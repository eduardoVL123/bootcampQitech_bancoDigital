"""Concentracao, repasse, coordenacao entre contas e a rede de dois saltos."""
import random
from datetime import timedelta

from tests.utils.pix import (
    RECEBEDOR_MARCACAO_CRITICA, Pagador, Recebedor, analisa, disparou, historico, nova_base, pix, pontos, regra,
)

CASA = "99999999"


def _varios_pagam(recebedor, quantos, hoje, valor=5000):
    corpos = []
    for indice in range(quantos):
        corpos.append(analisa(pix(Pagador(), recebedor, valor, (hoje + timedelta(minutes=indice)).isoformat())))
    return corpos


def test_cinco_pagadores_para_conta_nova_somam_40():
    hoje = nova_base()
    corpos = _varios_pagam(Recebedor(aberta_em=hoje - timedelta(days=10)), 5, hoje)

    assert not disparou(corpos[3], "CONTA_LARANJA")
    assert pontos(corpos[4], "CONTA_LARANJA") == 40


def test_dez_pagadores_para_conta_nova_somam_60_e_sem_o_grupo_pedem_facial_document():
    # 60 de concentracao + 20 de conta nova = 80, tudo no eixo destino. So
    # reprova se o grupo do titular confirmar (test_grupo_do_titular.py): este
    # CPF novo so tem a conta que esta recebendo.
    hoje = nova_base()
    corpos = _varios_pagam(Recebedor(aberta_em=hoje - timedelta(days=10)), 10, hoje)

    assert pontos(corpos[-1], "CONTA_LARANJA") == 60
    assert corpos[-1]["metadata"]["risk_axes"]["destino"] == 80
    assert corpos[-1]["status"] == "two_factor_required"
    assert corpos[-1]["metadata"]["authentication"]["level"] == "facial_document"
    assert corpos[-1]["metadata"]["destination_group"]["gate"] == "facial_document"
    assert corpos[-1]["metadata"]["scenario"] == "conta_laranja"


def test_cinco_pagadores_para_conta_antiga_somam_20():
    corpos = _varios_pagam(Recebedor(), 5, nova_base())

    assert pontos(corpos[-1], "CONTA_LARANJA") == 20


def test_mesmo_pagador_repetido_nao_e_conta_laranja():
    hoje = nova_base()
    pagador, recebedor = Pagador(), Recebedor(aberta_em=hoje - timedelta(days=10))
    corpos = [analisa(pix(pagador, recebedor, 5000, (hoje + timedelta(minutes=2 * i)).isoformat())) for i in range(6)]

    assert not disparou(corpos[-1], "CONTA_LARANJA")


def _recebe_de_quatro(hoje, valor=100000):
    conta = Recebedor(participante=CASA)
    for indice in range(4):
        analisa(pix(Pagador(), conta, valor, (hoje + timedelta(minutes=indice)).isoformat()))
    return conta


def test_recebe_de_varios_e_esvazia_soma_60():
    hoje = nova_base()
    conta = _recebe_de_quatro(hoje)

    corpo = analisa(pix(conta.como_pagador(), Recebedor(), 350000, (hoje + timedelta(minutes=10)).isoformat()))

    assert pontos(corpo, "REPASSE_RAPIDO") == 60
    assert corpo["metadata"]["scenario"] == "conta_laranja"


def test_devolver_a_quem_pagou_nao_e_repasse():
    hoje = nova_base()
    conta = Recebedor(participante=CASA)
    pagadores = [Pagador() for _ in range(4)]
    for indice, pagador in enumerate(pagadores):
        analisa(pix(pagador, conta, 100000, (hoje + timedelta(minutes=indice)).isoformat()))
    devolve_para = Recebedor(documento=pagadores[0].documento)

    corpo = analisa(pix(conta.como_pagador(), devolve_para, 350000, (hoje + timedelta(minutes=10)).isoformat()))

    assert not disparou(corpo, "REPASSE_RAPIDO")


def test_saida_pequena_nao_e_repasse():
    hoje = nova_base()
    conta = _recebe_de_quatro(hoje)

    corpo = analisa(pix(conta.como_pagador(), Recebedor(), 50000, (hoje + timedelta(minutes=10)).isoformat()))

    assert not disparou(corpo, "REPASSE_RAPIDO")


def test_repasse_para_destino_familiar_sem_perfil_avaliavel_soma_20():
    hoje = nova_base()
    conta = Recebedor(participante=CASA)
    fornecedor = Recebedor()
    historico(conta.como_pagador(), [500000] * 3, hoje - timedelta(days=20), timedelta(days=4), recebedor=fornecedor)
    for indice in range(4):
        analisa(pix(Pagador(), conta, 100000, (hoje + timedelta(minutes=indice)).isoformat()))

    corpo = analisa(pix(conta.como_pagador(), fornecedor, 350000, (hoje + timedelta(minutes=10)).isoformat()))

    assert pontos(corpo, "REPASSE_RAPIDO") == 20


def test_repasse_para_conta_de_3_horas_sem_o_grupo_pede_facial_document():
    # 90 so no eixo destino (REPASSE_RAPIDO 60 + DESTINO_NOVO 30). Reprovaria
    # se o grupo do titular do destino confirmasse; um CPF novo nao confirma.
    hoje = nova_base()
    conta = _recebe_de_quatro(hoje)
    novo = Recebedor(aberta_em=hoje - timedelta(hours=3))

    corpo = analisa(pix(conta.como_pagador(), novo, 350000, (hoje + timedelta(minutes=10)).isoformat()))

    assert corpo["metadata"]["risk_axes"]["destino"] == 90
    assert corpo["status"] == "two_factor_required"
    assert corpo["metadata"]["authentication"]["level"] == "facial_document"
    assert corpo["metadata"]["destination_group"]["gate"] == "facial_document"


def test_coordenacao_pede_facial_e_suprime_aparelho_compartilhado():
    hoje = nova_base()
    aparelho = f"dvc-coord-{random.randint(0, 10**9)}"
    destino = Recebedor(aberta_em=hoje - timedelta(days=3))
    corpos = [analisa(pix(Pagador(), destino, 5000, (hoje + timedelta(minutes=i)).isoformat(), aparelho=aparelho))
              for i in range(3)]

    ultimo = corpos[-1]
    assert pontos(ultimo, "COORDENACAO_ENTRE_CONTAS") == 40
    assert regra(ultimo, "APARELHO_COMPARTILHADO")["correlated"] is True
    assert pontos(ultimo, "APARELHO_COMPARTILHADO") == 0
    assert ultimo["metadata"]["authentication"]["level"] in ("facial", "facial_document")
    assert ultimo["metadata"]["scenario"] == "coordenacao_entre_contas"


def test_destino_a_dois_saltos_de_uma_ancora_soma_30():
    hoje = nova_base()
    ancora = Pagador(documento=RECEBEDOR_MARCACAO_CRITICA)
    meio, destino = Recebedor(), Recebedor()
    analisa(pix(ancora, meio, 5000, (hoje - timedelta(days=2)).isoformat()))
    analisa(pix(meio.como_pagador(), destino, 5000, (hoje - timedelta(days=1)).isoformat()))

    corpo = analisa(pix(Pagador(), destino, 5000, hoje.isoformat()))

    rede = regra(corpo, "REDE_SUSPEITA")
    assert rede["raw_points"] == 30
    assert rede["hops"] == 2


def test_aresta_de_centavos_nao_contamina_o_destino():
    # Uma ancora que e cliente da casa manda R$ 0,01 para uma loja. Antes, todo
    # mundo que pagasse a loja depois levava +30.
    hoje = nova_base()
    ancora, loja = Pagador(documento=RECEBEDOR_MARCACAO_CRITICA), Recebedor(pj=True)
    analisa(pix(ancora, loja, 1, (hoje - timedelta(hours=2)).isoformat()))

    corpo = analisa(pix(Pagador(), loja, 5000, hoje.isoformat()))

    assert not disparou(corpo, "REDE_SUSPEITA")


def test_destino_que_o_pagador_ja_paga_nao_ganha_a_suspeita():
    hoje = nova_base()
    cliente, loja = Pagador(), Recebedor(pj=True)
    analisa(pix(cliente, loja, 5000, (hoje - timedelta(days=5)).isoformat()))
    analisa(pix(Pagador(documento=RECEBEDOR_MARCACAO_CRITICA), loja, 5000, (hoje - timedelta(days=1)).isoformat()))

    corpo = analisa(pix(cliente, loja, 5000, hoje.isoformat()))

    assert not disparou(corpo, "REDE_SUSPEITA")


def test_tres_saltos_nao_dispara():
    hoje = nova_base()
    ancora = Pagador(documento=RECEBEDOR_MARCACAO_CRITICA)
    primeiro, segundo, destino = Recebedor(), Recebedor(), Recebedor()
    analisa(pix(ancora, primeiro, 5000, (hoje - timedelta(days=3)).isoformat()))
    analisa(pix(primeiro.como_pagador(), segundo, 5000, (hoje - timedelta(days=2)).isoformat()))
    analisa(pix(segundo.como_pagador(), destino, 5000, (hoje - timedelta(days=1)).isoformat()))

    corpo = analisa(pix(Pagador(), destino, 5000, hoje.isoformat()))

    assert not disparou(corpo, "REDE_SUSPEITA")
