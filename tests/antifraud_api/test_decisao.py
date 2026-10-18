"""O motor de decisao: faixas, eixos, familias, redutores, bloqueios e pisos.

As regras usadas aqui sao as que nao dependem de historico (limite,
noturno, geolocalizacao ausente e mesma titularidade). Cada teste cria
pessoas novas, entao nenhum historico de outro teste entra na conta.
"""
from datetime import datetime, timedelta, timezone

from tests.utils.pix import (
    AntifraudApi, Pagador, Recebedor, analisa, disparou, nova_base, pix, pontos, regra,
)


def _dia(hora: int, minuto: int = 0) -> datetime:
    return nova_base().replace(hour=hora, minute=minuto)


def test_valor_alto_pede_facial():
    corpo = analisa(pix(Pagador(), Recebedor(), 2500000, _dia(14).isoformat()))

    assert pontos(corpo, "LIMITE_POR_PIX") == 40
    assert corpo["status"] == "two_factor_required"
    assert corpo["metadata"]["authentication"] == {
        "level": "facial",
        "required_checks": ["facial"],
        "execution": "required_not_executed",
    }


def test_valor_abaixo_do_corte_nao_dispara_o_limite():
    corpo = analisa(pix(Pagador(), Recebedor(), 1999999, _dia(14).isoformat()))

    assert not disparou(corpo, "LIMITE_POR_PIX")


def test_acima_do_teto_rejeita_por_bloqueio():
    corpo = analisa(pix(Pagador(), Recebedor(), 15000000, _dia(14).isoformat()))

    assert corpo["status"] == "rejected"
    assert regra(corpo, "LIMITE_POR_PIX")["hard_block"] is True
    assert corpo["metadata"]["scenario"] == "restricao_por_limite"
    assert corpo["metadata"]["reason"] == "LIMITE_POR_PIX"
    assert corpo["metadata"]["authentication"]["level"] == "none"


def test_noturno_pf_para_pf_soma_25():
    corpo = analisa(pix(Pagador(), Recebedor(), 150000, _dia(22, 15).isoformat()))

    assert pontos(corpo, "NOTURNO") == 25
    assert regra(corpo, "NOTURNO")["axis"] == "movimentacao"


def test_noturno_para_cnpj_nao_dispara():
    corpo = analisa(pix(Pagador(), Recebedor(pj=True), 150000, _dia(22, 15).isoformat()))

    assert not disparou(corpo, "NOTURNO")


def test_noturno_para_cnpj_com_conta_nova_soma_25():
    # A conta laranja aberta como MEI: e PJ, mas a conta tem 10 dias.
    noite = _dia(22, 15)
    corpo = analisa(pix(Pagador(), Recebedor(pj=True, aberta_em=noite - timedelta(days=10)), 150000, noite.isoformat()))

    assert pontos(corpo, "NOTURNO") == 25


def test_noturno_com_valor_pequeno_nao_dispara():
    corpo = analisa(pix(Pagador(), Recebedor(), 5000, _dia(23).isoformat()))

    assert not disparou(corpo, "NOTURNO")


def test_noturno_entre_pessoas_com_o_mesmo_documento_nao_dispara():
    pagador = Pagador()
    corpo = analisa(pix(pagador, Recebedor(documento=pagador.documento), 150000, _dia(22).isoformat()))

    assert not disparou(corpo, "NOTURNO")


def test_mesmo_instante_com_offsets_diferentes_da_o_mesmo_horario():
    instante = _dia(22, 15)
    em_utc = instante.astimezone(timezone.utc)

    sao_paulo = analisa(pix(Pagador(), Recebedor(), 150000, instante.isoformat()))
    utc = analisa(pix(Pagador(), Recebedor(), 150000, em_utc.isoformat()))

    assert disparou(sao_paulo, "NOTURNO")
    assert disparou(utc, "NOTURNO")


def test_horario_e_o_de_sao_paulo_e_nao_o_do_offset():
    # 22:15 em UTC sao 19:15 em Sao Paulo: ainda nao e noite.
    dia = nova_base()
    data = f"{dia.date().isoformat()}T22:15:00+00:00"

    corpo = analisa(pix(Pagador(), Recebedor(), 150000, data))

    assert not disparou(corpo, "NOTURNO")


def test_sem_gps_pelo_app_soma_20_e_aprova():
    corpo = analisa(pix(Pagador(canal="app"), Recebedor(), 15000, _dia(14).isoformat(), gps=None))

    assert pontos(corpo, "GEO_AUSENTE") == 20
    assert corpo["status"] == "approved"


def test_sem_gps_pela_web_soma_20():
    corpo = analisa(pix(Pagador(canal="web"), Recebedor(), 15000, _dia(14).isoformat(), gps=None))

    assert pontos(corpo, "GEO_AUSENTE") == 20


def test_sem_gps_pela_api_nao_soma():
    corpo = analisa(pix(Pagador(canal="api"), Recebedor(), 15000, _dia(14).isoformat(), gps=None))

    assert pontos(corpo, "GEO_AUSENTE") == 0


def test_quem_nunca_manda_gps_nao_e_penalizado_pela_ausencia():
    # Permissao de localizacao negada desde sempre: a ausencia e o normal
    # deste titular, e nao baixa o corte de 2FA dele em todo Pix.
    pagador, hoje = Pagador(canal="app", gps=None), _dia(14)
    for dias in (9, 6, 3):
        analisa(pix(pagador, Recebedor(), 15000, (hoje - timedelta(days=dias)).isoformat()))

    corpo = analisa(pix(pagador, Recebedor(), 15000, hoje.isoformat()))

    assert not disparou(corpo, "GEO_AUSENTE")


def test_quem_costuma_mandar_gps_e_chega_sem_ele_soma_20():
    pagador, hoje = Pagador(canal="app"), _dia(14)
    for dias in (9, 6, 3):
        analisa(pix(pagador, Recebedor(), 15000, (hoje - timedelta(days=dias)).isoformat()))

    corpo = analisa(pix(pagador, Recebedor(), 15000, hoje.isoformat(), gps=None))

    assert pontos(corpo, "GEO_AUSENTE") == 20


def test_com_gps_nao_dispara():
    corpo = analisa(pix(Pagador(), Recebedor(), 15000, _dia(14).isoformat()))

    assert not disparou(corpo, "GEO_AUSENTE")


def test_alto_noturno_e_sem_gps_rejeita_por_convergencia_de_eixos():
    # limite 40 + noturno 25 (movimentacao 65) e sem GPS 20 (acesso 20):
    # 80 ou mais, com dois eixos de pelo menos 20 pontos.
    corpo = analisa(pix(Pagador(), Recebedor(), 2500000, _dia(23).isoformat(), gps=None))

    assert corpo["metadata"]["risk_axes"]["movimentacao"] >= 65
    assert corpo["metadata"]["risk_axes"]["acesso"] >= 20
    assert corpo["status"] == "rejected"


def test_alto_e_noturno_num_eixo_so_pede_facial_document():
    # Os mesmos 65 em movimentacao, com GPS: so um eixo passa de 20, entao
    # nao rejeita, e pede a verificacao reforcada.
    corpo = analisa(pix(Pagador(), Recebedor(pj=False), 2500000, _dia(23).isoformat()))

    assert corpo["metadata"]["risk_axes"]["acesso"] < 20
    assert corpo["status"] == "two_factor_required"
    assert corpo["metadata"]["authentication"]["level"] == "facial_document"
    assert corpo["metadata"]["authentication"]["required_checks"] == ["facial", "document"]


def test_mesma_titularidade_desconta_so_10_da_familia_de_valor():
    pagador = Pagador()
    corpo = analisa(pix(pagador, Recebedor(documento=pagador.documento), 2500000, _dia(14).isoformat()))

    assert pontos(corpo, "MESMA_TITULARIDADE") == -10
    assert corpo["metadata"]["risk_axes"]["movimentacao"] == 30


def test_redutor_nao_desfaz_bloqueio():
    pagador = Pagador()
    corpo = analisa(pix(pagador, Recebedor(documento=pagador.documento), 15000000, _dia(14).isoformat()))

    assert corpo["status"] == "rejected"


def test_regras_ficam_no_get_iguais_ao_post():
    payload = pix(Pagador(), Recebedor(), 2500000, _dia(22).isoformat(), gps=None)
    criado = analisa(payload)

    lido = AntifraudApi.get(payload["id"]).json()

    assert lido["metadata"]["rules"] == criado["metadata"]["rules"]
    assert lido["metadata"]["risk_score"] == criado["metadata"]["risk_score"]
