"""Reputacao: o mock externo (no formato do destination_statistics da QI)
e a lista interna, que o proprio motor nunca alimenta."""
from datetime import timedelta

from tests.utils.pix import (
    APARELHO_NA_WATCHLIST, RECEBEDOR_ALERTA, RECEBEDOR_ALERTA_VENCIDO, RECEBEDOR_MARCACAO_CRITICA,
    RECEBEDOR_NA_WATCHLIST, RECEBEDOR_VITIMA, AntifraudApi, Pagador, Recebedor, analisa, disparou, nova_base, pix,
    pontos, regra,
)


def test_marcacao_critica_rejeita_mesmo_com_valor_baixo():
    corpo = analisa(pix(Pagador(), Recebedor(documento=RECEBEDOR_MARCACAO_CRITICA), 5000, nova_base().isoformat()))

    assert corpo["status"] == "rejected"
    assert corpo["metadata"]["scenario"] == "risco_critico_do_recebedor"
    assert corpo["metadata"]["reputation"]["is_mock"] is True
    assert corpo["metadata"]["reputation"]["signal"] == "active_fraud_marker"


def test_alerta_soma_40():
    corpo = analisa(pix(Pagador(), Recebedor(documento=RECEBEDOR_ALERTA), 5000, nova_base().isoformat()))

    assert pontos(corpo, "REPUTACAO_EXTERNA") == 40
    assert corpo["metadata"]["reputation"]["signal"] == "risk_alert"


def test_alerta_vencido_nao_conta():
    corpo = analisa(pix(Pagador(), Recebedor(documento=RECEBEDOR_ALERTA_VENCIDO), 5000, nova_base().isoformat()))

    assert not disparou(corpo, "REPUTACAO_EXTERNA")
    assert corpo["metadata"]["reputation"]["signal"] == "expired"


def test_vitima_nao_e_tratada_como_fraudador():
    corpo = analisa(pix(Pagador(), Recebedor(documento=RECEBEDOR_VITIMA), 5000, nova_base().isoformat()))

    assert not disparou(corpo, "REPUTACAO_EXTERNA")
    assert corpo["metadata"]["reputation"]["entity_role"] == "victim"


def test_documento_sem_registro_no_mock_e_not_found():
    corpo = analisa(pix(Pagador(), Recebedor(), 5000, nova_base().isoformat()))

    assert corpo["metadata"]["reputation"]["signal"] == "not_found"


def test_documento_na_watchlist_soma_40():
    corpo = analisa(pix(Pagador(), Recebedor(documento=RECEBEDOR_NA_WATCHLIST), 5000, nova_base().isoformat()))

    assert pontos(corpo, "REPUTACAO_INTERNA") == 40


def test_aparelho_na_watchlist_soma_40():
    corpo = analisa(pix(Pagador(), Recebedor(), 5000, nova_base().isoformat(), aparelho=APARELHO_NA_WATCHLIST))

    assert pontos(corpo, "REPUTACAO_INTERNA") == 40


def test_rejeicao_do_motor_nao_alimenta_a_watchlist():
    hoje, destino = nova_base(), Recebedor()
    assert analisa(pix(Pagador(), destino, 15000000, hoje.isoformat()))["status"] == "rejected"

    corpo = analisa(pix(Pagador(), destino, 5000, (hoje + timedelta(hours=1)).isoformat()))

    assert not disparou(corpo, "REPUTACAO_INTERNA")


def test_titular_que_nega_o_desafio_marca_o_destino():
    hoje, destino = nova_base(), Recebedor()
    payload = pix(Pagador(), destino, 2500000, hoje.isoformat())
    assert analisa(payload)["status"] == "two_factor_required"
    AntifraudApi.patch(payload["id"], {"challenge_result": "reproved_by_client",
                                       "event_date": (hoje + timedelta(minutes=2)).isoformat()})

    corpo = analisa(pix(Pagador(), destino, 5000, (hoje + timedelta(hours=1)).isoformat()))

    assert pontos(corpo, "REPUTACAO_INTERNA") == 40
    assert regra(corpo, "REPUTACAO_INTERNA")["creator"] == "client"


def test_negativa_do_titular_conta_como_restritiva_na_sondagem():
    hoje, pagador = nova_base(), Pagador()
    payload = pix(pagador, Recebedor(), 2500000, hoje.isoformat())
    analisa(payload)
    AntifraudApi.patch(payload["id"], {"challenge_result": "reproved_by_client",
                                       "event_date": (hoje + timedelta(minutes=1)).isoformat()})

    corpo = analisa(pix(pagador, Recebedor(), 1900000, (hoje + timedelta(minutes=3)).isoformat()))

    assert disparou(corpo, "SONDAGEM_DE_LIMITE")
