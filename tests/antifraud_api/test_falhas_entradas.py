"""Entradas que passam no schema e mesmo assim derrubam ou enganam o motor.

Um pedido que o schema aceita nunca pode virar 500: ou o motor analisa, ou
recusa com 4xx dizendo o que esta errado. E duas formas do mesmo dado (o
mesmo IP, o mesmo valor) tem que dar a mesma analise, senao a forma vira
um jeito de escapar das regras.
"""

import pytest

from tests.utils.pix import AntifraudApi, Pagador, Recebedor, analisa, nova_base, pix, pix_normal


def _nunca_500(resposta):
    assert resposta.status_code < 500, f"{resposta.status_code}: {resposta.text[:300]}"


@pytest.mark.parametrize("data", ["0001-01-01T00:00:00+00:00", "0001-01-01T00:00:00-03:00", "0001-01-02T12:00:00+14:00"])
def test_pix_no_ano_1_nao_derruba_a_api(data):
    # O pattern aceita qualquer ano. As janelas do motor recuam dias a partir
    # da data, e antes do ano 1 o datetime do Python nao existe.
    payload = pix_normal(data=data)
    payload["source_account"]["opening_date"] = data
    payload["destination_account"]["opening_date"] = data

    _nunca_500(AntifraudApi.post(payload))


@pytest.mark.parametrize("ip", ["fe80::1%eth0", "fe80::1%1"])
def test_ipv6_com_escopo_nao_derruba_a_api(ip):
    # O ipaddress aceita o escopo ("%eth0") no endereco, mas nao na rede /48.
    _nunca_500(AntifraudApi.post(pix_normal(ip=ip)))


@pytest.mark.parametrize("data", ["0001-01-01T00:00:00+00:00", "9999-12-31T23:59:59+00:00"])
def test_nao_fui_eu_com_data_extrema_nao_derruba_a_api(data):
    # A cautelar soma 24 horas e o aparelho 30 dias ao event_date, e a busca
    # de denunciantes recua 30 dias: nas pontas do calendario, estoura.
    payload = pix(Pagador(), Recebedor(), 2500000, nova_base().isoformat())
    assert analisa(payload)["status"] == "two_factor_required"

    _nunca_500(AntifraudApi.patch(payload["id"], {"challenge_result": "reproved_by_client", "event_date": data}))


def test_ipv4_escrito_como_ipv6_e_localizado_como_o_ipv4():
    # "::ffff:198.51.100.7" e o mesmo endereco que "198.51.100.7", na forma
    # que um balanceador IPv6 costuma repassar. Se o motor perde a
    # localizacao, as regras de geografia (IP longe do GPS, viagem
    # impossivel) deixam de enxergar quem chega por essa forma.
    ipv4 = analisa(pix_normal(ip="198.51.100.7"))
    mapeado = analisa(pix_normal(ip="::ffff:198.51.100.7"))

    assert ipv4["metadata"]["signals"]["ip_location_source"] == "mock"
    assert mapeado["metadata"]["signals"]["ip_location_source"] == ipv4["metadata"]["signals"]["ip_location_source"]


def test_valor_com_ponto_zero_e_o_mesmo_pix_no_replay():
    # 15000 e 15000.0 sao o mesmo numero em JSON, e o schema aceita os dois.
    # Ou o motor recusa o 15000.0 (400), ou o replay com 15000 e o mesmo Pix.
    payload = pix_normal(valor=15000)
    com_ponto = dict(payload, amount=15000.0)

    primeira = AntifraudApi.post(com_ponto)
    if primeira.status_code == 400:
        return
    assert primeira.status_code == 201, primeira.text

    replay = AntifraudApi.post(payload)
    assert replay.status_code == 200, replay.text
    assert replay.json()["key"] == primeira.json()["key"]


@pytest.mark.parametrize("gps", [(90, 180), (-90, -180), (0, 0)])
def test_gps_nas_pontas_do_mapa_e_analisado(gps):
    resposta = AntifraudApi.post(pix_normal(gps=gps))

    assert resposta.status_code == 201, resposta.text


def test_valor_maximo_do_schema_e_analisado():
    resposta = AntifraudApi.post(pix_normal(valor=999999999999))

    assert resposta.status_code == 201, resposta.text
    assert resposta.json()["status"] != "approved"


@pytest.mark.parametrize("aparelho", ["dvc-ç-ã-日本", "x" * 64, "dvc com espaço", "'; DROP TABLE pix_analysis; --"])
def test_aparelho_com_caracteres_estranhos_e_analisado(aparelho):
    resposta = AntifraudApi.post(pix_normal(aparelho=aparelho))

    assert resposta.status_code == 201, resposta.text
