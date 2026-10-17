"""Ferramentas dos testes da antifraud-api.

O teste fala com a API só por HTTP (R1). O histórico de cada cenário é
montado pela porta da frente: um POST por Pix anterior, com a data que o
cenário pede. A `transaction_date` vem no payload, então "ontem" e "três
meses atrás" se montam sem esperar o relógio.

O que tem aqui:
  - AntifraudApi: uma função por rota;
  - Pagador e Recebedor: uma pessoa com conta, documento, aparelho, IP e
    lugar fixos, para que vários Pix sejam "da mesma pessoa";
  - pix(): o payload do contrato, montado a partir das duas pontas;
  - pix_normal(): o payload da seção 3.1 do documento, com tudo novo;
  - mutar(): uma cópia do payload com um campo trocado;
  - quando(): datas com fuso, a partir de uma base;
  - AntifraudDb.reset(): zera as tabelas de movimento, e só isso;
  - os documentos dos seeds de demonstração.
"""
import copy
import random
import string
from datetime import datetime, timedelta, timezone
from os import environ
from uuid import uuid4
from zoneinfo import ZoneInfo

import requests
from sqlalchemy import create_engine

from tests.utils.random_generator import RandomGenerator


TOKEN = environ.get("INTERNAL_TOKEN", "default_token")
SAO_PAULO = ZoneInfo("America/Sao_Paulo")

API_FORA_DO_AR = (
    "Nao consegui falar com a antifraud-api em {endereco}.\n"
    "Ela precisa estar de pe pros testes rodarem. Suba com:  docker compose up -d --build --wait"
)

# As faixas de IP do mock (database/antifraud.sql). Sao faixas reservadas
# para documentacao, de proposito: nenhum IP real cai nelas.
REDE_SAO_PAULO = "198.51.100"
REDE_RECIFE = "203.0.113"
REDE_LISBOA = "192.0.2"
SAO_PAULO_GPS = (-23.56, -46.65)
RECIFE_GPS = (-8.05, -34.90)
LISBOA_GPS = (38.72, -9.14)

# Documentos dos seeds de demonstracao (database/antifraud.sql).
RECEBEDOR_MARCACAO_CRITICA = "529.982.247-25"
RECEBEDOR_ALERTA = "111.444.777-35"
RECEBEDOR_ALERTA_VENCIDO = "390.533.447-05"
RECEBEDOR_VITIMA = "123.456.789-09"
RECEBEDOR_NA_WATCHLIST = "275.484.389-23"
APARELHO_NA_WATCHLIST = "dvc-watchlist-0001"


def endereco_da_api() -> str:
    host = environ.get("SERVER_LOCALHOST", "127.0.0.1")
    porta = environ.get("ANTIFRAUD_API_PORT", "3020")
    return f"http://{host}:{porta}"


class AntifraudApi:
    @staticmethod
    def envia(metodo: str, caminho: str, token: str = TOKEN, **extras) -> requests.Response:
        cabecalhos = {"INTERNAL-TOKEN": token} if token is not None else {}
        try:
            return requests.request(metodo, endereco_da_api() + caminho, headers=cabecalhos, timeout=30, **extras)
        except requests.exceptions.ConnectionError:
            raise RuntimeError(API_FORA_DO_AR.format(endereco=endereco_da_api())) from None

    @staticmethod
    def health() -> requests.Response:
        return AntifraudApi.envia("GET", "/health_check", token=None)

    @staticmethod
    def post(payload: dict, token: str = TOKEN) -> requests.Response:
        return AntifraudApi.envia("POST", "/pix/transaction", token=token, json=payload)

    @staticmethod
    def get(pix_id: str, token: str = TOKEN) -> requests.Response:
        return AntifraudApi.envia("GET", f"/pix/transaction/{pix_id}", token=token)

    @staticmethod
    def put_limit(payload: dict) -> requests.Response:
        return AntifraudApi.envia("PUT", "/pix/account_limit", json=payload)

    @staticmethod
    def patch(pix_id: str, payload: dict) -> requests.Response:
        return AntifraudApi.envia("PATCH", f"/pix/transaction/{pix_id}", json=payload)


def analisa(payload: dict) -> dict:
    """Manda o Pix e devolve o corpo, exigindo 201 (ou 200 no replay)."""
    resposta = AntifraudApi.post(payload)
    assert resposta.status_code in (200, 201), resposta.text
    return resposta.json()


def regra(corpo: dict, codigo: str) -> dict:
    """O resultado de uma regra no metadata, ou None se ela nao foi listada."""
    for resultado in corpo["metadata"]["rules"]:
        if resultado["rule"] == codigo:
            return resultado
    return None


def pontos(corpo: dict, codigo: str) -> int:
    resultado = regra(corpo, codigo)
    return resultado["effective_points"] if resultado else 0


def disparou(corpo: dict, codigo: str) -> bool:
    resultado = regra(corpo, codigo)
    return resultado is not None and resultado["evaluation"] == "triggered"


def quando(base: datetime = None, **delta) -> str:
    """Data ISO com fuso de Sao Paulo, deslocada de `base` por `delta`."""
    base = base or BASE
    return (base + timedelta(**delta)).isoformat()


def nova_base() -> datetime:
    """Um dia util no passado, entre 10h e 17h, longe do relogio.

    Aleatoria de proposito: cada teste pede a sua base, e assim o IP e o
    aparelho de testes diferentes nao caem na mesma janela de tempo e nao
    se contam uns aos outros.
    """
    dias = random.randint(400, 1800)
    dia = datetime(2026, 9, 30, tzinfo=SAO_PAULO) - timedelta(days=dias)
    return dia.replace(hour=random.randint(10, 16), minute=random.randint(0, 59), second=random.randint(0, 59))


BASE = nova_base()


def novo_ip(rede: str = REDE_SAO_PAULO) -> str:
    return f"{rede}.{random.randint(1, 254)}"


def nova_conta() -> str:
    return "".join(random.choices(string.digits, k=8))


class Pagador:
    """Uma pessoa que paga: conta, documento, aparelho, IP e lugar fixos."""

    def __init__(self, documento: str = None, aberta_em: datetime = None, canal: str = "app",
                 rede: str = REDE_SAO_PAULO, gps=SAO_PAULO_GPS) -> None:
        self.documento = documento or RandomGenerator.generate_cpf()
        self.agencia = "0001"
        self.conta = nova_conta()
        self.aberta_em = aberta_em or datetime(2020, 1, 15, 10, 0, tzinfo=SAO_PAULO)
        self.aparelho = f"dvc-{uuid4().hex[:12]}"
        self.canal = canal
        self.ip = novo_ip(rede)
        self.gps = gps

    def conta_json(self) -> dict:
        return {
            "branch": self.agencia,
            "account_number": self.conta,
            "opening_date": self.aberta_em.isoformat(),
            "owner": {"document_number": self.documento},
        }


class Recebedor:
    """Uma pessoa que recebe: conta e documento fixos."""

    def __init__(self, documento: str = None, aberta_em: datetime = None, participante: str = "60701190",
                 pj: bool = False) -> None:
        if documento is None:
            documento = RandomGenerator.generate_cnpj() if pj else RandomGenerator.generate_cpf()
        self.documento = documento
        self.participante = participante
        self.agencia = "3675"
        self.conta = nova_conta()
        self.aberta_em = aberta_em or datetime(2019, 6, 1, 9, 0, tzinfo=SAO_PAULO)

    def conta_json(self) -> dict:
        return {
            "participant": self.participante,
            "branch": self.agencia,
            "account_number": self.conta,
            "opening_date": self.aberta_em.isoformat(),
            "owner": {"document_number": self.documento},
        }

    def como_pagador(self) -> "Pagador":
        """A mesma pessoa, agora pagando. A conta e a mesma, para o motor
        reconhecer o repasse: quem recebeu e quem esta pagando agora."""
        pagador = Pagador(documento=self.documento, aberta_em=self.aberta_em)
        pagador.agencia = self.agencia
        pagador.conta = self.conta
        return pagador


def pix(pagador: Pagador, recebedor: Recebedor, valor: int, data: str = None, **over) -> dict:
    """O payload do contrato a partir das duas pontas.

    `over` aceita: id, aparelho, ip, canal, gps (None tira a geolocalizacao).
    """
    gps = over.get("gps", pagador.gps)
    origem = {
        "device_id": over.get("aparelho", pagador.aparelho),
        "channel": over.get("canal", pagador.canal),
        "ip": over.get("ip", pagador.ip),
    }
    if gps is not None:
        origem["geolocation"] = {"latitude": gps[0], "longitude": gps[1]}
    return {
        "id": over.get("id", f"pix-{uuid4()}"),
        "amount": valor,
        "transaction_date": data or quando(),
        "source_account": pagador.conta_json(),
        "destination_account": recebedor.conta_json(),
        "source": origem,
    }


def pix_normal(**over) -> dict:
    """Um Pix de R$ 150 de dia, entre duas pessoas novas, sem nenhum sinal."""
    data = over.pop("data", None) or nova_base().isoformat()
    valor = over.pop("valor", 15000)
    return pix(Pagador(), Recebedor(), valor, data, **over)


def payload_do_documento() -> dict:
    """O payload da secao 3.1 do documento oficial, com id e contas novos.

    Os documentos sao trocados por novos para o teste nao depender do que
    outros testes ja gravaram com os CPFs do exemplo. As datas recuam 7 dias
    (17/10 vira 10/10, e a abertura do destino 10/10 vira 03/10): o horario,
    as 22:15, e a idade da conta destino, 7 dias e 13 horas, ficam iguais, e
    o teste deixa de depender do relogio (o 17/10 as 22:15 ja foi futuro).
    """
    corpo = {
        "id": f"pix-{uuid4()}",
        "amount": 150000,
        "transaction_date": "2026-10-10T22:15:00-03:00",
        "source_account": {
            "branch": "0001",
            "account_number": nova_conta(),
            "opening_date": "2025-03-02T10:00:00-03:00",
            "owner": {"document_number": RandomGenerator.generate_cpf()},
        },
        "destination_account": {
            "participant": "60701190",
            "branch": "3675",
            "account_number": nova_conta(),
            "opening_date": "2026-10-03T09:00:00-03:00",
            "owner": {"document_number": RandomGenerator.generate_cpf()},
        },
        "source": {
            "device_id": f"dvc-{uuid4().hex[:8]}",
            "channel": "app",
            "ip": "198.51.100.23",
            "geolocation": {"latitude": -23.56, "longitude": -46.65},
        },
    }
    return corpo


def mutar(payload: dict, caminho: str, valor) -> dict:
    """Uma copia do payload com o campo do caminho (com pontos) trocado.

    `valor` igual a `mutar.REMOVER` tira o campo.
    """
    copia = copy.deepcopy(payload)
    partes = caminho.split(".")
    alvo = copia
    for parte in partes[:-1]:
        alvo = alvo[parte]
    if valor is mutar.REMOVER:
        alvo.pop(partes[-1], None)
    else:
        alvo[partes[-1]] = valor
    return copia


mutar.REMOVER = object()


def agora_sp() -> datetime:
    return datetime.now(timezone.utc).astimezone(SAO_PAULO)


class AntifraudDb:
    """Zera as tabelas de movimento do banco antifraud.

    So zera: a politica, os status e os seeds de demonstracao ficam. Nunca
    monta cenario (R1): cenario se monta pela API.
    """

    @staticmethod
    def database_url() -> str:
        host = environ.get("SERVER_LOCALHOST", "127.0.0.1")
        porta = environ.get("DB_PORT", "5432")
        padrao = f"postgresql+psycopg2://bootcamp:bootcamp@{host}:{porta}/antifraud"
        return environ.get("ANTIFRAUD_DATABASE_URL_TESTS", padrao)

    @staticmethod
    def reset() -> None:
        engine = create_engine(AntifraudDb.database_url(), isolation_level="AUTOCOMMIT")
        try:
            with engine.connect() as conexao:
                conexao.exec_driver_sql(
                    "TRUNCATE pix_challenge_result, pix_rule_result, pix_analysis, account_limit, pix_account "
                    "RESTART IDENTITY CASCADE"
                )
        finally:
            engine.dispose()


def paga(payload: dict, confirma: bool = True) -> dict:
    """Manda o Pix e, se o motor pediu verificacao, confirma como o cliente faria.

    E assim que um historico de valores altos se forma pela porta da
    frente: o 2FA confirmado conta como dinheiro que saiu.
    """
    corpo = analisa(payload)
    if confirma and corpo["status"] == "two_factor_required":
        resposta = AntifraudApi.patch(payload["id"], {
            "challenge_result": "approved_by_client",
            "event_date": payload["transaction_date"],
        })
        assert resposta.status_code == 200, resposta.text
    return corpo


def historico(pagador: Pagador, valores: list, inicio: datetime, passo: timedelta, recebedor: Recebedor = None,
              recebedores_novos: bool = False) -> list:
    """Uma sequencia de Pix aprovados (ou confirmados) do pagador, a partir de `inicio`."""
    corpos = []
    for indice, valor in enumerate(valores):
        destino = Recebedor() if recebedores_novos else (recebedor or Recebedor())
        if recebedor is None and not recebedores_novos:
            recebedor = destino
        corpos.append(paga(pix(pagador, destino, valor, (inicio + passo * indice).isoformat())))
    return corpos
