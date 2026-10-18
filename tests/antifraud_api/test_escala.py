"""Escala: o custo de um Pix nao pode crescer com o quadrado do historico.

O motor calcula a regua de cada cliente (controllers/engine/reference.py)
com os eventos dos 30 dias anteriores. Uma loja que recebe muito tem
milhares deles. Se a janela movel varre todos os eventos anteriores para
cada evento, o custo cresce com o quadrado: medido isolado, 1.000 eventos
levavam 109 ms, 5.000 levavam 2,8 s e 10.000, 11,4 s (tools/escala_antifraude.py
e docs/testes/antifraude-escala.md).

O teste compara o Pix para uma loja movimentada com o Pix para uma loja
sem movimento, com pagadores do mesmo tipo. Comparar as duas, e nao um
tempo fixo, deixa o teste valer numa maquina lenta e numa rapida.

Monta 800 recebimentos pela API, o que leva perto de um minuto: por isso
so roda com RUN_ESCALA=true (o workflow curto do antifraude liga).
"""
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from os import environ
from statistics import median

import pytest

from tests.utils.pix import Pagador, Recebedor, analisa, nova_base, paga, pix

pytestmark = pytest.mark.skipif(environ.get("RUN_ESCALA") != "true",
                                reason="teste de escala: monta 800 Pix pela API; ligue com RUN_ESCALA=true")

RECEBIMENTOS = 800
POR_PAGADOR = 5


def _enche(loja: Recebedor, hoje) -> None:
    """800 Pix aprovados para a loja, espalhados nos 29 dias antes de hoje."""
    passo = timedelta(days=29) / RECEBIMENTOS
    inicio = hoje - timedelta(days=29, hours=1)

    def um_pagador(indice: int) -> None:
        pagador = Pagador()
        for vez in range(POR_PAGADOR):
            # Cada pagador anda para a frente no tempo (sem DATA_RETROATIVA),
            # e os pagadores se intercalam ao longo dos 29 dias.
            momento = inicio + passo * (vez * (RECEBIMENTOS // POR_PAGADOR) + indice)
            paga(pix(pagador, loja, 5000, momento.isoformat()))

    with ThreadPoolExecutor(max_workers=8) as pool:
        list(pool.map(um_pagador, range(RECEBIMENTOS // POR_PAGADOR)))


def _latencia(loja: Recebedor, hoje, quantos: int = 7) -> float:
    """Mediana do latency_ms de Pix de pagadores novos para a loja, hoje."""
    tempos = []
    for indice in range(quantos):
        corpo = analisa(pix(Pagador(), loja, 5000, (hoje + timedelta(minutes=indice)).isoformat()))
        tempos.append(corpo["metadata"]["latency_ms"])
    return median(tempos)


def test_pix_para_loja_com_800_recebimentos_custa_quase_o_mesmo_que_para_loja_parada():
    hoje = nova_base()
    movimentada = Recebedor(pj=True)
    parada = Recebedor(pj=True)
    _enche(movimentada, hoje)

    calma = _latencia(parada, hoje)
    cheia = _latencia(movimentada, hoje)

    # A folga cobre o trabalho que cresce de verdade com o historico (ler
    # 800 linhas, montar a regua). O que nao cabe nela e varrer a janela
    # inteira de novo para cada evento.
    assert cheia <= max(1.5 * calma, calma + 30), f"loja parada {calma} ms, loja com 800 recebimentos {cheia} ms"
