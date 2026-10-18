"""Bancada de testes da antifraud-api: massa sintetica e benchmark.

Convive com o tools/cenarios_antifraude.py, que e a massa da propria equipe
da API, montada com o tests/utils/pix.py dos testes dela. Este aqui e a
bancada do RFC: payloads e gabarito em arquivos separados.

Dois modos, sempre de fora da API (black-box):

  python tools/bancada_rfc_antifraude.py --generate
      Monta a linha do tempo de todos os cenarios e grava dois arquivos
      independentes em tools/: os payloads (so o que vai para a API) e o
      gabarito (o que a API deveria responder a cada um).

  python tools/bancada_rfc_antifraude.py --run
      Le os dois arquivos, dispara cada payload na ordem, confere o
      GET /pix/transaction/{id} e compara com o gabarito.

O tempo dos cenarios e o transaction_date de cada Pix, nao o relogio da
maquina. Por isso a lista e cronologica: o historico de cada cliente precisa
chegar antes da transacao que depende dele. A linha do tempo termina em
2026-10-17 as 23h; antes disso a API recusa os Pix "do futuro", a menos que
o TIME_SKEW_SECONDS dela esteja alto.

Os ids sao fixos: repetir o --run no mesmo banco devolve a analise ja
gravada (replay), sem analisar de novo. Para medir de novo, zere o banco
antifraud.

Gabarito, campo a campo:
  expected_status       string ou lista de aceitos; null nao confere
  expected_auth_level   idem; "none" quando aprovado sem autenticacao
  expected_scenario     string ou null
  expected_rules        codigos que precisam aparecer; "!CODIGO" nao pode
  category              warmup e setup preparam terreno e ficam fora das
                        taxas; legit_clear e legit_hard sao trafego normal;
                        evasion e fraud_clear sao trafego fraudulento
"""

import argparse
import json
import os
import statistics
import sys
import time
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

from laboratorio.api import cenario as _cenario
from laboratorio.api import latencia as _latencia
from laboratorio.api import nivel as _nivel
from laboratorio.api import regras as _regras
from laboratorio.api import status as _status
from laboratorio import pix_base as pix_utils

PASTA = Path(__file__).resolve().parent
ARQUIVO_PAYLOADS = PASTA / "bancada_teste_payloads.json"
ARQUIVO_GABARITO = PASTA / "bancada_teste_gabarito.json"

BRT = timezone(timedelta(hours=-3))
HOJE = "2026-10-17"
SEM_GPS = object()  # marcador para "este Pix nao manda geolocation"

NORMAL = ("legit_clear", "legit_hard")
FRAUDE = ("evasion", "fraud_clear")

# Quando a API pede selfie, quem confirma e o titular. Nos Pix legitimos e
# no aquecimento ele confirma (approved_by_client), e e assim que o
# historico de valores altos se forma. Nas burlas e fraudes ninguem
# confirma: o resultado fica como a API decidiu.
CONFIRMA_DESAFIO = ("warmup",) + NORMAL


def quando(data: str, hora: str = "14:00") -> datetime:
    ano, mes, dia = (int(x) for x in data.split("-"))
    hh, mm = (int(x) for x in hora.split(":"))
    return datetime(ano, mes, dia, hh, mm, tzinfo=BRT)


# ----------------------------------------------------------------------
# Personas e contas
# ----------------------------------------------------------------------

class Gerador:
    """Documentos, contas e aparelhos deterministicos.

    Rodar o --generate duas vezes produz os mesmos arquivos, o que deixa
    o diff do gabarito legivel quando um cenario muda.
    """

    def __init__(self):
        self._n = 0
        self._ips = 0

    def _proximo(self) -> int:
        self._n += 1
        return self._n

    def cpf(self) -> str:
        return pix_utils.cpf_com_digitos(f"{(123456789 + self._proximo() * 7919) % 10 ** 9:09d}")

    def cnpj(self) -> str:
        return pix_utils.cnpj_com_digitos(f"{(10000000 + self._proximo() * 104729) % 10 ** 8:08d}0001")

    def aparelho(self, nome: str) -> str:
        """device_id opaco: o nome da persona nao pode chegar a API, senao vira dica da resposta."""
        return f"device-{uuid.uuid5(uuid.NAMESPACE_URL, 'bancada/' + nome).hex[:16]}"

    def conta(self, aberta_em: str = pix_utils.CONTA_ANTIGA) -> dict:
        return {"branch": "0001", "account_number": f"{100000 + self._proximo():06d}",
                "opening_date": pix_utils.abertura(aberta_em)}

    def pessoa(self, apelido: str, pj: bool = False, aberta_em: str = pix_utils.CONTA_ANTIGA,
               documento: str = None, canal: str = "app") -> dict:
        return {
            "apelido": apelido,
            "document_number": documento or (self.cnpj() if pj else self.cpf()),
            "account": self.conta(aberta_em),
            "participant": pix_utils.PARTICIPANTE_CASA,
            "device_id": self.aparelho(apelido),
            "ip": self.ip(),
            "channel": canal,
        }

    def ip(self) -> str:
        """Um IP por persona, dentro da faixa de SP. IP unico para todos faria a
        API ver dezenas de titulares no mesmo IP (IP_COMPARTILHADO) sem motivo."""
        self._ips += 1
        return f"{pix_utils.IP_SP.rsplit('.', 1)[0]}.{2 + self._ips % 252}"


class Bancada:
    """Junta payloads e gabarito e devolve os dois em ordem cronologica."""

    def __init__(self):
        self.gerador = Gerador()
        self._itens = []
        self._seq = 0

    def _novo_id(self) -> str:
        self._seq += 1
        return f"pix-bt-{self._seq:04d}"

    def pix(self, origem: dict, destino: dict, amount: int, em: datetime, *,
            cenario: str, categoria: str, status=None, nivel=None, cenario_api=None,
            regras=None, porque: str = "", pix_id: str = None, device: str = None,
            ip: str = None, gps=None, canal: str = None,
            conta_destino: dict = None) -> str:
        assert isinstance(amount, int), "amount sempre em centavos inteiros"
        pix_id = pix_id or self._novo_id()
        canal = canal or origem["channel"]
        if gps is None:
            gps = pix_utils.GPS_SP if canal == "app" else SEM_GPS

        corpo = pix_utils.pix_normal(id=pix_id, amount=amount, transaction_date=em.isoformat())
        corpo = pix_utils.mutar(corpo, "source_account", {
            **origem["account"], "owner": {"document_number": origem["document_number"]},
        })
        corpo = pix_utils.mutar(corpo, "destination_account", {
            "participant": destino["participant"], **(conta_destino or destino["account"]),
            "owner": {"document_number": destino["document_number"]},
        })
        corpo = pix_utils.mutar(corpo, "source", {"device_id": device or origem["device_id"], "channel": canal,
                                                  "ip": ip or origem["ip"]})
        if gps is not SEM_GPS:
            corpo = pix_utils.mutar(corpo, "source.geolocation", gps)

        self._adiciona(em, pix_id, "POST", "/pix/transaction", corpo,
                       cenario, categoria, status, nivel, cenario_api, regras, porque)
        return pix_id

    def _adiciona(self, em, item_id, metodo, caminho, corpo, cenario, categoria,
                  status, nivel, cenario_api, regras, porque):
        if categoria == "warmup":
            # O aquecimento nao e julgado: selfie pedida e confirmada pelo titular
            # forma o mesmo historico que a aprovacao direta. So a rejeicao quebra.
            status = ["approved", "two_factor_required"]
        if status == "approved" and nivel is None:
            nivel = "none"
        self._itens.append((em, len(self._itens), {
            "id": item_id, "method": metodo, "path": caminho, "body": corpo,
        }, {
            "id": item_id,
            "scenario_name": cenario,
            "category": categoria,
            "expected_status": status,
            "expected_auth_level": nivel,
            "expected_scenario": cenario_api,
            "expected_rules": list(regras or []),
            "rationale": porque,
        }))

    def aquecer(self, origem: dict, destinos: list, valores: list, dias: list, *,
                cenario: str, hora: str = "12:00"):
        """Historico aprovado: um Pix por dia, girando entre os destinos."""
        for i, (valor, dia) in enumerate(zip(valores, dias)):
            self.pix(origem, destinos[i % len(destinos)], valor, quando(dia, hora),
                     cenario=cenario, categoria="warmup", status="approved",
                     porque="historico de base para os cenarios desta persona")

    def cliente_com_historico(self, apelido: str, faixa: tuple) -> tuple:
        """Persona de apoio: 6 Pix na faixa de valor, para 2 contrapartes."""
        cliente = self.gerador.pessoa(apelido)
        conhecidos = [self.gerador.pessoa(f"{apelido}-contraparte-{i}") for i in (1, 2)]
        menor, maior = faixa
        passo = (maior - menor) // 5
        valores = [menor + passo * i for i in (0, 3, 1, 5, 2, 4)]
        dias = ["2026-09-21", "2026-09-26", "2026-10-01", "2026-10-06", "2026-10-10", "2026-10-14"]
        self.aquecer(cliente, conhecidos, valores, dias, cenario=f"aquecimento_{apelido}")
        return cliente, conhecidos[0]

    def ordenado(self) -> tuple:
        itens = sorted(self._itens, key=lambda item: (item[0], item[1]))
        return [i[2] for i in itens], [i[3] for i in itens]


# ----------------------------------------------------------------------
# Linha do tempo dos cenarios
# ----------------------------------------------------------------------

def monta_bancada() -> Bancada:
    b = Bancada()
    g = b.gerador

    # Fase 0: aquecimento ------------------------------------------------

    # Persona A: cliente regular. 12 Pix pequenos em 10 dias e o aluguel
    # de todo dia 05 para a mesma imobiliaria.
    persona_a = g.pessoa("persona-a")
    loja_c = g.pessoa("loja-c", pj=True, aberta_em="2019-05-02")
    mercado = g.pessoa("mercado", pj=True)
    farmacia = g.pessoa("farmacia", pj=True)
    imobiliaria = g.pessoa("imobiliaria", pj=True, aberta_em="2015-08-20")

    rotina_a = [
        ("2026-09-18", "10:20", 4200, loja_c), ("2026-09-20", "18:40", 7800, mercado),
        ("2026-09-23", "12:10", 3900, loja_c), ("2026-09-26", "09:30", 3000, farmacia),
        ("2026-09-26", "19:15", 8600, mercado), ("2026-09-29", "13:05", 5100, loja_c),
        ("2026-10-02", "11:45", 4700, loja_c), ("2026-10-06", "17:20", 6200, loja_c),
        ("2026-10-09", "10:00", 9000, mercado), ("2026-10-09", "16:30", 3400, farmacia),
        ("2026-10-12", "12:40", 5500, loja_c), ("2026-10-15", "18:00", 6800, mercado),
    ]
    for dia, hora, valor, destino in rotina_a:
        b.pix(persona_a, destino, valor, quando(dia, hora), cenario="aquecimento_persona_a",
              categoria="warmup", status="approved", porque="rotina de compras da persona A")
    for dia in ("2026-07-05", "2026-08-05", "2026-09-05"):
        b.pix(persona_a, imobiliaria, 250000, quando(dia, "14:00"), cenario="aquecimento_persona_a_aluguel",
              categoria="warmup", status="approved", porque="aluguel mensal, sempre no dia 05")

    # Persona B: PJ que paga o mesmo fornecedor por integracao (API).
    persona_b = g.pessoa("persona-b", pj=True, aberta_em="2018-02-14", canal="api")
    fornecedor = g.pessoa("fornecedor-b", pj=True, aberta_em="2017-11-03")
    for dia in ("2026-09-20", "2026-09-25", "2026-09-30", "2026-10-06", "2026-10-13"):
        b.pix(persona_b, fornecedor, 4000000, quando(dia, "10:00"), cenario="aquecimento_persona_b",
              categoria="warmup", status="approved", porque="pagamento recorrente de R$ 40 mil ao fornecedor")

    # Persona C: loja que recebe muito, de muita gente, em 8 dias ativos.
    # 6 dos 25 recebimentos sao da propria persona A (rotina acima).
    dias_extra_c = ["2026-09-18", "2026-09-21", "2026-09-23", "2026-09-29",
                    "2026-10-02", "2026-10-06", "2026-10-12", "2026-10-14"]
    for i in range(19):
        comprador = g.pessoa(f"comprador-loja-{i + 1:02d}")
        dia = dias_extra_c[i % len(dias_extra_c)]
        b.pix(comprador, loja_c, 2000 + 350 * i, quando(dia, f"{9 + i % 10:02d}:{(i * 7) % 60:02d}"),
              cenario="aquecimento_persona_c", categoria="warmup", status="approved",
              porque="compra na loja C, que acumula 25 recebimentos em 8 dias")

    # Personas de apoio: cada burla usa um cliente proprio, para um
    # cenario nao contaminar o historico do outro.
    persona_d, conhecido_d = b.cliente_com_historico("persona-d", (100000, 200000))
    persona_e, _ = b.cliente_com_historico("persona-e", (250000, 320000))
    persona_f, _ = b.cliente_com_historico("persona-f", (80000, 150000))
    # A persona-g era a do limite do cliente, que saiu do motor (vai para o BAS). Ela continua sendo
    # criada para o sorteio das personas seguintes nao mudar.
    b.cliente_com_historico("persona-g", (80000, 150000))
    persona_h, conhecido_h = b.cliente_com_historico("persona-h", (3000, 9000))
    persona_i, conhecido_i = b.cliente_com_historico("persona-i", (3000, 9000))
    persona_j, conhecido_j = b.cliente_com_historico("persona-j", (3000, 9000))
    persona_m, _ = b.cliente_com_historico("persona-m", (3000, 9000))
    persona_n, _ = b.cliente_com_historico("persona-n", (3000, 9000))

    # Fase 1: transacoes nitidamente legitimas -----------------------------

    b.pix(persona_a, loja_c, 4500, quando(HOJE, "11:00"),
          cenario="rotina_diaria", categoria="legit_clear",
          status="approved", cenario_api="pagamento_recorrente",
          porque="valor na mediana, destino habitual, aparelho e GPS de sempre: o destino de sempre da o "
                 "pagamento_recorrente, que vem antes de sem_alerta_relevante na ordem dos cenarios")

    b.pix(persona_a, persona_a, 150000, quando(HOJE, "11:30"),
          conta_destino=g.conta(aberta_em="2020-01-15"),
          cenario="mesma_titularidade", categoria="legit_hard",
          status="two_factor_required", nivel="facial_document", regras=["PERFIL", "MESMA_TITULARIDADE"],
          porque="R$ 1.500 para conta do mesmo CPF, muito acima dos picos do titular: decisao do time, "
                 "conta do mesmo dono tambem pode ser tomada, e MESMA_TITULARIDADE so desconta 10")

    # Fase 2: legitimas que parecem fraude ---------------------------------

    b.pix(persona_a, imobiliaria, 250000, quando("2026-10-05", "14:00"),
          cenario="aluguel_recorrente", categoria="legit_hard",
          status="approved", cenario_api="pagamento_recorrente",
          regras=["DESTINO_CONFIAVEL", "!PERFIL"],
          porque="50x a mediana, mas e o par de sempre no dia de sempre: a referencia do par neutraliza PERFIL")

    b.pix(persona_b, fornecedor, 4200000, quando(HOJE, "10:00"),
          cenario="fornecedor_alto_valor_compativel", categoria="legit_hard",
          status="approved", regras=["!LIMITE_POR_PIX"],
          porque="R$ 42 mil e alto, mas compativel com o fornecedor habitual: o corte do LIMITE_POR_PIX nao dispara "
                 "(a regra volta not_triggered, com o motivo no detail)")

    imobiliaria_nova = g.pessoa("imobiliaria-nova", pj=True, aberta_em="2016-04-11")
    b.pix(persona_a, imobiliaria_nova, 280000, quando(HOJE, "14:00"),
          cenario="primeiro_aluguel_inedito", categoria="legit_hard",
          status="two_factor_required", nivel=["facial", "facial_document"],
          regras=["PERFIL", "CONTRAPARTE_INEDITA"],
          porque="valor fora do perfil para CNPJ nunca pago, mas aparelho e GPS habituais: pede prova, nunca rejeita")

    b.pix(persona_a, loja_c, 3500, quando(HOJE, "02:30"),
          cenario="madrugada_baixo_valor", categoria="legit_hard", status="approved",
          porque="madrugada sozinha, com R$ 35 para destino habitual, nao justifica atrito")

    b.pix(persona_b, fornecedor, 10000, quando(HOJE, "15:00"), canal="api",
          cenario="canal_api_sem_gps", categoria="legit_hard", status="approved",
          porque="integracao por API nao tem GPS; a ausencia so pesa no canal app")

    vitima = g.pessoa("vitima", documento=pix_utils.DOC_VITIMA)
    b.pix(persona_h, vitima, 5000, quando("2026-10-16", "14:00"),
          cenario="recebedor_vitima_cadastro", categoria="legit_hard", status="approved",
          porque="ser vitima registrada nao torna a conta suspeita para receber")

    # Fase 3: tentativas de burla -------------------------------------------

    destino_oficial = g.pessoa("destino-oficial", aberta_em="2026-10-10")
    b.pix(persona_d, destino_oficial, 150000, quando(HOJE, "22:15"), pix_id="pix-000123",
          cenario="exemplo_oficial_qitech", categoria="evasion",
          status="two_factor_required", nivel="facial", cenario_api="primeiro_pagamento",
          regras=["NOTURNO", "DESTINO_NOVO"],
          porque="45 pts: NOTURNO 25 + DESTINO_NOVO 20 (conta aberta ha 7 dias); valor dentro do perfil da persona D")

    destino_fatias = g.pessoa("destino-fatias")
    for n, hora in enumerate(("09:00", "09:12", "09:25", "09:40"), start=1):
        ultima = n == 4
        b.pix(persona_e, destino_fatias, 290000, quando(HOJE, hora),
              cenario="burla_fatiamento_smurfing" + ("" if ultima else f".fatia_{n}"),
              categoria="evasion" if ultima else "setup",
              status="two_factor_required" if ultima else None,
              cenario_api="esvaziamento_fatiado" if ultima else None,
              regras=["FATIAMENTO"] if ultima else None,
              porque=("4a fatia de R$ 2.900 em 40 min: FATIAMENTO +40" if ultima
                      else "fatia que monta o padrao, sem conferencia propria"))

    destino_sonda = g.pessoa("destino-sondagem")
    b.pix(persona_f, destino_sonda, 2500000, quando(HOJE, "10:00"),
          cenario="burla_sondagem_de_limite.tentativa_alta", categoria="evasion",
          status=["two_factor_required", "rejected"],
          porque="R$ 25 mil, muito acima do perfil: precisa ser barrado ou pedir prova")
    b.pix(persona_f, destino_sonda, 1500000, quando(HOJE, "10:05"),
          cenario="burla_sondagem_de_limite.recuo", categoria="setup",
          porque="primeiro recuo de valor depois do bloqueio")
    b.pix(persona_f, destino_sonda, 80000, quando(HOJE, "10:12"),
          cenario="burla_sondagem_de_limite", categoria="evasion",
          status="two_factor_required", nivel="facial_document", cenario_api="sondagem_de_limite",
          regras=["SONDAGEM_DE_LIMITE"],
          porque="valores caindo em sequencia para o mesmo destino em 12 min: SONDAGEM_DE_LIMITE +50")

    b.pix(persona_h, conhecido_h, 2500000, quando(HOJE, "23:00"), gps=SEM_GPS,
          cenario="burla_gps_desligado_noturno_alto", categoria="evasion",
          status="rejected", regras=["NOTURNO", "GEO_AUSENTE"],
          porque="65 pts em movimentacao + 20 em acesso (GPS desligado no app) = 85 pts com 2 eixos >= 20")

    b.pix(persona_i, conhecido_i, 5000, quando(HOJE, "15:00"), ip=pix_utils.IP_RECIFE,
          cenario="burla_spoofing_geo_ip_divergente", categoria="evasion",
          regras=["GEO_IP_DIVERGENTE"],
          porque="GPS diz Sao Paulo e o IP diz Recife: GEO_IP_DIVERGENTE +30")

    b.pix(persona_j, conhecido_j, 5000, quando(HOJE, "17:00"),
          cenario="burla_viagem_impossivel_fallback_ip.referencia_sp", categoria="setup",
          porque="Pix de referencia em Sao Paulo")
    b.pix(persona_j, conhecido_j, 5000, quando(HOJE, "17:15"), gps=SEM_GPS, ip=pix_utils.IP_RECIFE,
          cenario="burla_viagem_impossivel_fallback_ip", categoria="evasion",
          regras=["VIAGEM_IMPOSSIVEL", "GEO_AUSENTE"],
          porque="sem GPS a API cai no IP: Recife 15 min depois de SP e VIAGEM_IMPOSSIVEL +40, e GEO_AUSENTE +20")

    imobiliaria_falsa = g.pessoa("imobiliaria-falsa", pj=True, aberta_em="2019-09-09")
    b.pix(persona_a, imobiliaria_falsa, 250000, quando("2026-09-22", "14:00"), device=g.aparelho("persona-a-novo-1"),
          cenario="burla_falso_aluguel_fora_da_janela", categoria="evasion",
          status=["two_factor_required", "rejected"], cenario_api="primeiro_pagamento",
          regras=["APARELHO_NOVO", "CONTRAPARTE_INEDITA"],
          porque="valor de aluguel no dia 22, de aparelho novo para quem nunca recebeu: retido pelo aparelho e pelo "
                 "recebedor (o PADRAO_MENSAL, que olhava a janela do mes, saiu do motor)")

    # Fase 4: fraudes nitidas -----------------------------------------------

    b.pix(persona_a, loja_c, 4000, quando(HOJE, "16:00"),
          cenario="conta_tomada_ruptura_contexto.referencia_sp", categoria="setup",
          porque="ultimo Pix legitimo da persona A, em Sao Paulo")
    destino_tomada = g.pessoa("destino-tomada", aberta_em=HOJE)
    b.pix(persona_a, destino_tomada, 300000, quando(HOJE, "16:15"), device=g.aparelho("persona-a-novo-2"),
          ip=pix_utils.IP_RECIFE, gps=pix_utils.GPS_RECIFE,
          cenario="conta_tomada_ruptura_contexto", categoria="fraud_clear",
          status="rejected", cenario_api="conta_tomada",
          regras=["APARELHO_NOVO", "VIAGEM_IMPOSSIVEL", "PERFIL", "DESTINO_NOVO"],
          porque="aparelho novo, Recife 15 min depois de SP, 60x a mediana, conta destino aberta hoje")

    laranja = g.pessoa("laranja-fan-in", aberta_em="2026-10-15")
    for n in range(1, 11):
        ultimo = n == 10
        pagador = g.pessoa(f"pagador-laranja-{n:02d}")
        b.pix(pagador, laranja, 30000 + 5000 * n, quando(HOJE, f"19:{(n - 1) * 6:02d}"),
              cenario="conta_laranja_fan_in" + ("" if ultimo else f".pagador_{n:02d}"),
              categoria="fraud_clear" if ultimo else "setup",
              status=["two_factor_required", "rejected"] if ultimo else None,
              cenario_api="conta_laranja" if ultimo else None,
              regras=["CONTA_LARANJA", "DESTINO_NOVO"] if ultimo else None,
              porque=("10o pagador distinto em 54 min para conta de 2 dias: CONTA_LARANJA +60, DESTINO_NOVO +20"
                      if ultimo else "pagador que alimenta o fan-in"))

    repassador = g.pessoa("repassador")
    b.aquecer(repassador, [g.pessoa("repassador-contraparte")], [3000, 4500, 6000],
              ["2026-09-25", "2026-10-03", "2026-10-10"], cenario="aquecimento_repassador")
    for n, hora in enumerate(("20:00", "20:12", "20:25"), start=1):
        b.pix(g.pessoa(f"pagador-repasse-{n}"), repassador, 100000, quando(HOJE, hora),
              cenario=f"repasse_rapido_cascata.entrada_{n}", categoria="setup",
              porque="entrada que soma R$ 3.000 em 25 min")
    b.pix(repassador, g.pessoa("quarto-titular"), 270000, quando(HOJE, "20:30"),
          device=g.aparelho("repassador-novo"),
          cenario="repasse_rapido_cascata", categoria="fraud_clear",
          status="rejected", cenario_api="conta_laranja",
          regras=["REPASSE_RAPIDO", "APARELHO_NOVO"],
          porque="90% do que entrou sai 5 min depois para um 4o titular, de aparelho novo")

    destino_coord = g.pessoa("destino-coordenado", aberta_em="2026-10-13")
    for n, hora in enumerate(("21:00", "21:04", "21:08"), start=1):
        ultimo = n == 3
        b.pix(g.pessoa(f"titular-coordenado-{n}"), destino_coord, 40000, quando(HOJE, hora),
              device=g.aparelho("coordenado-compartilhado"),
              cenario="coordenacao_entre_contas" + ("" if ultimo else f".titular_{n}"),
              categoria="fraud_clear" if ultimo else "setup",
              status="two_factor_required" if ultimo else None,
              nivel=["facial", "facial_document"] if ultimo else None,
              cenario_api="coordenacao_entre_contas" if ultimo else None,
              regras=["COORDENACAO_ENTRE_CONTAS", "!APARELHO_COMPARTILHADO"] if ultimo else None,
              porque=("3 titulares no mesmo aparelho em 8 min para conta de 4 dias: COORDENACAO_ENTRE_CONTAS +40, "
                      "piso facial, e APARELHO_COMPARTILHADO fica suprimida" if ultimo
                      else "titular que compartilha o aparelho"))

    fraudador = g.pessoa("fraude-ativa", documento=pix_utils.DOC_FRAUDE_ATIVA)
    salto_1 = g.pessoa("rede-salto-1")
    salto_2 = g.pessoa("rede-salto-2")
    b.pix(fraudador, salto_1, 100000, quando("2026-10-16", "10:00"),
          cenario="rede_suspeita_dois_saltos.salto_1", categoria="setup",
          porque="aresta DOC_FRAUDE_ATIVA para o salto 1")
    b.pix(salto_1, salto_2, 90000, quando("2026-10-16", "11:00"),
          cenario="rede_suspeita_dois_saltos.salto_2", categoria="setup",
          porque="aresta do salto 1 para o salto 2")
    b.pix(persona_m, salto_2, 20000, quando(HOJE, "18:00"),
          cenario="rede_suspeita_dois_saltos", categoria="fraud_clear",
          regras=["REDE_SUSPEITA"],
          porque="o destino esta a 2 saltos de uma fraude ativa: REDE_SUSPEITA +30")

    b.pix(persona_n, fraudador, 2000, quando(HOJE, "12:30"),
          cenario="bloqueio_reputacao_externa", categoria="fraud_clear",
          status="rejected", cenario_api="risco_critico_do_recebedor",
          porque="recebedor com fraude ativa: rejeita qualquer valor, ate R$ 20")

    b.pix(persona_b, fornecedor, 15000000, quando(HOJE, "16:00"),
          cenario="acima_teto_operacional", categoria="fraud_clear",
          status="rejected", cenario_api="restricao_por_limite", regras=["LIMITE_POR_PIX"],
          porque="R$ 150 mil passa do teto operacional por Pix, mesmo para o fornecedor habitual")

    return b


def gerar() -> int:
    payloads, gabarito = monta_bancada().ordenado()

    ids = [p["id"] for p in payloads]
    assert len(ids) == len(set(ids)), "ids repetidos na bancada"
    for p in payloads:
        corpo = p["body"]
        for lado in ("source_account", "destination_account"):
            if lado in corpo:
                documento = corpo[lado]["owner"]["document_number"]
                assert pix_utils.documento_valido(documento), f"documento invalido em {p['id']}: {documento}"
                aberta = datetime.fromisoformat(corpo[lado]["opening_date"])
                assert aberta <= datetime.fromisoformat(corpo["transaction_date"]), f"Pix antes da abertura em {p['id']}"

    ARQUIVO_PAYLOADS.write_text(json.dumps(payloads, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    ARQUIVO_GABARITO.write_text(json.dumps(gabarito, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    contagem = {}
    for item in gabarito:
        contagem[item["category"]] = contagem.get(item["category"], 0) + 1
    print(f"{len(payloads)} requisicoes gravadas em {ARQUIVO_PAYLOADS.name}")
    print(f"{len(gabarito)} respostas esperadas gravadas em {ARQUIVO_GABARITO.name}")
    for categoria in ("warmup", "setup") + NORMAL + FRAUDE:
        print(f"  {categoria:<12} {contagem.get(categoria, 0)}")
    return 0


# ----------------------------------------------------------------------
# Execucao contra a API
# ----------------------------------------------------------------------

def _lista(valor) -> list:
    if valor is None:
        return []
    return valor if isinstance(valor, list) else [valor]


def confere(esperado: dict, resposta: dict) -> list:
    """Devolve a lista de divergencias (vazia quando bate)."""
    falhas = []
    status = _status(resposta)
    if esperado["expected_status"] is not None and status not in _lista(esperado["expected_status"]):
        falhas.append(f"status {status}")
    nivel = _nivel(resposta)
    if esperado["expected_auth_level"] is not None and nivel not in _lista(esperado["expected_auth_level"]):
        falhas.append(f"nivel {nivel}")
    if esperado["expected_scenario"] is not None and _cenario(resposta) != esperado["expected_scenario"]:
        falhas.append(f"cenario {_cenario(resposta)}")
    # Presenca vale mesmo suprimida por correlacao (o sinal foi percebido);
    # o "!CODIGO" so reclama se a regra contou pontos.
    contadas = set(_regras(resposta))
    percebidas = set(_regras(resposta, com_correlatas=True))
    for regra in esperado["expected_rules"]:
        if regra.startswith("!"):
            if regra[1:] in contadas:
                falhas.append(f"{regra[1:]} nao devia acender")
        elif regra not in percebidas:
            falhas.append(f"faltou {regra}")
    return falhas


def _percentil(valores: list, p: int) -> float:
    if not valores:
        return 0.0
    if len(valores) == 1:
        return float(valores[0])
    return statistics.quantiles(valores, n=100, method="inclusive")[p - 1]


def _taxas(linhas: list, categorias: tuple) -> str:
    grupo = [linha for linha in linhas if linha["categoria"] in categorias and linha["status"] is not None]
    if not grupo:
        return "sem transacoes"
    total = len(grupo)
    contas = {
        "approved": sum(1 for linha in grupo if linha["status"] == "approved"),
        "facial": sum(1 for linha in grupo if linha["status"] == "two_factor_required" and linha["nivel"] == "facial"),
        "facial_document": sum(1 for linha in grupo
                               if linha["status"] == "two_factor_required" and linha["nivel"] == "facial_document"),
        "rejected": sum(1 for linha in grupo if linha["status"] == "rejected"),
    }
    partes = [f"{nome} {100 * qtd / total:.1f}% ({qtd})" for nome, qtd in contas.items()]
    return f"{total} transacoes: " + ", ".join(partes)


def _esperado_texto(esperado: dict) -> str:
    if esperado["expected_status"] is None:
        return "regras" if esperado["expected_rules"] else "preparo"
    texto = "/".join(_lista(esperado["expected_status"]))
    if esperado["expected_auth_level"] not in (None, "none"):
        texto += " (" + "/".join(_lista(esperado["expected_auth_level"])) + ")"
    return texto


def rodar(base_url: str, token: str, timeout: float, tabela_completa: bool) -> int:
    try:
        import requests
    except ImportError:
        print("O modo --run precisa do pacote requests:  pip install requests")
        return 2

    if not ARQUIVO_PAYLOADS.exists() or not ARQUIVO_GABARITO.exists():
        print("Arquivos da bancada nao encontrados. Rode antes:  python tools/bancada_rfc_antifraude.py --generate")
        return 2
    payloads = json.loads(ARQUIVO_PAYLOADS.read_text(encoding="utf-8"))
    gabarito = {g["id"]: g for g in json.loads(ARQUIVO_GABARITO.read_text(encoding="utf-8"))}

    sessao = requests.Session()
    sessao.headers.update({"INTERNAL-TOKEN": token, "Content-Type": "application/json"})
    execucao = uuid.uuid4().hex[:8]
    linhas = []

    for requisicao in payloads:
        esperado = gabarito[requisicao["id"]]
        url = base_url + requisicao["path"]
        inicio = time.perf_counter()
        try:
            resposta = sessao.request(requisicao["method"], url, json=requisicao["body"], timeout=timeout,
                                      headers={"X-Request-Id": f"bancada-{execucao}-{requisicao['id']}"})
        except requests.exceptions.ConnectionError:
            print(f"Nao consegui falar com a antifraud-api em {base_url}. Ela esta de pe?")
            return 2
        latencia = (time.perf_counter() - inicio) * 1000

        try:
            corpo = resposta.json()
        except ValueError:
            corpo = {}
        if not isinstance(corpo, dict):
            corpo = {}
        if _latencia(corpo) is not None:
            latencia = _latencia(corpo)

        falhas = []
        if not resposta.ok:
            falhas.append(f"HTTP {resposta.status_code}: {resposta.text[:160]}")
        elif requisicao["method"] == "POST":
            falhas.extend(confere(esperado, corpo))
            consulta = sessao.get(f"{base_url}/pix/transaction/{requisicao['id']}", timeout=timeout)
            try:
                gravado = consulta.json() if consulta.status_code == 200 else None
            except ValueError:
                gravado = None
            if not isinstance(gravado, dict):
                falhas.append(f"GET HTTP {consulta.status_code}")
            elif _status(gravado) != _status(corpo):
                falhas.append(f"GET devolveu {_status(gravado)}")
            if _status(corpo) == "two_factor_required" and esperado["category"] in CONFIRMA_DESAFIO:
                confirmacao = sessao.patch(f"{base_url}/pix/transaction/{requisicao['id']}", timeout=timeout, json={
                    "challenge_result": "approved_by_client", "event_date": requisicao["body"]["transaction_date"]})
                if not confirmacao.ok:
                    falhas.append(f"PATCH HTTP {confirmacao.status_code}")

        linhas.append({
            "cenario": esperado["scenario_name"],
            "categoria": esperado["category"],
            "esperado": _esperado_texto(esperado),
            "status": _status(corpo) if requisicao["method"] == "POST" else None,
            "nivel": _nivel(corpo) if requisicao["method"] == "POST" else None,
            "regras": _regras(corpo),
            "latencia": latencia,
            "falhas": falhas,
        })

    imprime_relatorio(linhas, tabela_completa)
    return 1 if any(linha["falhas"] for linha in linhas) else 0


def imprime_relatorio(linhas: list, tabela_completa: bool):
    print("| cenário | esperado | obtido | nível | regras | latência |")
    print("|---|---|---|---|---|---|")
    for linha in linhas:
        if linha["categoria"] == "warmup" and not tabela_completa and not linha["falhas"]:
            continue
        marca = "[falha] " if linha["falhas"] else "[ok] "
        obtido = linha["status"] or "registrado"
        if linha["falhas"]:
            obtido += " (" + "; ".join(linha["falhas"]) + ")"
        print(f"| {marca}{linha['cenario']} | {linha['esperado']} | {obtido} | {linha['nivel'] or ''} "
              f"| {', '.join(linha['regras'])} | {linha['latencia']:.0f} ms |")

    aquecimento = [linha for linha in linhas if linha["categoria"] == "warmup"]
    falhas_aquecimento = sum(1 for linha in aquecimento if linha["falhas"])
    print()
    print(f"Aquecimento: {len(aquecimento) - falhas_aquecimento} de {len(aquecimento)} como esperado"
          + ("" if tabela_completa else " (so as divergencias aparecem na tabela; --tabela-completa mostra todas)"))
    print(f"Trafego normal:     {_taxas(linhas, NORMAL)}")
    print(f"Trafego fraudulento: {_taxas(linhas, FRAUDE)}")

    latencias = [linha["latencia"] for linha in linhas]
    print(f"latency_ms: p50 {_percentil(latencias, 50):.1f}, p95 {_percentil(latencias, 95):.1f}")

    total_falhas = sum(1 for linha in linhas if linha["falhas"])
    print(f"{len(linhas) - total_falhas} de {len(linhas)} requisicoes bateram com o gabarito")


def main() -> int:
    parser = argparse.ArgumentParser(description="Massa sintetica e benchmark da antifraud-api")
    modo = parser.add_mutually_exclusive_group(required=True)
    modo.add_argument("--generate", action="store_true", help="grava payloads e gabarito em tools/")
    modo.add_argument("--run", action="store_true", help="dispara os payloads e compara com o gabarito")
    host = os.environ.get("SERVER_LOCALHOST", "localhost").strip()
    porta = os.environ.get("ANTIFRAUD_API_PORT", "3020").strip()
    parser.add_argument("--url", default=f"http://{host}:{porta}", help="endereco da antifraud-api")
    parser.add_argument("--timeout", type=float, default=10.0, help="segundos por requisicao")
    parser.add_argument("--tabela-completa", action="store_true", help="mostra tambem o aquecimento que bateu")
    args = parser.parse_args()

    if args.generate:
        return gerar()
    token = os.environ.get("INTERNAL_TOKEN", "default_token")
    return rodar(args.url.rstrip("/"), token, args.timeout, args.tabela_completa)


if __name__ == "__main__":
    sys.exit(main())
