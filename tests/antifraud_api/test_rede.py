"""Concentracao, repasse, coordenacao entre contas e a rede, nos dois sentidos do dinheiro."""
import random
from datetime import timedelta

from tests.utils.pix import (
    RECEBEDOR_ALERTA, RECEBEDOR_MARCACAO_CRITICA, AntifraudApi, Pagador, Recebedor, analisa, disparou, historico,
    nega, nova_base, paga, pix, pontos, regra,
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


def _vitimas_pagam(conta, hoje, quantas=3, valor=100000, primeiro_minuto=0):
    """Titulares diferentes pagam a conta, um por minuto. O 2FA, se vier, e confirmado: o dinheiro entrou."""
    pagadores = [Pagador() for _ in range(quantas)]
    for indice, pagador in enumerate(pagadores):
        paga(pix(pagador, conta, valor, (hoje + timedelta(minutes=primeiro_minuto + indice)).isoformat()))
    return pagadores


def _sai(pagador, recebedor, valor, data):
    """Uma saida que virou dinheiro: aprovada, ou com o 2FA confirmado."""
    corpo = paga(pix(pagador, recebedor, valor, data.isoformat()))
    assert corpo["status"] != "rejected", corpo["metadata"]["reason"]
    return corpo


def _fluxo(corpo):
    resultado = regra(corpo, "REPASSE_RAPIDO")
    return {chave: resultado[chave] for chave in ("window_minutes", "incoming", "refunded", "outflow", "base",
                                                  "current_refund", "current_outflow", "qualified_payers")}


def test_tres_entradas_e_uma_saida_de_2700_soma_60():
    # O replay de cada entrada nao conta o dinheiro duas vezes.
    hoje = nova_base()
    conta = Recebedor(participante=CASA)
    for indice in range(3):
        entrada = pix(Pagador(), conta, 100000, (hoje + timedelta(minutes=indice)).isoformat())
        paga(entrada)
        analisa(entrada)

    corpo = analisa(pix(conta.como_pagador(), Recebedor(), 270000, (hoje + timedelta(minutes=10)).isoformat()))

    assert pontos(corpo, "REPASSE_RAPIDO") == 60
    assert _fluxo(corpo) == {"window_minutes": 60, "incoming": 300000, "refunded": 0, "outflow": 270000,
                             "base": 300000, "current_refund": 0, "current_outflow": 270000, "qualified_payers": 3}
    assert regra(corpo, "REPASSE_RAPIDO")["attribution"] == "fifo_heuristic"


def test_repasse_fatiado_em_tres_saidas_dispara_na_terceira():
    # R$ 3.000 de tres titulares saem em tres Pix de R$ 1.000. Cada saida e
    # um terco do que entrou; o acumulado e o repasse inteiro.
    hoje = nova_base()
    conta = Recebedor(participante=CASA)
    _vitimas_pagam(conta, hoje)
    laranja = conta.como_pagador()
    anteriores = [_sai(laranja, Recebedor(), 100000, hoje + timedelta(minutes=10 + indice)) for indice in range(2)]

    corpo = analisa(pix(laranja, Recebedor(), 100000, (hoje + timedelta(minutes=12)).isoformat()))

    assert not any(disparou(anterior, "REPASSE_RAPIDO") for anterior in anteriores)
    assert pontos(corpo, "REPASSE_RAPIDO") == 60
    assert _fluxo(corpo)["outflow"] == 300000
    assert _fluxo(corpo)["current_outflow"] == 100000


def test_centavo_do_destino_nao_transforma_o_repasse_em_devolucao():
    # O destino final manda R$ 0,01 para a conta e depois recebe R$ 2.700: so
    # o centavo e devolucao, o resto e o dinheiro das vitimas saindo.
    hoje = nova_base()
    conta = Recebedor(participante=CASA)
    _vitimas_pagam(conta, hoje)
    destino = Pagador()
    paga(pix(destino, conta, 1, (hoje + timedelta(minutes=5)).isoformat()))

    corpo = analisa(pix(conta.como_pagador(), Recebedor(documento=destino.documento), 270000,
                        (hoje + timedelta(minutes=10)).isoformat()))

    assert pontos(corpo, "REPASSE_RAPIDO") == 60
    assert _fluxo(corpo) == {"window_minutes": 60, "incoming": 300001, "refunded": 1, "outflow": 269999,
                             "base": 300000, "current_refund": 1, "current_outflow": 269999, "qualified_payers": 3}


def test_devolver_mais_que_o_credito_de_quem_pagou_e_repasse():
    # Era o teste que aceitava a devolucao inteira so porque o destino estava
    # entre os pagadores. Ele pagou R$ 1.000: o resto e dinheiro dos outros.
    hoje = nova_base()
    conta = Recebedor(participante=CASA)
    pagadores = _vitimas_pagam(conta, hoje, 4)

    corpo = analisa(pix(conta.como_pagador(), Recebedor(documento=pagadores[0].documento), 350000,
                        (hoje + timedelta(minutes=10)).isoformat()))

    assert pontos(corpo, "REPASSE_RAPIDO") == 60
    assert _fluxo(corpo) == {"window_minutes": 60, "incoming": 400000, "refunded": 100000, "outflow": 250000,
                             "base": 300000, "current_refund": 100000, "current_outflow": 250000,
                             "qualified_payers": 3}


def test_devolver_a_quem_pagou_ate_o_credito_nao_e_repasse():
    # Cada um recebe de volta o que pagou: nada de terceiros sai da conta.
    hoje = nova_base()
    conta = Recebedor(participante=CASA)
    pagadores = _vitimas_pagam(conta, hoje)
    laranja = conta.como_pagador()

    corpos = [_sai(laranja, Recebedor(documento=pagador.documento), 100000, hoje + timedelta(minutes=10 + indice))
              for indice, pagador in enumerate(pagadores)]
    depois = analisa(pix(laranja, Recebedor(), 100000, (hoje + timedelta(minutes=20)).isoformat()))

    assert not any(disparou(corpo, "REPASSE_RAPIDO") for corpo in corpos)
    assert not disparou(depois, "REPASSE_RAPIDO")


def test_o_mesmo_credito_so_justifica_uma_devolucao():
    # Quem pagou R$ 100 recebe R$ 100 de volta, e depois mais R$ 100. A
    # segunda ja nao tem credito dele: escoa o dinheiro das vitimas e completa
    # o repasse que a saida de R$ 2.300 tinha deixado abaixo do corte.
    hoje = nova_base()
    conta = Recebedor(participante=CASA)
    _vitimas_pagam(conta, hoje)
    amigo = Pagador()
    paga(pix(amigo, conta, 10000, (hoje + timedelta(minutes=5)).isoformat()))
    laranja, volta = conta.como_pagador(), Recebedor(documento=amigo.documento)
    escoou = _sai(laranja, Recebedor(), 230000, hoje + timedelta(minutes=10))
    devolveu = _sai(laranja, volta, 10000, hoje + timedelta(minutes=11))

    corpo = analisa(pix(laranja, volta, 10000, (hoje + timedelta(minutes=12)).isoformat()))

    assert not disparou(escoou, "REPASSE_RAPIDO")
    assert not disparou(devolveu, "REPASSE_RAPIDO")
    assert pontos(corpo, "REPASSE_RAPIDO") == 60
    assert _fluxo(corpo) == {"window_minutes": 60, "incoming": 310000, "refunded": 10000, "outflow": 240000,
                             "base": 300000, "current_refund": 0, "current_outflow": 10000, "qualified_payers": 3}


def test_saida_antes_das_entradas_nao_usa_credito_que_nao_existia():
    hoje = nova_base()
    conta = Recebedor(participante=CASA)
    laranja = conta.como_pagador()
    _sai(laranja, Recebedor(), 270000, hoje)
    _vitimas_pagam(conta, hoje, primeiro_minuto=1)

    corpo = analisa(pix(laranja, Recebedor(), 50000, (hoje + timedelta(minutes=10)).isoformat()))

    assert not disparou(corpo, "REPASSE_RAPIDO")


def test_credito_consumido_nao_volta_e_entrada_nova_cria_credito_novo():
    # O primeiro lote escoou ate o credito do pagador 1. A saida para ele
    # depois nao e devolucao: o credito dele ja saiu. Com o segundo lote, o
    # acumulado chega a 80%.
    hoje = nova_base()
    conta = Recebedor(participante=CASA)
    primeiros = _vitimas_pagam(conta, hoje)
    laranja = conta.como_pagador()
    _sai(laranja, Recebedor(), 200000, hoje + timedelta(minutes=5))
    _vitimas_pagam(conta, hoje, primeiro_minuto=10)

    corpo = analisa(pix(laranja, Recebedor(documento=primeiros[0].documento), 280000,
                        (hoje + timedelta(minutes=15)).isoformat()))

    assert pontos(corpo, "REPASSE_RAPIDO") == 60
    assert _fluxo(corpo) == {"window_minutes": 60, "incoming": 600000, "refunded": 0, "outflow": 480000,
                             "base": 600000, "current_refund": 0, "current_outflow": 280000, "qualified_payers": 6}


def _entrada_com_desafio(conta, hoje, resultado):
    """R$ 25 mil de um terceiro 3 h antes (fora da janela de 1 h), com o desafio respondido em hoje + 5 min."""
    entrada = pix(Pagador(), conta, 2500000, (hoje - timedelta(hours=3)).isoformat())
    assert analisa(entrada)["status"] == "two_factor_required"
    resposta = AntifraudApi.patch(entrada["id"], {"challenge_result": resultado,
                                                  "event_date": (hoje + timedelta(minutes=5)).isoformat()})
    assert resposta.status_code == 200, resposta.text


def test_credito_confirmado_entra_no_fluxo_so_depois_da_confirmacao():
    # O Pix e de 3 h antes, e a confirmacao, de dentro da janela de 1 h. Antes
    # dela, o credito estava pendente e nao financia nada; depois, entra na
    # janela pela confirmacao, e nao some pelo filtro da data do Pix.
    hoje = nova_base()
    conta = Recebedor(participante=CASA)
    _entrada_com_desafio(conta, hoje, "approved_by_client")
    _vitimas_pagam(conta, hoje, 2)
    laranja = conta.como_pagador()

    antes = analisa(pix(laranja, Recebedor(), 2500000, (hoje + timedelta(minutes=3)).isoformat()))
    depois = analisa(pix(laranja, Recebedor(), 2500000, (hoje + timedelta(minutes=10)).isoformat()))

    assert not disparou(antes, "REPASSE_RAPIDO")
    assert pontos(depois, "REPASSE_RAPIDO") == 60
    assert _fluxo(depois)["window_minutes"] == 60
    assert _fluxo(depois)["incoming"] == 2700000


def test_credito_com_desafio_recusado_nao_financia_o_repasse():
    hoje = nova_base()
    conta = Recebedor(participante=CASA)
    _entrada_com_desafio(conta, hoje, "reproved_by_client")
    _vitimas_pagam(conta, hoje, 2)

    corpo = analisa(pix(conta.como_pagador(), Recebedor(), 2500000, (hoje + timedelta(minutes=10)).isoformat()))

    assert not disparou(corpo, "REPASSE_RAPIDO")


def test_mandar_para_outra_conta_propria_nao_apaga_o_repasse():
    hoje = nova_base()
    conta = Recebedor(participante=CASA)
    _vitimas_pagam(conta, hoje)

    corpo = analisa(pix(conta.como_pagador(), Recebedor(documento=conta.documento), 270000,
                        (hoje + timedelta(minutes=10)).isoformat()))

    assert pontos(corpo, "REPASSE_RAPIDO") == 60


def test_transferencia_entre_contas_proprias_sem_terceiros_nao_e_repasse():
    hoje = nova_base()
    conta = Recebedor(participante=CASA)
    for indice in range(3):
        paga(pix(Pagador(documento=conta.documento), conta, 100000, (hoje + timedelta(minutes=indice)).isoformat()))

    corpo = analisa(pix(conta.como_pagador(), Recebedor(documento=conta.documento), 270000,
                        (hoje + timedelta(minutes=10)).isoformat()))

    assert not disparou(corpo, "REPASSE_RAPIDO")


def test_o_corte_de_80_por_cento_e_exato():
    hoje = nova_base()
    no_corte, abaixo = Recebedor(participante=CASA), Recebedor(participante=CASA)
    _vitimas_pagam(no_corte, hoje)
    _vitimas_pagam(abaixo, hoje)

    exato = analisa(pix(no_corte.como_pagador(), Recebedor(), 240000, (hoje + timedelta(minutes=10)).isoformat()))
    um_centavo_abaixo = analisa(pix(abaixo.como_pagador(), Recebedor(), 239999,
                                    (hoje + timedelta(minutes=10)).isoformat()))

    assert pontos(exato, "REPASSE_RAPIDO") == 60
    assert not disparou(um_centavo_abaixo, "REPASSE_RAPIDO")


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


def test_laranja_que_repassa_para_a_ancora_contamina_quem_paga_ela():
    # A laranja recebe de duas pessoas sem vinculo e manda o dinheiro para a
    # ancora. O repasse e recusado (a ancora tem marcacao critica), mas a
    # recusa mostra para onde o dinheiro ia: a proxima vitima e protegida.
    hoje, laranja = nova_base(), Recebedor()
    ancora = Recebedor(documento=RECEBEDOR_MARCACAO_CRITICA)
    for minutos in (180, 120):
        analisa(pix(Pagador(), laranja, 30000, (hoje - timedelta(minutes=minutos)).isoformat()))
    repasse = analisa(pix(laranja.como_pagador(), ancora, 50000, (hoje - timedelta(hours=1)).isoformat()))
    assert repasse["status"] == "rejected"

    corpo = analisa(pix(Pagador(), laranja, 5000, hoje.isoformat()))

    rede = regra(corpo, "REDE_SUSPEITA")
    assert rede["raw_points"] == 60
    assert rede["direction"] == "to_anchor"


def test_vitima_que_pagou_a_ancora_com_o_proprio_dinheiro_nao_contamina():
    hoje, vitima = nova_base(), Recebedor()
    analisa(pix(vitima.como_pagador(), Recebedor(documento=RECEBEDOR_MARCACAO_CRITICA), 50000,
                (hoje - timedelta(hours=1)).isoformat()))

    corpo = analisa(pix(Pagador(), vitima, 5000, hoje.isoformat()))

    assert not disparou(corpo, "REDE_SUSPEITA")


def test_repasse_do_dinheiro_de_quem_tem_vinculo_nao_contamina():
    # O organizador junta o dinheiro dos amigos de sempre e paga uma agencia
    # que era golpe. Ele e vitima, nao laranja: os amigos ja pagavam ele antes.
    hoje, organizador = nova_base(), Recebedor()
    amigos = [Pagador(), Pagador()]
    for amigo in amigos:
        analisa(pix(amigo, organizador, 5000, (hoje - timedelta(days=10)).isoformat()))
    for minutos, amigo in zip((180, 120), amigos):
        analisa(pix(amigo, organizador, 30000, (hoje - timedelta(minutes=minutos)).isoformat()))
    analisa(pix(organizador.como_pagador(), Recebedor(documento=RECEBEDOR_MARCACAO_CRITICA), 50000,
                (hoje - timedelta(hours=1)).isoformat()))

    corpo = analisa(pix(Pagador(), organizador, 5000, hoje.isoformat()))

    assert not disparou(corpo, "REDE_SUSPEITA")


def test_cautelar_de_um_titular_so_nao_espalha_pela_rede():
    # O denunciado pagou uma loja. Antes, um "nao fui eu" so fazia todo cliente
    # novo da loja levar +60 por 30 dias.
    hoje, denunciado, loja = nova_base(), Recebedor(), Recebedor(pj=True)
    analisa(pix(denunciado.como_pagador(), loja, 20000, (hoje - timedelta(days=2)).isoformat()))
    nega(Pagador(), denunciado, 2500000, hoje - timedelta(days=1))

    corpo = analisa(pix(Pagador(), loja, 150000, hoje.isoformat()))

    assert not disparou(corpo, "REDE_SUSPEITA")


def test_denuncia_confirmada_espalha_pela_rede():
    hoje, denunciado, vizinho = nova_base(), Recebedor(), Recebedor()
    analisa(pix(denunciado.como_pagador(), vizinho, 20000, (hoje - timedelta(days=2)).isoformat()))
    nega(Pagador(), denunciado, 2500000, hoje - timedelta(days=1))
    nega(Pagador(), denunciado, 50000, hoje - timedelta(hours=23))

    corpo = analisa(pix(Pagador(), vizinho, 5000, hoje.isoformat()))

    assert pontos(corpo, "REDE_SUSPEITA") == 60
