"""O ticket do recebedor: o valor contra o que se costuma pagar a ele.

Com regua (o que outros clientes da casa pagaram a ele em 90 dias), vale o
desvio do ticket dele. Sem regua, o teto da atividade, pelo CNAE do mock de
cadastro. A regra so dificulta: reprovar, so com outro eixo concordando.
"""
from datetime import timedelta

from tests.utils.pix import (
    RECEBEDOR_CONCESSIONARIA, RECEBEDOR_DOCERIA, Pagador, Recebedor, analisa, disparou, nova_base, paga, pix, pontos,
    regra,
)

# Doze clientes diferentes, um por dia: tickets de R$ 30 a R$ 80, mediana R$ 50.
TICKETS = [3000, 4000, 5000, 6000, 8000, 3500, 4500, 5500, 7000, 6500, 5000, 4000]


def _clientes_pagam(loja, hoje):
    for indice, valor in enumerate(TICKETS):
        analisa(pix(Pagador(), loja, valor, (hoje - timedelta(days=len(TICKETS) - indice)).isoformat()))


def test_valor_muito_acima_do_ticket_do_recebedor_soma_40_e_pede_2fa():
    hoje, loja = nova_base(), Recebedor(pj=True)
    _clientes_pagam(loja, hoje)

    corpo = analisa(pix(Pagador(), loja, 400000, hoje.isoformat()))

    assert pontos(corpo, "TICKET_DO_RECEBEDOR") == 40
    assert regra(corpo, "TICKET_DO_RECEBEDOR")["reference"] == "recebedor"
    assert corpo["status"] == "two_factor_required"


def test_valor_dentro_do_ticket_do_recebedor_nao_dispara():
    hoje, loja = nova_base(), Recebedor(pj=True)
    _clientes_pagam(loja, hoje)

    corpo = analisa(pix(Pagador(), loja, 6000, hoje.isoformat()))

    assert not disparou(corpo, "TICKET_DO_RECEBEDOR")
    assert corpo["status"] == "approved"


def test_quem_ja_pagou_esse_valor_ao_recebedor_nao_dispara():
    # O cliente da encomenda grande: os outros pagam R$ 50, ele ja pagou
    # R$ 4.000 ontem e confirmou na verificacao.
    hoje, loja, cliente = nova_base(), Recebedor(pj=True), Pagador()
    _clientes_pagam(loja, hoje)
    paga(pix(cliente, loja, 400000, (hoje - timedelta(hours=20)).isoformat()))

    corpo = analisa(pix(cliente, loja, 400000, hoje.isoformat()))

    assert not disparou(corpo, "TICKET_DO_RECEBEDOR")


def test_doceria_sem_historico_acima_do_ticket_da_atividade_soma_40():
    # Ninguem da casa pagou a doceria ainda: vale o teto da atividade pelo
    # CNAE (confeitaria, R$ 2.000). R$ 15 mil passa de 5 vezes o teto.
    corpo = analisa(pix(Pagador(), Recebedor(documento=RECEBEDOR_DOCERIA), 1500000, nova_base().isoformat()))

    resultado = regra(corpo, "TICKET_DO_RECEBEDOR")
    assert resultado["effective_points"] == 40
    assert resultado["reference"] == "cnae"
    assert resultado["is_mock"] is True
    assert corpo["status"] == "two_factor_required"


def test_doceria_recebendo_20_mil_reprova_pela_convergencia_com_o_valor():
    # O ticket sozinho so dificulta. Aqui o valor tambem estranha do lado de
    # quem paga (LIMITE_POR_PIX, eixo movimentacao): dois eixos, e reprova.
    corpo = analisa(pix(Pagador(), Recebedor(documento=RECEBEDOR_DOCERIA), 2000000, nova_base().isoformat()))

    assert pontos(corpo, "TICKET_DO_RECEBEDOR") == 40
    assert pontos(corpo, "LIMITE_POR_PIX") == 40
    assert corpo["status"] == "rejected"


def test_concessionaria_recebe_valor_alto_sem_pontos_do_ticket():
    corpo = analisa(pix(Pagador(), Recebedor(documento=RECEBEDOR_CONCESSIONARIA), 1500000, nova_base().isoformat()))

    assert not disparou(corpo, "TICKET_DO_RECEBEDOR")
