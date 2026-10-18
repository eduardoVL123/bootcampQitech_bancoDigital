"""Concentracao, repasse, coordenacao entre contas e a rede de dois saltos."""
import random
from datetime import timedelta

from tests.utils.pix import (
    RECEBEDOR_ALERTA, RECEBEDOR_MARCACAO_CRITICA, AntifraudApi, Pagador, Recebedor, analisa, disparou, historico,
    nova_base, pix, pontos, regra,
)

CASA = "99999999"


def _varios_pagam(recebedor, quantos, hoje, valor=5000):
    corpos = []
    for indice in range(quantos):
        corpos.append(analisa(pix(Pagador(), recebedor, valor, (hoje + timedelta(minutes=indice)).isoformat())))
    return corpos


def _no_pico(recebedor, hoje, valor_do_ultimo=5000, ultimo=None):
    """Nove pagadores de R$ 50 na mesma hora, e o decimo com o valor pedido. Devolve o corpo do decimo."""
    _varios_pagam(recebedor, 9, hoje)
    return analisa(pix(ultimo or Pagador(), recebedor, valor_do_ultimo, (hoje + timedelta(minutes=9)).isoformat()))


def _nao_fui_eu(pagador, recebedor, hoje):
    """O titular nega o desafio de um Pix de R$ 25 mil, duas horas antes: o aparelho e o recebedor vao para a lista."""
    negado = pix(pagador, recebedor, 2500000, (hoje - timedelta(hours=2)).isoformat())
    assert analisa(negado)["status"] == "two_factor_required"
    resposta = AntifraudApi.patch(negado["id"], {"challenge_result": "reproved_by_client",
                                                 "event_date": (hoje - timedelta(hours=2) + timedelta(minutes=1)).isoformat()})
    assert resposta.status_code == 200, resposta.text


def test_cinco_pagadores_para_conta_nova_somam_40():
    hoje = nova_base()
    corpos = _varios_pagam(Recebedor(aberta_em=hoje - timedelta(days=10)), 5, hoje)

    assert not disparou(corpos[3], "CONTA_LARANJA")
    assert pontos(corpos[4], "CONTA_LARANJA") == 40


def test_dez_pagadores_para_conta_nova_somam_80_e_sem_denuncia_pedem_2fa():
    # 60 de concentracao + 20 de conta nova = 80, tudo no eixo destino. Pode ser
    # loja lancando produto ou conta laranja: sem denuncia do recebedor, e com a
    # conta fora da primeira semana, o eixo destino nao reprova sozinho.
    hoje = nova_base()
    corpos = _varios_pagam(Recebedor(aberta_em=hoje - timedelta(days=10)), 10, hoje)

    assert pontos(corpos[-1], "CONTA_LARANJA") == 60
    assert corpos[-1]["metadata"]["risk_axes"]["destino"] == 80
    assert corpos[-1]["status"] == "two_factor_required"
    assert corpos[-1]["metadata"]["authentication"]["level"] == "facial_document"
    assert corpos[-1]["metadata"]["scenario"] == "conta_laranja"


def test_dez_pagadores_para_conta_com_denuncia_aberta_reprovam():
    # A mesma concentracao, com uma denuncia aberta contra o recebedor no mock:
    # loja de verdade nao junta denuncia na primeira semana.
    hoje = nova_base()
    corpos = _varios_pagam(Recebedor(documento=RECEBEDOR_ALERTA, aberta_em=hoje - timedelta(days=10)), 10, hoje)

    assert disparou(corpos[-1], "REPUTACAO_EXTERNA")
    assert corpos[-1]["metadata"]["risk_axes"]["destino"] == 120
    assert corpos[-1]["status"] == "rejected"


def test_dez_pagadores_depois_do_nao_fui_eu_de_outro_cliente_reprovam():
    hoje = nova_base()
    recebedor = Recebedor(aberta_em=hoje - timedelta(days=10))
    _nao_fui_eu(Pagador(), recebedor, hoje)

    corpos = _varios_pagam(recebedor, 10, hoje)

    assert regra(corpos[-1], "REPUTACAO_INTERNA")["kind"] == "document"
    assert regra(corpos[-1], "REPUTACAO_INTERNA")["creator"] == "client"
    assert corpos[-1]["status"] == "rejected"


def test_aparelho_do_pagador_na_lista_nao_e_denuncia_do_recebedor():
    # O "nao fui eu" lista tambem o aparelho. Aqui esse aparelho paga outra
    # conta: e risco de quem paga, e contra ele a facial funciona.
    hoje, pagador = nova_base(), Pagador()
    _nao_fui_eu(pagador, Recebedor(), hoje)

    corpo = _no_pico(Recebedor(aberta_em=hoje - timedelta(days=10)), hoje, ultimo=pagador)

    assert regra(corpo, "REPUTACAO_INTERNA")["kind"] == "device"
    assert corpo["metadata"]["risk_axes"]["destino"] == 120
    assert corpo["status"] == "two_factor_required"


def test_conta_da_primeira_semana_no_pico_recebe_ate_200_com_2fa():
    # Sem denuncia, a conta de 5 dias recebe ate o teto: a loja vende o tiquete
    # pequeno, com a verificacao que a tabela pede.
    hoje = nova_base()
    corpo = _no_pico(Recebedor(aberta_em=hoje - timedelta(days=5)), hoje, valor_do_ultimo=20000)

    assert corpo["metadata"]["risk_axes"]["destino"] == 80
    assert not disparou(corpo, "TETO_DESTINO_NOVO")
    assert corpo["status"] == "two_factor_required"


def test_conta_da_primeira_semana_no_pico_reprova_acima_de_200():
    hoje = nova_base()
    corpo = _no_pico(Recebedor(aberta_em=hoje - timedelta(days=5)), hoje, valor_do_ultimo=20001)

    assert disparou(corpo, "TETO_DESTINO_NOVO")
    assert corpo["metadata"]["risk_axes"]["destino"] == 80
    assert corpo["status"] == "rejected"


def test_conta_fora_da_primeira_semana_nao_tem_teto():
    hoje = nova_base()
    corpo = _no_pico(Recebedor(aberta_em=hoje - timedelta(days=10)), hoje, valor_do_ultimo=50000)

    assert not disparou(corpo, "TETO_DESTINO_NOVO")
    assert corpo["status"] == "two_factor_required"


def test_pix_sem_concentracao_para_conta_nova_acima_do_teto_continua_aprovado():
    # O teto so pesa com o eixo destino no corte: um Pix para quem acabou de
    # abrir conta, sem mais nada, segue como antes.
    hoje = nova_base()
    corpo = analisa(pix(Pagador(), Recebedor(aberta_em=hoje - timedelta(days=3)), 50000, hoje.isoformat()))

    assert disparou(corpo, "TETO_DESTINO_NOVO")
    assert corpo["status"] == "approved"


def test_dez_pagadores_espalhados_no_dia_para_conta_nova_somam_40():
    # Um por hora: a janela de 1 h nunca ve mais de um, a de 24 h ve os dez.
    hoje = nova_base()
    recebedor = Recebedor(aberta_em=hoje - timedelta(days=10))
    corpos = [analisa(pix(Pagador(), recebedor, 5000, (hoje + timedelta(hours=i)).isoformat())) for i in range(10)]

    assert pontos(corpos[-1], "CONTA_LARANJA") == 40
    assert regra(corpos[-1], "CONTA_LARANJA")["window_minutes"] == 1440


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


def _recebe_ao_longo_do_dia(hoje, quantos, valor=100000):
    """Um pagador por hora: a janela de 1 h nunca ve mais de um."""
    conta = Recebedor(participante=CASA)
    for indice in range(quantos):
        analisa(pix(Pagador(), conta, valor, (hoje + timedelta(hours=indice)).isoformat()))
    return conta


def test_recebe_de_cinco_ao_longo_do_dia_e_esvazia_soma_60():
    # A laranja que espera horas para repassar: so a janela de 24 h ve.
    hoje = nova_base()
    conta = _recebe_ao_longo_do_dia(hoje, 5)

    corpo = analisa(pix(conta.como_pagador(), Recebedor(), 450000, (hoje + timedelta(hours=5)).isoformat()))

    assert pontos(corpo, "REPASSE_RAPIDO") == 60


def test_quatro_pagadores_ao_longo_do_dia_nao_bastam_para_o_repasse():
    # Na janela de 24 h o corte e de 5 pagadores, e nao 3 como na de 1 h.
    hoje = nova_base()
    conta = _recebe_ao_longo_do_dia(hoje, 4)

    corpo = analisa(pix(conta.como_pagador(), Recebedor(), 350000, (hoje + timedelta(hours=4)).isoformat()))

    assert not disparou(corpo, "REPASSE_RAPIDO")


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


def test_repasse_para_conta_de_3_horas_reprova_pelo_eixo_destino():
    # Quem repassa e a propria conta laranja (cliente da casa): o dono dela
    # passa na facial. 90 so no eixo destino, sem denuncia do recebedor: quem
    # reprova e o teto da conta de 3 horas.
    hoje = nova_base()
    conta = _recebe_de_quatro(hoje)
    novo = Recebedor(aberta_em=hoje - timedelta(hours=3))

    corpo = analisa(pix(conta.como_pagador(), novo, 350000, (hoje + timedelta(minutes=10)).isoformat()))

    assert corpo["metadata"]["risk_axes"]["destino"] == 90
    assert disparou(corpo, "TETO_DESTINO_NOVO")
    assert corpo["status"] == "rejected"


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
