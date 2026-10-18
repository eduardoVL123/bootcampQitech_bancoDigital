"""Reputacao: o mock externo (no formato do destination_statistics da QI)
e a lista interna, que o proprio motor nunca alimenta."""
from datetime import datetime, timedelta

from tests.utils.pix import (
    APARELHO_NA_WATCHLIST, RECEBEDOR_ALERTA, RECEBEDOR_ALERTA_VENCIDO, RECEBEDOR_MARCACAO_CRITICA,
    RECEBEDOR_MARCACAO_UM_DENUNCIANTE, RECEBEDOR_NA_WATCHLIST, RECEBEDOR_VITIMA, SAO_PAULO, AntifraudApi, Pagador,
    Recebedor, analisa, disparou, historico, nega, nova_base, pix, pontos, regra,
)


def test_marcacao_critica_rejeita_mesmo_com_valor_baixo():
    corpo = analisa(pix(Pagador(), Recebedor(documento=RECEBEDOR_MARCACAO_CRITICA), 5000, nova_base().isoformat()))

    assert corpo["status"] == "rejected"
    assert corpo["metadata"]["scenario"] == "risco_critico_do_recebedor"
    assert corpo["metadata"]["reputation"]["is_mock"] is True
    assert corpo["metadata"]["reputation"]["signal"] == "active_fraud_marker"


def test_alerta_soma_40():
    corpo = analisa(pix(Pagador(), Recebedor(documento=RECEBEDOR_ALERTA), 5000, nova_base().isoformat()))

    assert pontos(corpo, "REPUTACAO_EXTERNA") == 40
    assert corpo["metadata"]["reputation"]["signal"] == "risk_alert"


def test_alerta_vencido_nao_conta():
    corpo = analisa(pix(Pagador(), Recebedor(documento=RECEBEDOR_ALERTA_VENCIDO), 5000, nova_base().isoformat()))

    assert not disparou(corpo, "REPUTACAO_EXTERNA")
    assert corpo["metadata"]["reputation"]["signal"] == "expired"


def test_vitima_nao_e_tratada_como_fraudador():
    corpo = analisa(pix(Pagador(), Recebedor(documento=RECEBEDOR_VITIMA), 5000, nova_base().isoformat()))

    assert not disparou(corpo, "REPUTACAO_EXTERNA")
    assert corpo["metadata"]["reputation"]["entity_role"] == "victim"


def test_conta_nova_em_cpf_com_fraude_de_cadastro_soma_40():
    # A pessoa e vitima (a conta antiga dela continua limpa, teste de cima),
    # mas a conta aberta ha 10 dias nesse CPF pode ser a do fraudador.
    hoje = nova_base()
    corpo = analisa(pix(Pagador(), Recebedor(documento=RECEBEDOR_VITIMA, aberta_em=hoje - timedelta(days=10)), 5000,
                        hoje.isoformat()))

    assert pontos(corpo, "REPUTACAO_EXTERNA") == 40
    assert corpo["metadata"]["reputation"]["signal"] == "application_fraud_new_account"


def test_conta_segura_no_proprio_cpf_com_fraude_de_cadastro_rejeita():
    # O golpe da "conta segura": o golpista abre uma conta no nome da vitima
    # e manda ela "proteger" o saldo ali. Antes: 30 pontos e approved.
    hoje = nova_base()
    vitima = Pagador(documento=RECEBEDOR_VITIMA)
    conta_do_golpista = Recebedor(documento=RECEBEDOR_VITIMA, aberta_em=hoje - timedelta(hours=3),
                                  participante="12345678")

    corpo = analisa(pix(vitima, conta_do_golpista, 1500000, hoje.isoformat()))

    assert corpo["status"] == "rejected"
    assert corpo["metadata"]["scenario"] == "risco_critico_do_recebedor"


def test_documento_sem_registro_no_mock_e_not_found():
    corpo = analisa(pix(Pagador(), Recebedor(), 5000, nova_base().isoformat()))

    assert corpo["metadata"]["reputation"]["signal"] == "not_found"


def test_uma_marcacao_confirmada_com_um_denunciante_rejeita():
    # Marcacao de laranja ja e fraude confirmada pela instituicao do
    # recebedor; o segundo denunciante nao muda isso.
    corpo = analisa(pix(Pagador(), Recebedor(documento=RECEBEDOR_MARCACAO_UM_DENUNCIANTE), 5000,
                        nova_base().isoformat()))

    assert corpo["status"] == "rejected"
    assert corpo["metadata"]["reputation"]["signal"] == "active_fraud_marker"


def test_documento_confirmado_na_watchlist_rejeita():
    corpo = analisa(pix(Pagador(), Recebedor(documento=RECEBEDOR_NA_WATCHLIST), 5000, nova_base().isoformat()))

    assert corpo["status"] == "rejected"
    assert regra(corpo, "REPUTACAO_INTERNA")["hard_block"] is True
    assert corpo["metadata"]["reason"] == "REPUTACAO_INTERNA"
    assert corpo["metadata"]["scenario"] == "risco_critico_do_recebedor"


def test_falsa_central_para_conta_confirmada_rejeita_mesmo_com_o_cliente_normal():
    # A vitima paga do celular e do lugar de sempre, um valor do perfil dela:
    # movimentacao e acesso em 0. Antes, 60 pontos so no eixo destino davam
    # 2FA, e a vitima, enganada, passava na facial.
    hoje = nova_base()
    vitima = Pagador()
    historico(vitima, [200000, 250000, 300000, 350000, 400000, 280000, 320000, 260000, 310000, 290000],
              hoje - timedelta(days=12), timedelta(days=1), recebedores_novos=True)
    golpista = Recebedor(documento=RECEBEDOR_NA_WATCHLIST, aberta_em=hoje - timedelta(days=3))

    corpo = analisa(pix(vitima, golpista, 300000, hoje.isoformat()))

    assert corpo["metadata"]["risk_axes"]["movimentacao"] == 0
    assert corpo["metadata"]["risk_axes"]["acesso"] == 0
    assert corpo["status"] == "rejected"


def test_aparelho_na_watchlist_soma_40():
    corpo = analisa(pix(Pagador(), Recebedor(), 5000, nova_base().isoformat(), aparelho=APARELHO_NA_WATCHLIST))

    assert pontos(corpo, "REPUTACAO_INTERNA") == 40


def test_rejeicao_do_motor_nao_alimenta_a_watchlist():
    hoje, destino = nova_base(), Recebedor()
    assert analisa(pix(Pagador(), destino, 15000000, hoje.isoformat()))["status"] == "rejected"

    corpo = analisa(pix(Pagador(), destino, 5000, (hoje + timedelta(hours=1)).isoformat()))

    assert not disparou(corpo, "REPUTACAO_INTERNA")


def test_titular_que_nega_o_desafio_marca_o_destino():
    hoje, destino = nova_base(), Recebedor()
    payload = pix(Pagador(), destino, 2500000, hoje.isoformat())
    assert analisa(payload)["status"] == "two_factor_required"
    AntifraudApi.patch(payload["id"], {"challenge_result": "reproved_by_client",
                                       "event_date": (hoje + timedelta(minutes=2)).isoformat()})

    corpo = analisa(pix(Pagador(), destino, 5000, (hoje + timedelta(hours=1)).isoformat()))

    assert pontos(corpo, "REPUTACAO_INTERNA") == 40
    assert regra(corpo, "REPUTACAO_INTERNA")["creator"] == "client"


def test_cautelar_de_um_titular_so_vence_em_24_horas():
    hoje, destino = nova_base(), Recebedor()
    nega(Pagador(), destino, 2500000, hoje)

    corpo = analisa(pix(Pagador(), destino, 5000, (hoje + timedelta(hours=25)).isoformat()))

    assert not disparou(corpo, "REPUTACAO_INTERNA")


def test_dois_titulares_distintos_confirmam_a_fraude_e_o_destino_e_recusado():
    hoje, destino = nova_base(), Recebedor()
    nega(Pagador(), destino, 2500000, hoje)
    # Na cautelar, R$ 500 para o destino ja pede selfie: a segunda vitima tambem recebe o desafio.
    nega(Pagador(), destino, 50000, hoje + timedelta(hours=1))

    corpo = analisa(pix(Pagador(), destino, 5000, (hoje + timedelta(hours=2)).isoformat()))

    assert corpo["status"] == "rejected"
    assert regra(corpo, "REPUTACAO_INTERNA")["hard_block"] is True
    assert regra(corpo, "REPUTACAO_INTERNA")["creator"] == "confirmed"


def test_o_mesmo_titular_reclamando_duas_vezes_nao_confirma():
    hoje, destino, pagador = nova_base(), Recebedor(), Pagador()
    nega(pagador, destino, 2500000, hoje)
    nega(pagador, destino, 50000, hoje + timedelta(hours=1))

    corpo = analisa(pix(Pagador(), destino, 5000, (hoje + timedelta(hours=2)).isoformat()))

    assert corpo["status"] != "rejected"
    assert pontos(corpo, "REPUTACAO_INTERNA") == 40


def test_segunda_denuncia_dias_depois_ainda_confirma():
    # A cautelar da primeira ja venceu, mas a denuncia continua contando: a
    # segunda vitima costuma reclamar dias depois.
    hoje, destino = nova_base(), Recebedor()
    nega(Pagador(), destino, 2500000, hoje)
    nega(Pagador(), destino, 2500000, hoje + timedelta(days=3))

    corpo = analisa(pix(Pagador(), destino, 5000, (hoje + timedelta(days=3, hours=1)).isoformat()))

    assert corpo["status"] == "rejected"


def test_nao_fui_eu_contra_quem_ja_tem_denuncia_externa_confirma():
    # Data fixa, fora da faixa da nova_base: a confirmacao vale 30 dias para
    # este documento do seed, e nao pode vazar para os outros testes.
    hoje = datetime(2020, 6, 3, 14, 0, tzinfo=SAO_PAULO)
    destino = Recebedor(documento=RECEBEDOR_ALERTA)
    nega(Pagador(), destino, 50000, hoje)

    corpo = analisa(pix(Pagador(), destino, 5000, (hoje + timedelta(hours=1)).isoformat()))

    assert corpo["status"] == "rejected"
    assert regra(corpo, "REPUTACAO_INTERNA")["creator"] == "confirmed"


def test_negativa_do_titular_conta_como_restritiva_na_sondagem():
    hoje, pagador = nova_base(), Pagador()
    payload = pix(pagador, Recebedor(), 2500000, hoje.isoformat())
    analisa(payload)
    AntifraudApi.patch(payload["id"], {"challenge_result": "reproved_by_client",
                                       "event_date": (hoje + timedelta(minutes=1)).isoformat()})

    corpo = analisa(pix(pagador, Recebedor(), 1900000, (hoje + timedelta(minutes=3)).isoformat()))

    assert disparou(corpo, "SONDAGEM_DE_LIMITE")
