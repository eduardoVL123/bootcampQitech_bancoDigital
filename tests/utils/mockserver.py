"""O Mockserver nos testes da onboarding-api (plano, seção 2.2).

O Mockserver faz o papel de quem está fora: a Receita, as listas de
sanções e de PEP, e a account-api. O teste programa a resposta de cada
um, presa ao documento ou à customer_key do próprio teste, e depois
confere o que o worker pediu. Nenhum teste apaga o que outro programou.

O que tem aqui:
  - Mockserver: programar, consultar os pedidos recebidos e esperar ficar de pé;
  - receita_responde, sancoes_respondem, pep_responde e account_api_responde:
    a resposta de cada vizinho, no contrato da seção 2.2 do plano;
  - biros_regulares: os três birôs dizendo que está tudo certo;
  - receita_fora_do_ar, receita_demora e receita_derruba_a_conexao: a Receita
    sem resposta, só em algumas chamadas (F7);
  - saude_do_biro: a chamada de teste de um birô, que a retentativa em lote faz (F7).
"""
import json
import time
from os import environ
from uuid import uuid4

import requests


ROTA_DA_RECEITA = "/receita/v1/consulta"
ROTA_DAS_SANCOES = "/sancoes/v1/consulta"
ROTA_DO_PEP = "/pep/v1/consulta"
ROTA_DA_ACCOUNT_API = "/internal/account"

# A chamada de teste de cada birô (RFC 05, decisão D29). O Mockserver sobe
# com as três respondendo 200 (mockserver/saude-dos-biros.json).
ROTA_DA_SAUDE = {
    "receita": "/receita/v1/health",
    "sancoes": "/sancoes/v1/health",
    "pep": "/pep/v1/health",
}

# A falha programada pelo teste ganha da resposta regular, que fica por baixo.
PRIORIDADE_DA_FALHA = 10

# A senha com que o worker se apresenta à account-api. O teste confere
# que ela chegou, com o mesmo valor que o compose passa para o worker.
TOKEN_DE_SERVICO = environ.get("SERVICE_TOKEN", "service_token_de_estudo")

MOCKSERVER_FORA_DO_AR = (
    "Nao consegui falar com o Mockserver em {endereco}.\n"
    "Ele sobe junto com o compose:  docker compose up -d --build --wait"
)


def endereco_do_mockserver() -> str:
    host = environ.get("SERVER_LOCALHOST", "127.0.0.1")
    return environ.get("MOCKSERVER_URL", f"http://{host}:1080")


class Mockserver:
    ja_esta_de_pe = False

    @staticmethod
    def envia(caminho: str, corpo: dict) -> requests.Response:
        Mockserver.espera_ficar_de_pe()
        return requests.put(f"{endereco_do_mockserver()}{caminho}", json=corpo, timeout=10)

    @staticmethod
    def espera_ficar_de_pe(limite_segundos: float = 30) -> None:
        """O Mockserver não tem checagem de saúde no compose (a imagem não tem
        shell nem curl). Antes do primeiro uso, o teste espera ele responder."""
        if Mockserver.ja_esta_de_pe:
            return

        endereco = endereco_do_mockserver()
        fim = time.monotonic() + limite_segundos
        while True:
            try:
                if requests.put(f"{endereco}/mockserver/status", timeout=2).status_code == 200:
                    Mockserver.ja_esta_de_pe = True
                    return
            except requests.exceptions.ConnectionError:
                pass
            if time.monotonic() > fim:
                raise RuntimeError(MOCKSERVER_FORA_DO_AR.format(endereco=endereco))
            time.sleep(0.5)

    @staticmethod
    def programa(
        rota: str,
        corpo_esperado: dict,
        status: int,
        resposta: dict,
        vezes: int = None,
        prioridade: int = 0,
        atraso_segundos: int = None,
    ) -> None:
        """Quando chegar um POST na rota com estes campos no corpo, responde assim.
        `vezes` limita quantas vezes a resposta vale; `prioridade` maior ganha;
        `atraso_segundos` segura a resposta antes de mandar."""
        expectativa = {
            "httpRequest": Mockserver.pedido_post(rota, corpo_esperado),
            "httpResponse": {
                "statusCode": status,
                "headers": {"Content-Type": ["application/json"]},
                "body": json.dumps(resposta),
            },
            "priority": prioridade,
        }
        if atraso_segundos is not None:
            expectativa["httpResponse"]["delay"] = {"timeUnit": "SECONDS", "value": atraso_segundos}

        Mockserver.registra(expectativa, vezes)

    @staticmethod
    def derruba_a_conexao(rota: str, corpo_esperado: dict, vezes: int, prioridade: int = PRIORIDADE_DA_FALHA) -> None:
        """Quando chegar um POST na rota com estes campos no corpo, fecha a
        conexão sem responder nada."""
        expectativa = {
            "httpRequest": Mockserver.pedido_post(rota, corpo_esperado),
            "httpError": {"dropConnection": True},
            "priority": prioridade,
        }
        Mockserver.registra(expectativa, vezes)

    @staticmethod
    def programa_get(rota: str, status: int, vezes: int, validade_segundos: int, prioridade: int = PRIORIDADE_DA_FALHA) -> None:
        """Quando chegar um GET na rota, responde com este status, por no máximo
        `vezes` vezes e `validade_segundos` segundos. A validade garante que a
        resposta some sozinha, mesmo se ninguém a usar."""
        expectativa = {
            "httpRequest": {"method": "GET", "path": rota},
            "httpResponse": {"statusCode": status},
            "priority": prioridade,
            "timeToLive": {"timeUnit": "SECONDS", "timeToLive": validade_segundos, "unlimited": False},
        }
        Mockserver.registra(expectativa, vezes)

    @staticmethod
    def pedido_post(rota: str, corpo_esperado: dict) -> dict:
        return {
            "method": "POST",
            "path": rota,
            "body": {"type": "JSON", "json": corpo_esperado, "matchType": "ONLY_MATCHING_FIELDS"},
        }

    @staticmethod
    def registra(expectativa: dict, vezes: int = None) -> None:
        if vezes is not None:
            expectativa["times"] = {"remainingTimes": vezes, "unlimited": False}

        resposta_do_mockserver = Mockserver.envia("/mockserver/expectation", expectativa)
        assert resposta_do_mockserver.status_code == 201, resposta_do_mockserver.text

    @staticmethod
    def pedidos(corpo_esperado: dict, rota: str = None) -> list:
        """Os pedidos que o Mockserver recebeu com estes campos no corpo, na
        ordem em que chegaram. Sem `rota`, de todas as rotas."""
        filtro = {"body": {"type": "JSON", "json": corpo_esperado, "matchType": "ONLY_MATCHING_FIELDS"}}
        if rota is not None:
            filtro["path"] = rota

        resposta = Mockserver.envia("/mockserver/retrieve?type=REQUESTS&format=JSON", filtro)
        assert resposta.status_code == 200, resposta.text
        return resposta.json() or []


def cabecalho(pedido: dict, nome: str):
    """O valor de um cabeçalho de um pedido gravado pelo Mockserver."""
    for chave, valores in pedido.get("headers", {}).items():
        if chave.lower() == nome.lower():
            return valores[0]
    return None


def corpo(pedido: dict) -> dict:
    """O corpo JSON de um pedido gravado pelo Mockserver."""
    conteudo = pedido.get("body")
    if isinstance(conteudo, dict):
        conteudo = conteudo.get("json", conteudo.get("string"))
    if isinstance(conteudo, str):
        return json.loads(conteudo)
    return conteudo


# ----------------------------------------------------------------------
# Cada vizinho, no contrato da seção 2.2 do plano
# ----------------------------------------------------------------------

def receita_responde(dados: dict, situacao: str = None, nome: str = None, data: str = None) -> None:
    """A Receita, para o documento destes dados. Sem trocas, devolve os
    mesmos nome e data do cadastro, e a situação regular (REGULAR na PF,
    ATIVA na PJ)."""
    resposta = {"protocol": f"RF-{uuid4().hex[:12]}"}

    if situacao is None:
        situacao = "REGULAR" if dados["type"] == "PF" else "ATIVA"
    resposta["situacao"] = situacao

    if situacao != "NAO_ENCONTRADO":
        resposta["name"] = nome if nome is not None else dados["name"]
        campo_da_data = "birth_date" if dados["type"] == "PF" else "opening_date"
        resposta[campo_da_data] = data if data is not None else dados[campo_da_data]

    Mockserver.programa(ROTA_DA_RECEITA, {"document_number": dados["document_number"]}, 200, resposta)


def sancoes_respondem(dados: dict, match: bool = False) -> None:
    resposta = {"match": match, "protocol": f"SC-{uuid4().hex[:12]}"}
    Mockserver.programa(ROTA_DAS_SANCOES, {"document_number": dados["document_number"]}, 200, resposta)


def pep_responde(dados: dict, pep: bool = False) -> None:
    resposta = {"pep": pep, "protocol": f"PEP-{uuid4().hex[:12]}"}
    Mockserver.programa(ROTA_DO_PEP, {"document_number": dados["document_number"]}, 200, resposta)


def account_api_responde(abertura: dict, dados: dict, status: int = 201, account_key: str = None, vezes: int = None, prioridade: int = 0) -> str:
    """A account-api abrindo (201) ou devolvendo a conta que já existia (200)
    para o cliente desta abertura. Devolve a account_key da resposta."""
    if account_key is None:
        account_key = str(uuid4())

    resposta = {"account_key": account_key, "customer_key": abertura["customer_key"], "type": dados["type"], "status": "ACTIVE"}
    if status >= 400:
        resposta = {"code": "QIT002999", "title": "Unavailable"}

    Mockserver.programa(ROTA_DA_ACCOUNT_API, {"customer_key": abertura["customer_key"]}, status, resposta, vezes, prioridade)
    return account_key


def biros_regulares(dados: dict) -> None:
    """Receita regular, com os mesmos dados do cadastro; fora das sanções; não é PEP."""
    receita_responde(dados)
    sancoes_respondem(dados)
    pep_responde(dados)


def pedidos_aos_biros(dados: dict) -> list:
    """As rotas dos birôs consultadas para este documento, na ordem em que chegaram."""
    return [pedido["path"] for pedido in Mockserver.pedidos({"document_number": dados["document_number"]})]


def pedidos_a_receita(dados: dict) -> list:
    return Mockserver.pedidos({"document_number": dados["document_number"]}, ROTA_DA_RECEITA)


# ----------------------------------------------------------------------
# Birô fora do ar (F7)
#
# Cada falha vale só para o documento do teste e só pelas `vezes` pedidas,
# com prioridade maior que a resposta regular. Quando as falhas acabam, a
# Receita "volta": quem chama de novo recebe o que estiver por baixo.
# ----------------------------------------------------------------------

def receita_fora_do_ar(dados: dict, vezes: int) -> None:
    """A Receita responde 503 para este documento nas próximas `vezes` chamadas."""
    resposta = {"code": "RECEITA_INDISPONIVEL", "message": "Servico indisponivel"}
    Mockserver.programa(
        ROTA_DA_RECEITA, {"document_number": dados["document_number"]}, 503, resposta, vezes, PRIORIDADE_DA_FALHA
    )


def receita_demora(dados: dict, segundos: int, vezes: int) -> None:
    """A Receita responde regular para este documento, mas só depois de `segundos`,
    nas próximas `vezes` chamadas. Se chegasse a tempo, a resposta aprovaria."""
    resposta = {
        "situacao": "REGULAR" if dados["type"] == "PF" else "ATIVA",
        "name": dados["name"],
        "protocol": f"RF-{uuid4().hex[:12]}",
    }
    campo_da_data = "birth_date" if dados["type"] == "PF" else "opening_date"
    resposta[campo_da_data] = dados[campo_da_data]

    Mockserver.programa(
        ROTA_DA_RECEITA,
        {"document_number": dados["document_number"]},
        200,
        resposta,
        vezes,
        PRIORIDADE_DA_FALHA,
        atraso_segundos=segundos,
    )


def receita_derruba_a_conexao(dados: dict, vezes: int) -> None:
    """A Receita fecha a conexão sem responder, para este documento, nas próximas `vezes` chamadas."""
    Mockserver.derruba_a_conexao(ROTA_DA_RECEITA, {"document_number": dados["document_number"]}, vezes)


def saude_do_biro(biro: str, status: int) -> None:
    """A próxima chamada de teste do birô (receita, sancoes ou pep) responde
    com este status. Vale uma vez só, e some em 30 s se ninguém chamar: a
    chamada de teste é de todos, e não pode sobrar para outro teste."""
    Mockserver.programa_get(ROTA_DA_SAUDE[biro], status, vezes=1, validade_segundos=30)


def pedidos_a_account_api(abertura: dict) -> list:
    return Mockserver.pedidos({"customer_key": abertura["customer_key"]}, ROTA_DA_ACCOUNT_API)
