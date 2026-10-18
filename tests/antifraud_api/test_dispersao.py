"""Dispersao de saida: o titular manda dinheiro para muitos destinos que nunca tinha pago, no mesmo dia.

E o dreno da mao fantasma: aparelho, IP e lugar sao os de sempre, cada Pix
fica abaixo dos cortes de valor e de ritmo, e cada um vai para uma conta
diferente.
"""
from datetime import timedelta

from tests.utils.pix import Pagador, Recebedor, analisa, disparou, nova_base, paga, pix, pontos, regra


def _espalha(pagador, hoje, quantos, valor=65000, pj=False):
    """Um Pix a cada 31 min (fora da janela da VELOCITY), cada um para um destino novo."""
    return [analisa(pix(pagador, Recebedor(pj=pj), valor, (hoje + timedelta(minutes=31 * i)).isoformat()))
            for i in range(quantos)]


def test_quinto_destino_novo_no_dia_pede_verificacao():
    corpos = _espalha(Pagador(), nova_base(), 5)

    assert not disparou(corpos[3], "DISPERSAO_DE_SAIDA")
    assert pontos(corpos[4], "DISPERSAO_DE_SAIDA") == 40
    assert regra(corpos[4], "DISPERSAO_DE_SAIDA")["new_destinations"] == 5
    assert corpos[4]["status"] == "two_factor_required"


def test_pagar_os_destinos_de_sempre_no_mesmo_dia_nao_espalha():
    # Cinco destinos ja pagos em dias anteriores, um por dia: pagar os cinco
    # hoje nao e espalhar dinheiro para gente nova.
    hoje, pagador = nova_base(), Pagador()
    conhecidos = [Recebedor() for _ in range(5)]
    for indice, destino in enumerate(conhecidos):
        paga(pix(pagador, destino, 20000, (hoje - timedelta(days=indice + 2)).isoformat()))

    corpos = [analisa(pix(pagador, destino, 20000, (hoje + timedelta(minutes=31 * i)).isoformat()))
              for i, destino in enumerate(conhecidos)]

    assert not any(disparou(corpo, "DISPERSAO_DE_SAIDA") for corpo in corpos)


def test_empresa_pagando_fornecedores_novos_tem_corte_maior():
    corpos = _espalha(Pagador(pj=True), nova_base(), 6, pj=True)

    assert not disparou(corpos[-1], "DISPERSAO_DE_SAIDA")


def test_pix_abaixo_de_100_reais_nao_conta_como_destino_novo():
    hoje, pagador = nova_base(), Pagador()
    _espalha(pagador, hoje, 4, valor=500)

    corpo = analisa(pix(pagador, Recebedor(), 65000, (hoje + timedelta(hours=3)).isoformat()))

    assert not disparou(corpo, "DISPERSAO_DE_SAIDA")
