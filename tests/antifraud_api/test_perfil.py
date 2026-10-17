"""O perfil do pagador: a mediana e o MAD dos aprovados, comparados com a
referencia certa (o par pagador -> recebedor antes das saidas gerais).

O historico e montado nos dias anteriores: a regua e congelada no inicio
do dia, entao Pix de hoje nao entram nela."""
from datetime import timedelta

from tests.utils.pix import (
    Pagador, Recebedor, analisa, disparou, historico, nova_base, pix, pontos, regra,
)


def _hoje():
    return nova_base().replace(hour=14, minute=0)


def _pequenos(pagador, hoje, valores=None):
    valores = valores or [3000, 3500, 4000, 4500, 5000, 5500, 6000, 6500, 7000, 8000]
    historico(pagador, valores, hoje - timedelta(days=6), timedelta(hours=12), recebedores_novos=True)


def test_valor_muito_acima_da_mediana_soma_50():
    pagador, hoje = Pagador(), _hoje()
    _pequenos(pagador, hoje)

    corpo = analisa(pix(pagador, Recebedor(), 300000, hoje.isoformat()))

    assert pontos(corpo, "PERFIL") == 50
    assert regra(corpo, "PERFIL")["reference"] == "payer"


def test_fornecedor_de_40_mil_recebendo_42_mil_nao_dispara():
    pagador, fornecedor, hoje = Pagador(), Recebedor(pj=True), _hoje()
    historico(pagador, [4000000] * 5, hoje - timedelta(days=20), timedelta(days=4), recebedor=fornecedor)

    corpo = analisa(pix(pagador, fornecedor, 4200000, hoje.isoformat()))

    assert not disparou(corpo, "PERFIL")
    assert not disparou(corpo, "LIMITE_POR_PIX")
    assert corpo["status"] == "approved"


def test_referencia_do_par_vence_a_geral():
    pagador, senhorio, hoje = Pagador(), Recebedor(), _hoje()
    historico(pagador, [250000] * 5, hoje - timedelta(days=20), timedelta(days=4), recebedor=senhorio)
    _pequenos(pagador, hoje)

    para_o_senhorio = analisa(pix(pagador, senhorio, 260000, hoje.isoformat()))
    para_outro = analisa(pix(pagador, Recebedor(), 260000, (hoje + timedelta(minutes=30)).isoformat()))

    assert not disparou(para_o_senhorio, "PERFIL")
    assert disparou(para_outro, "PERFIL")


def test_contato_de_150_recebendo_35_mil_dispara_pelo_par():
    pagador, contato, hoje = Pagador(), Recebedor(), _hoje()
    historico(pagador, [15000] * 5, hoje - timedelta(days=20), timedelta(days=4), recebedor=contato)

    corpo = analisa(pix(pagador, contato, 3500000, hoje.isoformat()))

    assert regra(corpo, "PERFIL")["raw_points"] == 50
    assert regra(corpo, "PERFIL")["reference"] == "pair"


def test_z_alto_em_valor_abaixo_de_2_vezes_a_mediana_nao_dispara():
    pagador, hoje = Pagador(), _hoje()
    _pequenos(pagador, hoje, [99800, 99900, 100000, 100000, 100100, 100200, 100000, 99900, 100100, 100000])

    corpo = analisa(pix(pagador, Recebedor(), 160000, hoje.isoformat()))

    assert not disparou(corpo, "PERFIL")


def test_mad_zero_usa_o_multiplo_da_mediana():
    hoje = _hoje()
    abaixo, acima = Pagador(), Pagador()
    _pequenos(abaixo, hoje, [20000] * 10)
    _pequenos(acima, hoje, [20000] * 10)

    nao = analisa(pix(abaixo, Recebedor(), 50000, hoje.isoformat()))
    sim = analisa(pix(acima, Recebedor(), 70000, hoje.isoformat()))

    assert not disparou(nao, "PERFIL")
    assert pontos(sim, "PERFIL") == 30


def test_diferenca_menor_que_500_nao_dispara():
    pagador, hoje = Pagador(), _hoje()
    _pequenos(pagador, hoje, [10000] * 10)

    corpo = analisa(pix(pagador, Recebedor(), 45000, hoje.isoformat()))

    assert not disparou(corpo, "PERFIL")


def test_sem_referencia_e_valor_alto_pede_facial():
    corpo = analisa(pix(Pagador(), Recebedor(), 600000, _hoje().isoformat()))

    assert pontos(corpo, "PERFIL_SEM_HISTORICO") == 20
    assert corpo["metadata"]["authentication"]["level"] == "facial"


def test_sem_historico_e_valor_baixo_aprova_com_perfil_nao_avaliavel():
    corpo = analisa(pix(Pagador(), Recebedor(), 10000, _hoje().isoformat()))

    assert regra(corpo, "PERFIL")["evaluation"] == "not_evaluable"
    assert corpo["status"] == "approved"


def test_limite_e_perfil_contam_uma_vez():
    pagador, hoje = Pagador(), _hoje()
    _pequenos(pagador, hoje)

    corpo = analisa(pix(pagador, Recebedor(), 2500000, hoje.isoformat()))

    assert regra(corpo, "LIMITE_POR_PIX")["correlated"] is True
    assert pontos(corpo, "LIMITE_POR_PIX") == 0
    assert pontos(corpo, "PERFIL") == 50


def test_dia_atipico_soma_30():
    pagador, hoje = Pagador(), _hoje()
    historico(pagador, [15000] * 14, hoje - timedelta(days=7, hours=4), timedelta(hours=12), recebedores_novos=True)

    corpo = analisa(pix(pagador, Recebedor(), 140000, hoje.isoformat()))

    assert pontos(corpo, "MONTANTE_DIARIO_ATIPICO") == 30


def test_menos_de_7_dias_de_historia_deixa_o_dia_nao_avaliavel():
    pagador, hoje = Pagador(), _hoje()
    historico(pagador, [15000] * 6, hoje - timedelta(days=3), timedelta(hours=12), recebedores_novos=True)

    corpo = analisa(pix(pagador, Recebedor(), 140000, hoje.isoformat()))

    assert regra(corpo, "MONTANTE_DIARIO_ATIPICO")["evaluation"] == "not_evaluable"
