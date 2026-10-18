"""O DICT de mentira (Mockserver): a marcacao de fraude que outro banco fez.

O Mockserver faz o papel do DICT, como faz o dos biros da onboarding-api. Cada
teste programa a resposta presa ao documento do proprio recebedor, que e novo,
e nunca apaga o que outro teste programou. O connector guarda cada resposta 60 s
em cache e abre o circuito depois de 3 falhas seguidas: por isso nenhum teste
derruba mais de uma conexao, e nenhum repete documento.

Pulam quando o Mockserver nao esta de pe: o CI curto (antifraud.yml) sobe so o
banco e a antifraud-api, e ali a consulta ao DICT falha aberta.
"""
import re
from datetime import datetime, timedelta

import pytest
import requests

from tests.utils.mockserver import Mockserver, cabecalho, endereco_do_mockserver
from tests.utils.pix import (
    TOKEN, AntifraudApi, Pagador, Recebedor, analisa, nega, nova_base, pix, regra,
)
from tests.utils.run_at_the_same_time import run_at_the_same_time

ROTA_DO_DICT = "/dict/v1/informacoes-seguranca"
SEM_MARCACAO = {"statistics": {}}
# Os contadores no formato do destination_statistics: uma marcacao de conta
# laranja nos ultimos 90 dias, por um denunciante.
LARANJA_CONFIRMADA = {
    "mule_accounts": {"d90": 1, "m12": 1, "m60": 1},
    "scammer_accounts": {"d90": 0, "m12": 0, "m60": 0},
    "application_frauds": {"d90": 0, "m12": 0, "m60": 0},
    "distinct_fraud_reporters": {"d90": 1, "m12": 1, "m60": 1},
    "open_reports": 0,
}
# So uma denuncia aberta, que ainda nao foi analisada: alerta, sem bloqueio.
DENUNCIA_ABERTA = {**LARANJA_CONFIRMADA, "mule_accounts": {"d90": 0, "m12": 0, "m60": 0},
                   "distinct_fraud_reporters": {"d90": 0, "m12": 0, "m60": 0}, "open_reports": 1}
# O tempo limite do connector e 0,3 s: o atraso fica abaixo dele.
ATRASO_MS = 250


def _mockserver_de_pe() -> bool:
    try:
        return requests.put(f"{endereco_do_mockserver()}/mockserver/status", timeout=2).status_code == 200
    except requests.exceptions.RequestException:
        return False


pytestmark = pytest.mark.skipif(not _mockserver_de_pe(), reason="Mockserver fora do ar: o DICT nao esta de pe")


def _digitos(documento: str) -> str:
    return re.sub(r"\D", "", documento)


def _dict_responde(documento: str, corpo: dict, atraso_ms: int = None) -> None:
    resposta = {"statusCode": 200, "headers": {"Content-Type": ["application/json"]},
                "body": {"type": "JSON", "json": corpo}}
    if atraso_ms is not None:
        resposta["delay"] = {"timeUnit": "MILLISECONDS", "value": atraso_ms}
    Mockserver.registra({"httpRequest": Mockserver.pedido_post(ROTA_DO_DICT, {"document": _digitos(documento)}),
                         "httpResponse": resposta, "priority": 10})


def _pedidos_ao_dict(documento: str) -> list:
    return Mockserver.pedidos({"document": _digitos(documento)}, ROTA_DO_DICT)


def _chegadas_ao_dict(documento: str) -> list:
    """O instante em que o Mockserver recebeu cada pedido sobre o documento, pelo log dele."""
    filtro = {"path": ROTA_DO_DICT, "body": {"type": "JSON", "json": {"document": _digitos(documento)},
                                             "matchType": "ONLY_MATCHING_FIELDS"}}
    log = Mockserver.envia("/mockserver/retrieve?type=LOGS", filtro).text
    return [datetime.strptime(linha, "%Y-%m-%d %H:%M:%S.%f")
            for linha in re.findall(r"^(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}\.\d{3}) - received request:", log, re.M)]


def test_recebedor_marcado_no_dict_e_recusado():
    destino = Recebedor()
    _dict_responde(destino.documento, {"statistics": LARANJA_CONFIRMADA, "evidence_id": "dict-teste-laranja"})

    corpo = analisa(pix(Pagador(), destino, 5000, nova_base().isoformat()))

    assert corpo["status"] == "rejected"
    assert regra(corpo, "REPUTACAO_EXTERNA")["hard_block"] is True
    assert regra(corpo, "REPUTACAO_EXTERNA")["evidence_ids"] == ["dict-teste-laranja"]
    assert corpo["metadata"]["reputation"]["provider"] == "dict"
    assert corpo["metadata"]["reputation"]["signal"] == "active_fraud_marker"


def test_o_documento_vai_so_no_corpo_do_pedido_ao_dict():
    destino = Recebedor()

    analisa(pix(Pagador(), destino, 5000, nova_base().isoformat()))

    pedidos = _pedidos_ao_dict(destino.documento)
    assert len(pedidos) == 1
    assert pedidos[0]["path"] == ROTA_DO_DICT
    assert not pedidos[0].get("queryStringParameters")
    assert cabecalho(pedidos[0], "INTERNAL-TOKEN") == TOKEN


def test_dict_fora_do_ar_o_pix_e_decidido_sem_ele():
    destino = Recebedor()
    Mockserver.derruba_a_conexao(ROTA_DO_DICT, {"document": _digitos(destino.documento)}, vezes=1)

    resposta = AntifraudApi.post(pix(Pagador(), destino, 5000, nova_base().isoformat()))

    assert resposta.status_code == 201, resposta.text
    assert resposta.json()["status"] == "approved"
    assert resposta.json()["metadata"]["reputation"]["signal"] == "not_found"
    assert len(_pedidos_ao_dict(destino.documento)) == 1


def test_nao_fui_eu_contra_quem_o_dict_ja_marcou_confirma_a_fraude():
    # A denuncia aberta no DICT e a segunda fonte independente: com o "nao fui
    # eu" do titular, o documento vira fraude confirmada na lista interna.
    hoje, destino = nova_base(), Recebedor()
    _dict_responde(destino.documento, {"statistics": DENUNCIA_ABERTA})
    nega(Pagador(), destino, 50000, hoje)

    corpo = analisa(pix(Pagador(), destino, 5000, (hoje + timedelta(hours=1)).isoformat()))

    assert corpo["status"] == "rejected"
    assert regra(corpo, "REPUTACAO_INTERNA")["creator"] == "confirmed"


def test_a_consulta_ao_dict_nao_segura_a_trava_do_pagador():
    # Quatro Pix do mesmo pagador, ao mesmo tempo, para quatro recebedores
    # novos, com o DICT levando 250 ms para responder cada um. As travas do
    # pagador enfileiram os quatro. Se a consulta acontecesse com a trava na
    # mao, cada pedido ao DICT so sairia depois de o anterior terminar, e os
    # quatro chegariam ao Mockserver espalhados por pelo menos 3 x 250 ms.
    # Fora da trava, os quatro saem juntos.
    hoje, pagador = nova_base(), Pagador()
    # A conta do pagador nasce antes: o INSERT de uma conta nova tambem
    # enfileira quem pede a mesma conta, e isso nao e o que este teste mede.
    analisa(pix(pagador, Recebedor(), 5000, hoje.isoformat()))
    destinos = [Recebedor() for _ in range(4)]
    for destino in destinos:
        _dict_responde(destino.documento, SEM_MARCACAO, atraso_ms=ATRASO_MS)
    payloads = [pix(pagador, destino, 5000, (hoje + timedelta(minutes=1, seconds=indice)).isoformat())
                for indice, destino in enumerate(destinos)]

    respostas = run_at_the_same_time(AntifraudApi.post, payloads)

    assert [resposta.status_code for resposta in respostas] == [201] * 4
    chegadas = sorted(instante for destino in destinos for instante in _chegadas_ao_dict(destino.documento))
    assert len(chegadas) == 4
    espalhamento_ms = (chegadas[-1] - chegadas[0]).total_seconds() * 1000
    assert espalhamento_ms < ATRASO_MS, f"os pedidos ao DICT chegaram espalhados por {espalhamento_ms:.0f} ms"
