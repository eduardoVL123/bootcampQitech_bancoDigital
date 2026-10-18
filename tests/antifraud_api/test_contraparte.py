"""Origem, destino e confianca: idade das contas, primeiro pagamento,
conta reativada e o destino que ja e familiar (o aluguel)."""
from datetime import timedelta

from tests.utils.pix import (
    AntifraudDb, Pagador, Recebedor, analisa, disparou, historico, nova_base, payload_do_documento, pix, pontos,
    regra,
)


def test_payload_do_documento_da_45_e_pede_facial():
    AntifraudDb.reset()

    corpo = analisa(payload_do_documento())

    assert corpo["status"] == "two_factor_required"
    assert corpo["metadata"]["risk_score"] == 45
    assert corpo["metadata"]["authentication"]["level"] == "facial"
    assert pontos(corpo, "NOTURNO") == 25
    assert pontos(corpo, "DESTINO_NOVO") == 20


def test_destino_novo_e_contraparte_inedita_contam_uma_vez():
    hoje = nova_base()
    recebedor = Recebedor(aberta_em=hoje - timedelta(days=10))

    corpo = analisa(pix(Pagador(), recebedor, 150000, hoje.isoformat()))

    assert regra(corpo, "CONTRAPARTE_INEDITA")["correlated"] is True
    assert corpo["metadata"]["risk_axes"]["destino"] == 20


def test_conta_destino_de_menos_de_1_dia_soma_30():
    hoje = nova_base()
    recebedor = Recebedor(aberta_em=hoje - timedelta(hours=5))

    corpo = analisa(pix(Pagador(), recebedor, 5000, hoje.isoformat()))

    assert pontos(corpo, "DESTINO_NOVO") == 30


def test_conta_destino_antiga_nao_dispara():
    corpo = analisa(pix(Pagador(), Recebedor(), 5000, nova_base().isoformat()))

    assert not disparou(corpo, "DESTINO_NOVO")


def test_primeiro_pix_acima_de_1000_para_documento_novo_soma_15():
    corpo = analisa(pix(Pagador(), Recebedor(), 150000, nova_base().isoformat()))

    assert pontos(corpo, "CONTRAPARTE_INEDITA") == 15


def test_contraparte_inedita_nao_vale_para_o_proprio_titular():
    pagador = Pagador()

    corpo = analisa(pix(pagador, Recebedor(documento=pagador.documento), 150000, nova_base().isoformat()))

    assert not disparou(corpo, "CONTRAPARTE_INEDITA")


def test_conta_origem_nova_soma_25():
    hoje = nova_base()
    pagador = Pagador(aberta_em=hoje - timedelta(hours=10))

    corpo = analisa(pix(pagador, Recebedor(), 150000, hoje.isoformat()))

    assert pontos(corpo, "ORIGEM_NOVA") == 25


def test_conta_parada_ha_90_dias_que_volta_com_rajada_soma_30():
    hoje = nova_base()
    pagador = Pagador(aberta_em=hoje - timedelta(days=400))
    analisa(pix(pagador, Recebedor(), 5000, (hoje - timedelta(days=90)).isoformat()))

    corpos = [analisa(pix(pagador, Recebedor(), 5000, (hoje + timedelta(minutes=10 * i)).isoformat()))
              for i in range(3)]

    assert not disparou(corpos[1], "CONTA_REATIVADA")
    assert pontos(corpos[2], "CONTA_REATIVADA") == 30


def test_conta_parada_que_volta_devagar_pede_facial_no_dia_da_volta():
    # Dois Pix por hora ficam abaixo da rajada de 3 em 1 h. A volta e o dia
    # inteiro: o terceiro do dia ja pede a facial.
    hoje = nova_base().replace(hour=9, minute=0, second=0)
    pagador, recebedor = Pagador(aberta_em=hoje - timedelta(days=400)), Recebedor()
    analisa(pix(pagador, Recebedor(), 5000, (hoje - timedelta(days=90)).isoformat()))

    corpos = [analisa(pix(pagador, recebedor, 5000, (hoje + timedelta(minutes=31 * i)).isoformat()))
              for i in range(3)]

    assert not disparou(corpos[1], "CONTA_REATIVADA")
    assert pontos(corpos[2], "CONTA_REATIVADA") == 30
    assert corpos[2]["status"] == "two_factor_required"


def test_conta_parada_que_volta_com_mais_de_2_mil_no_dia_pede_facial():
    hoje = nova_base().replace(hour=9, minute=0, second=0)
    pagador, recebedor = Pagador(aberta_em=hoje - timedelta(days=400)), Recebedor()
    analisa(pix(pagador, Recebedor(), 5000, (hoje - timedelta(days=90)).isoformat()))

    primeiro = analisa(pix(pagador, recebedor, 120000, hoje.isoformat()))
    segundo = analisa(pix(pagador, recebedor, 90000, (hoje + timedelta(hours=3)).isoformat()))

    assert not disparou(primeiro, "CONTA_REATIVADA")
    assert disparou(segundo, "CONTA_REATIVADA")
    assert segundo["status"] == "two_factor_required"


def test_primeiro_contato_com_o_motor_nao_e_reativacao():
    hoje = nova_base()
    pagador = Pagador(aberta_em=hoje - timedelta(days=400))

    corpos = [analisa(pix(pagador, Recebedor(), 5000, (hoje + timedelta(minutes=10 * i)).isoformat()))
              for i in range(3)]

    assert not disparou(corpos[2], "CONTA_REATIVADA")


def test_conta_ativa_nao_e_reativada():
    hoje = nova_base()
    pagador = Pagador(aberta_em=hoje - timedelta(days=400))
    analisa(pix(pagador, Recebedor(), 5000, (hoje - timedelta(days=5)).isoformat()))

    corpo = analisa(pix(pagador, Recebedor(), 600000, hoje.isoformat()))

    assert not disparou(corpo, "CONTA_REATIVADA")


def test_aluguel_recorrente_e_aprovado():
    pagador, senhorio, hoje = Pagador(), Recebedor(), nova_base()
    historico(pagador, [250000] * 5, hoje - timedelta(days=150), timedelta(days=30), recebedor=senhorio)

    corpo = analisa(pix(pagador, senhorio, 250000, hoje.isoformat()))

    assert corpo["status"] == "approved"
    assert disparou(corpo, "DESTINO_CONFIAVEL")
    assert not disparou(corpo, "PERFIL")


def test_destino_familiar_desconta_10_do_perfil():
    # Tres pagamentos em 10 dias tornam o destino familiar (pede 7 dias), mas
    # nao bastam para a referencia do par (pede 14), entao o perfil compara
    # com os gastos pequenos do dia a dia e dispara. O redutor tira 10.
    pagador, senhorio, hoje = Pagador(), Recebedor(), nova_base()
    historico(pagador, [250000] * 3, hoje - timedelta(days=20), timedelta(days=5), recebedor=senhorio)
    historico(pagador, [5000] * 10, hoje - timedelta(days=8), timedelta(hours=12), recebedores_novos=True)

    corpo = analisa(pix(pagador, senhorio, 250000, hoje.isoformat()))

    assert pontos(corpo, "PERFIL") == 50
    assert pontos(corpo, "DESTINO_CONFIAVEL") == -10
    outras = pontos(corpo, "MONTANTE_DIARIO_ATIPICO")
    assert corpo["metadata"]["risk_axes"]["movimentacao"] == 50 - 10 + outras


def test_um_pix_pequeno_nao_torna_o_destino_confiavel():
    pagador, destino, hoje = Pagador(), Recebedor(), nova_base()
    analisa(pix(pagador, destino, 1000, (hoje - timedelta(days=10)).isoformat()))

    corpo = analisa(pix(pagador, destino, 250000, hoje.isoformat()))

    assert not disparou(corpo, "DESTINO_CONFIAVEL")


def test_valor_acima_do_maior_ja_pago_nao_ganha_desconto():
    pagador, destino, hoje = Pagador(), Recebedor(), nova_base()
    historico(pagador, [1000] * 3, hoje - timedelta(days=20), timedelta(days=5), recebedor=destino)

    corpo = analisa(pix(pagador, destino, 250000, hoje.isoformat()))

    assert not disparou(corpo, "DESTINO_CONFIAVEL")
