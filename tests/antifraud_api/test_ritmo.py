"""Ritmo e montante da conta pagadora: velocity, montante em 24h,
fatiamento e sondagem de limite. Sem historico de 30 dias, a velocity usa
a regua de reserva (firme de proposito)."""
from datetime import timedelta

from tests.utils.pix import (
    AntifraudApi, Pagador, Recebedor, analisa, disparou, nova_base, pix, pontos, regra,
)


def _sequencia(pagador, valores, intervalo, recebedor=None, base=None):
    """Manda varios Pix do mesmo pagador, espacados por `intervalo`."""
    base = base or nova_base()
    recebedor = recebedor or Recebedor()
    corpos = []
    for indice, valor in enumerate(valores):
        data = (base + intervalo * indice).isoformat()
        corpos.append(analisa(pix(pagador, recebedor, valor, data)))
    return corpos


def test_segunda_tentativa_em_5_min_nao_dispara():
    corpos = _sequencia(Pagador(), [5000, 5000], timedelta(minutes=1))

    assert not disparou(corpos[-1], "VELOCITY")


def test_terceira_tentativa_em_5_min_soma_25():
    corpos = _sequencia(Pagador(), [5000] * 3, timedelta(minutes=1))

    assert pontos(corpos[-1], "VELOCITY") == 25
    assert regra(corpos[-1], "VELOCITY")["reference"] == "fallback"


def test_rajada_dividida_entre_contas_do_mesmo_titular_conta_como_uma():
    # Cinco Pix em dois minutos, em tres contas do mesmo CPF: nenhuma conta
    # passa de dois, mas o titular fez cinco.
    base, titular, recebedor = nova_base(), Pagador(), Recebedor()
    contas = [titular] + [Pagador(documento=titular.documento) for _ in range(2)]

    corpos = [analisa(pix(contas[i % 3], recebedor, 5000, (base + timedelta(seconds=30 * i)).isoformat()))
              for i in range(5)]

    assert pontos(corpos[-1], "VELOCITY") == 40
    assert corpos[-1]["status"] == "two_factor_required"


def test_quinta_tentativa_em_5_min_pede_facial():
    corpos = _sequencia(Pagador(), [5000] * 5, timedelta(seconds=30))

    assert pontos(corpos[-1], "VELOCITY") == 40
    assert corpos[-1]["metadata"]["authentication"]["level"] == "facial"


def test_decima_tentativa_em_5_min_pede_facial_document():
    corpos = _sequencia(Pagador(), [5000] * 10, timedelta(seconds=20))

    assert pontos(corpos[-1], "VELOCITY") == 60
    assert corpos[-1]["metadata"]["authentication"]["level"] == "facial_document"


def test_empresa_com_nove_pagamentos_em_5_min_nao_dispara():
    # Empresa paga fornecedores e folha em lote: o corte de CNPJ comeca em 10.
    corpos = _sequencia(Pagador(pj=True), [5000] * 9, timedelta(seconds=20))

    assert not disparou(corpos[-1], "VELOCITY")


def test_empresa_com_dez_pagamentos_em_5_min_soma_25_sem_verificacao():
    # Os mesmos dez Pix, de uma pessoa fisica, pedem facial e documento.
    corpos = _sequencia(Pagador(pj=True), [5000] * 10, timedelta(seconds=20))

    assert pontos(corpos[-1], "VELOCITY") == 25
    assert regra(corpos[-1], "VELOCITY")["payer_type"] == "PJ"
    assert corpos[-1]["status"] == "approved"


def test_empresa_com_vinte_pagamentos_em_5_min_pede_facial():
    corpos = _sequencia(Pagador(pj=True), [5000] * 20, timedelta(seconds=10))

    assert pontos(corpos[-1], "VELOCITY") == 40
    assert corpos[-1]["metadata"]["authentication"]["level"] == "facial"


def test_replay_nao_conta_como_tentativa():
    pagador, recebedor, base = Pagador(), Recebedor(), nova_base()
    repetido = pix(pagador, recebedor, 5000, base.isoformat())
    for _ in range(6):
        AntifraudApi.post(repetido)

    corpo = analisa(pix(pagador, recebedor, 5000, (base + timedelta(seconds=30)).isoformat()))

    assert not disparou(corpo, "VELOCITY")


def test_tentativas_rejeitadas_tambem_contam_na_velocity():
    pagador, base = Pagador(), nova_base()
    for indice in range(4):
        corpo = analisa(pix(pagador, Recebedor(), 15000000, (base + timedelta(seconds=indice * 10)).isoformat()))
        assert corpo["status"] == "rejected"

    quinto = analisa(pix(pagador, Recebedor(), 5000, (base + timedelta(seconds=50)).isoformat()))

    assert pontos(quinto, "VELOCITY") == 40


def test_janela_usa_a_transaction_date():
    corpos = _sequencia(Pagador(), [5000] * 5, timedelta(minutes=10))

    assert not any(disparou(corpo, "VELOCITY") for corpo in corpos)


def test_2fa_nao_entra_no_montante_aprovado():
    pagador, base = Pagador(), nova_base()
    desafio = analisa(pix(pagador, Recebedor(), 4500000, base.isoformat()))
    assert desafio["status"] == "two_factor_required"

    corpo = analisa(pix(pagador, Recebedor(), 900000, (base + timedelta(minutes=10)).isoformat()))

    assert not disparou(corpo, "MONTANTE_24H")


def test_montante_24h_soma_os_aprovados_e_o_atual():
    pagador, recebedor = Pagador(), Recebedor()
    corpos = _sequencia(pagador, [490000] * 11, timedelta(hours=1), recebedor=recebedor)

    assert all(corpo["status"] == "approved" for corpo in corpos[1:10])
    assert pontos(corpos[-1], "MONTANTE_24H") == 40
    assert not disparou(corpos[-2], "MONTANTE_24H")


def test_fatiamento_dispara_na_quarta_operacao():
    corpos = _sequencia(Pagador(), [290000] * 4, timedelta(minutes=10), recebedor=Recebedor())

    assert not disparou(corpos[2], "FATIAMENTO")
    assert pontos(corpos[3], "FATIAMENTO") == 40
    assert corpos[3]["status"] == "two_factor_required"


def test_fatiamento_abaixo_do_valor_nao_dispara():
    corpos = _sequencia(Pagador(), [100000] * 5, timedelta(minutes=10), recebedor=Recebedor())

    assert not disparou(corpos[-1], "FATIAMENTO")


def test_uma_reducao_depois_de_2fa_soma_30():
    corpos = _sequencia(Pagador(), [3000000, 1900000], timedelta(minutes=3))

    assert corpos[0]["status"] == "two_factor_required"
    assert pontos(corpos[1], "SONDAGEM_DE_LIMITE") == 30


def test_duas_reducoes_sucessivas_pedem_facial_document():
    corpos = _sequencia(Pagador(), [3000000, 2500000, 1900000], timedelta(minutes=3))

    sondagem = regra(corpos[2], "SONDAGEM_DE_LIMITE")
    assert sondagem["raw_points"] == 50
    assert sondagem["authentication_floor"] == "facial_document"
    assert corpos[2]["metadata"]["authentication"]["level"] == "facial_document"


def test_mesmo_valor_depois_de_2fa_nao_e_sondagem():
    corpos = _sequencia(Pagador(), [3000000, 3000000], timedelta(minutes=3))

    assert not disparou(corpos[1], "SONDAGEM_DE_LIMITE")


def test_pix_pequeno_para_outro_destino_depois_de_2fa_nao_e_sondagem():
    # O carro pediu 2FA; o almoco, dez minutos depois, e outro pagamento.
    base, pagador = nova_base(), Pagador()
    carro = analisa(pix(pagador, Recebedor(pj=True), 2500000, base.isoformat()))
    assert carro["status"] == "two_factor_required"

    almoco = analisa(pix(pagador, Recebedor(pj=True), 3000, (base + timedelta(minutes=10)).isoformat()))

    assert not disparou(almoco, "SONDAGEM_DE_LIMITE")


def test_valor_proximo_para_outro_destino_ainda_e_sondagem():
    # Trocar de conta e continuar baixando perto do valor recusado continua
    # sendo sondar: 25 mil, depois 19 mil para outra conta.
    base, pagador = nova_base(), Pagador()
    analisa(pix(pagador, Recebedor(), 2500000, base.isoformat()))

    corpo = analisa(pix(pagador, Recebedor(), 1900000, (base + timedelta(minutes=3)).isoformat()))

    assert disparou(corpo, "SONDAGEM_DE_LIMITE")


def test_reducao_depois_de_15_minutos_nao_e_sondagem():
    corpos = _sequencia(Pagador(), [3000000, 1900000], timedelta(minutes=20))

    assert not disparou(corpos[1], "SONDAGEM_DE_LIMITE")


def test_duas_reducoes_espacadas_de_40_min_pedem_facial_document():
    # Quem espera 40 min entre uma tentativa e outra continua sondando: na
    # janela longa, so a faixa de duas reducoes vale.
    corpos = _sequencia(Pagador(), [2500000, 1900000, 1400000], timedelta(minutes=40))

    assert not disparou(corpos[1], "SONDAGEM_DE_LIMITE")
    sondagem = regra(corpos[2], "SONDAGEM_DE_LIMITE")
    assert sondagem["raw_points"] == 50
    assert sondagem["authentication_floor"] == "facial_document"


def test_datas_recuando_nao_escondem_a_rajada():
    # Seis Pix mandados agora, com as datas recuando uma hora cada: cada um
    # "acontece" antes dos anteriores, e nenhuma janela via os outros.
    # Antes: approved com 0 pontos. Com as datas reais, a VELOCITY pegaria.
    base, pagador = nova_base(), Pagador()
    corpos = [analisa(pix(pagador, Recebedor(), 5000, (base - timedelta(hours=i)).isoformat())) for i in range(6)]

    assert not disparou(corpos[0], "DATA_RETROATIVA")
    ultimo = corpos[-1]
    assert disparou(ultimo, "DATA_RETROATIVA")
    assert ultimo["status"] == "two_factor_required"
    assert ultimo["metadata"]["authentication"]["level"] == "facial_document"
    assert ultimo["metadata"]["scenario"] == "data_fora_de_ordem"


def test_data_pouco_fora_de_ordem_nao_e_retroativa():
    # A organizacao avisou: as datas podem chegar pouco fora de ordem.
    base, pagador = nova_base(), Pagador()
    analisa(pix(pagador, Recebedor(), 5000, base.isoformat()))

    corpo = analisa(pix(pagador, Recebedor(), 5000, (base - timedelta(minutes=3)).isoformat()))

    assert not disparou(corpo, "DATA_RETROATIVA")


def test_um_pix_sozinho_acima_de_50_mil_nao_e_montante():
    corpo = analisa(pix(Pagador(), Recebedor(), 6000000, nova_base().isoformat()))

    assert not disparou(corpo, "MONTANTE_24H")
    assert disparou(corpo, "LIMITE_POR_PIX")
