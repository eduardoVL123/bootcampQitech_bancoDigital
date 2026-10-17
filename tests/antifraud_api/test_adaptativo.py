"""A regua de cada cliente: picos diarios dos 30 dias anteriores, mediana e
MAD. Com regua, o corte e o do cliente; sem regua, vale a reserva firme.

Os historicos aqui sao maiores (7 dias ou mais com movimento), porque a
regua so existe com 7 dias ativos e 20 eventos."""
from datetime import timedelta

from tests.utils.pix import (
    Pagador, Recebedor, analisa, disparou, nova_base, paga, pix, regra,
)

CASA = "99999999"


def _rajadas(pagador, hoje, dias, por_dia, intervalo, valor=5000, a_cada=1):
    """Uma rajada por dia, em `dias` dias antes de hoje, a cada `a_cada` dias."""
    for dia in range(dias, 0, -1):
        if dia % a_cada:
            continue
        inicio = (hoje - timedelta(days=dia)).replace(hour=11)
        for indice in range(por_dia):
            analisa(pix(pagador, Recebedor(), valor, (inicio + intervalo * indice).isoformat()))


def _hoje():
    return nova_base().replace(hour=15, minute=0)


def test_quem_sempre_faz_rajadas_de_6_nao_dispara_com_6():
    pagador, hoje = Pagador(), _hoje()
    _rajadas(pagador, hoje, 7, 6, timedelta(seconds=40))

    corpos = [analisa(pix(pagador, Recebedor(), 5000, (hoje + timedelta(seconds=40 * i)).isoformat()))
              for i in range(6)]

    assert regra(corpos[-1], "VELOCITY") is None or not disparou(corpos[-1], "VELOCITY")


def test_rajada_muito_acima_do_padrao_pede_facial_document():
    pagador, hoje = Pagador(), _hoje()
    _rajadas(pagador, hoje, 7, 6, timedelta(seconds=40))

    corpos = [analisa(pix(pagador, Recebedor(), 5000, (hoje + timedelta(seconds=10 * i)).isoformat()))
              for i in range(18)]

    velocity = regra(corpos[-1], "VELOCITY")
    assert velocity["raw_points"] == 60
    assert velocity["reference"] == "adaptive"
    assert corpos[-1]["metadata"]["authentication"]["level"] == "facial_document"


def test_mediana_2_e_mad_0_da_limiares_4_e_6():
    pagador, hoje = Pagador(), _hoje()
    _rajadas(pagador, hoje, 10, 2, timedelta(minutes=1))

    corpos = [analisa(pix(pagador, Recebedor(), 5000, (hoje + timedelta(seconds=30 * i)).isoformat()))
              for i in range(4)]

    velocity = regra(corpos[-1], "VELOCITY")
    assert velocity["raw_points"] == 40
    assert velocity["windows"]["5"]["moderate"] == 4
    assert velocity["windows"]["5"]["high"] == 6


def test_dias_sem_atividade_nao_entram_como_zero():
    # 7 dias com rajada de 6, espalhados em 21 dias. Se os 14 dias parados
    # contassem como zero, a mediana seria 0 e 6 tentativas disparariam.
    pagador, hoje = Pagador(), _hoje()
    _rajadas(pagador, hoje, 21, 6, timedelta(seconds=40), a_cada=3)

    corpos = [analisa(pix(pagador, Recebedor(), 5000, (hoje + timedelta(seconds=40 * i)).isoformat()))
              for i in range(6)]

    assert not disparou(corpos[-1], "VELOCITY")


def test_regua_congelada_no_inicio_do_dia():
    pagador, hoje = Pagador(), _hoje()
    _rajadas(pagador, hoje, 7, 6, timedelta(seconds=40))
    manha = [analisa(pix(pagador, Recebedor(), 5000, (hoje.replace(hour=9) + timedelta(seconds=5 * i)).isoformat()))
             for i in range(20)]

    tarde = [analisa(pix(pagador, Recebedor(), 5000, (hoje + timedelta(seconds=40 * i)).isoformat()))
             for i in range(6)]

    assert regra(manha[-1], "VELOCITY")["windows"]["5"]["moderate"] == 12
    assert not disparou(tarde[-1], "VELOCITY")


def test_montante_com_referencia_exige_o_corte_e_o_desvio():
    pagador, hoje = Pagador(), _hoje()
    for dia in range(7, 0, -1):
        inicio = (hoje - timedelta(days=dia)).replace(hour=8)
        for indice in range(12):
            paga(pix(pagador, Recebedor(), 490000, (inicio + timedelta(hours=1, minutes=indice)).isoformat()))
    for indice in range(10):
        paga(pix(pagador, Recebedor(), 490000, (hoje.replace(hour=8) + timedelta(hours=indice)).isoformat()))

    corpo = analisa(pix(pagador, Recebedor(), 490000, (hoje.replace(hour=8) + timedelta(hours=10)).isoformat()))

    assert regra(corpo, "MONTANTE_24H") is None or not disparou(corpo, "MONTANTE_24H")


def test_loja_que_sempre_recebe_de_10_clientes_por_hora_nao_e_laranja():
    loja, hoje = Recebedor(pj=True), _hoje()
    for dia in range(7, 0, -1):
        inicio = (hoje - timedelta(days=dia)).replace(hour=12)
        for indice in range(10):
            analisa(pix(Pagador(), loja, 5000, (inicio + timedelta(minutes=3 * indice)).isoformat()))

    corpos = [analisa(pix(Pagador(), loja, 5000, (hoje + timedelta(minutes=3 * i)).isoformat())) for i in range(10)]

    assert not disparou(corpos[-1], "CONTA_LARANJA")
    assert regra(corpos[-1], "CONTA_LARANJA") is None or regra(corpos[-1], "CONTA_LARANJA")["reference"] == "adaptive"


def test_repasse_para_fornecedor_de_sempre_nao_soma():
    hoje = _hoje()
    conta, fornecedor = Recebedor(participante=CASA), Recebedor(pj=True)
    pagador = conta.como_pagador()
    dias_do_fornecedor = {16, 12, 8, 4, 1}
    for dia in range(16, 0, -1):
        inicio = (hoje - timedelta(days=dia)).replace(hour=10)
        destino = fornecedor if dia in dias_do_fornecedor else Recebedor(pj=True)
        paga(pix(pagador, destino, 350000, inicio.isoformat()))
        paga(pix(pagador, Recebedor(pj=True), 350000, (inicio + timedelta(hours=3)).isoformat()))
    for indice in range(4):
        analisa(pix(Pagador(), conta, 100000, (hoje + timedelta(minutes=indice)).isoformat()))

    corpo = analisa(pix(pagador, fornecedor, 350000, (hoje + timedelta(minutes=10)).isoformat()))

    assert not disparou(corpo, "REPASSE_RAPIDO")
