"""A matematica da projecao do repasse (controllers/engine/flow.py), sem banco.

As regressoes de comportamento estao em tests/antifraud_api/test_rede.py,
pela API. Aqui ficam a ordem dos eventos, o consumo dos lotes e a fronteira
do corte, que la custariam um cenario inteiro cada.
"""
from datetime import datetime, timedelta, timezone
from fractions import Fraction

from controllers.engine.flow import INCOMING, OUTGOING, project

CONTA, OUTRA_CONTA, TITULAR = 1, 2, "dono"
OITENTA = Fraction("0.8")
T0 = datetime(2026, 10, 1, 12, tzinfo=timezone.utc)


def _eventos(*movimentos):
    """(lado, valor, documento[, conta da outra ponta]) em ordem, um por minuto."""
    eventos = []
    for indice, movimento in enumerate(movimentos):
        lado, valor, documento, *conta = movimento
        eventos.append((T0 + timedelta(minutes=indice), indice + 1, lado, valor, documento,
                        conta[0] if conta else 100 + indice))
    return eventos


def _entra(valor, documento, *conta):
    return (INCOMING, valor, documento, *conta)


def _sai(valor, documento, *conta):
    return (OUTGOING, valor, documento, *conta)


def _projeta(movimentos, valor, documento="novo", conta=999):
    return project(_eventos(*movimentos), CONTA, TITULAR, (valor, documento, conta))


VITIMAS = [_entra(100000, "v1"), _entra(100000, "v2"), _entra(100000, "v3")]


def test_saida_unica_escoa_o_pool():
    fluxo = _projeta(VITIMAS, 270000)

    assert fluxo.describe() == {"incoming": 300000, "refunded": 0, "outflow": 270000, "base": 300000,
                                "current_refund": 0, "current_outflow": 270000, "qualified_payers": 3}
    assert fluxo.identifies(3, OITENTA)


def test_saidas_fatiadas_acumulam():
    segunda = _projeta(VITIMAS + [_sai(100000, "x")], 100000)
    terceira = _projeta(VITIMAS + [_sai(100000, "x"), _sai(100000, "y")], 100000)

    assert segunda.outflow == 200000 and not segunda.identifies(3, OITENTA)
    assert terceira.outflow == 300000 and terceira.identifies(3, OITENTA)


def test_devolucao_vale_so_ate_o_credito_do_titular():
    fluxo = _projeta(VITIMAS + [_entra(1, "destino")], 270000, "destino")

    assert (fluxo.current_refund, fluxo.current_outflow) == (1, 269999)
    assert (fluxo.base, fluxo.qualified_payers) == (300000, 3)
    assert fluxo.identifies(3, OITENTA)


def test_quatro_entradas_e_3500_para_um_dos_pagadores():
    fluxo = _projeta(VITIMAS + [_entra(100000, "v4")], 350000, "v1")

    assert (fluxo.refunded, fluxo.outflow, fluxo.base, fluxo.qualified_payers) == (100000, 250000, 300000, 3)


def test_o_mesmo_credito_nao_justifica_duas_devolucoes():
    fluxo = _projeta(VITIMAS + [_entra(10000, "amigo"), _sai(10000, "amigo")], 10000, "amigo")

    assert (fluxo.current_refund, fluxo.current_outflow) == (0, 10000)
    assert fluxo.refunded == 10000


def test_devolucao_integral_nao_dispara_e_esgota_o_credito():
    devolve = [_sai(100000, "v1"), _sai(100000, "v2")]
    ultima = _projeta(VITIMAS + devolve, 100000, "v3")
    depois = _projeta(VITIMAS + devolve + [_sai(100000, "v3")], 100000)

    assert (ultima.current_refund, ultima.current_outflow) == (100000, 0)
    assert not ultima.identifies(1, OITENTA)
    assert depois.qualified_payers == 0 and depois.current_outflow == 0


def test_devolucao_integral_nao_herda_o_alerta_das_saidas_anteriores():
    fluxo = _projeta([_entra(100000, "v1"), _entra(100000, "v2"), _entra(100000, "v3"), _entra(100000, "v4"),
                      _sai(300000, "x")], 100000, "v4")

    assert fluxo.reaches(OITENTA)
    assert fluxo.current_outflow == 0
    assert not fluxo.identifies(3, OITENTA)


def test_saida_anterior_nao_consome_entrada_futura():
    fluxo = _projeta([_sai(270000, "x")] + VITIMAS, 50000)

    assert fluxo.outflow == 50000


def test_lote_consumido_nao_volta():
    fluxo = _projeta(VITIMAS + [_sai(200000, "x"), _entra(100000, "v4"), _entra(100000, "v5"),
                                _entra(100000, "v6")], 280000, "v1")

    assert fluxo.current_refund == 0
    assert (fluxo.outflow, fluxo.base, fluxo.qualified_payers) == (480000, 600000, 6)
    assert fluxo.identifies(3, OITENTA)


def test_saida_sem_lote_disponivel_nao_conta():
    fluxo = _projeta(VITIMAS + [_sai(500000, "x")], 100000)

    assert fluxo.outflow == 300000
    assert fluxo.current_outflow == 0


def test_entrada_propria_e_mesma_conta_nao_movem_nada():
    fluxo = _projeta([_entra(100000, TITULAR), _entra(100000, "v1", CONTA), _sai(50000, "y", CONTA)], 100000)

    assert fluxo.incoming == 0 and fluxo.outflow == 0


def test_conta_propria_escoa_o_dinheiro_de_terceiros():
    fluxo = _projeta(VITIMAS, 270000, TITULAR, OUTRA_CONTA)

    assert (fluxo.current_refund, fluxo.current_outflow) == (0, 270000)
    assert fluxo.identifies(3, OITENTA)


def test_pix_para_a_mesma_conta_nao_e_saida():
    fluxo = _projeta(VITIMAS, 270000, TITULAR, CONTA)

    assert fluxo.current_outflow == 0
    assert not fluxo.identifies(3, OITENTA)


def test_o_corte_e_exato():
    assert _projeta(VITIMAS, 240000).identifies(3, OITENTA)
    assert not _projeta(VITIMAS, 239999).identifies(3, OITENTA)
    assert _projeta(VITIMAS, 200000).identifies(3, Fraction("2") / 3)
    assert not _projeta(VITIMAS, 199999).identifies(3, Fraction("2") / 3)


def test_sem_base_nao_ha_repasse():
    fluxo = _projeta([], 100000)

    assert fluxo.base == 0 and not fluxo.reaches(OITENTA)


def test_muitos_eventos_numa_varredura_so():
    # 200 mil entradas e saidas intercaladas: cada lote entra e sai uma vez
    # de cada fila, entao a soma fecha e o tempo fica linear.
    movimentos = []
    for indice in range(100000):
        movimentos += [_entra(100, f"p{indice % 500}"), _sai(90, "x")]
    fluxo = _projeta(movimentos, 1000)

    assert fluxo.incoming == 10000000
    assert fluxo.outflow == 9000000 + 1000
