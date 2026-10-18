"""O limite que o proprio cliente escolhe.

Quem aplica o limite e a plataforma (BaaS), e nao o motor. Aqui ficam o
registro dos pedidos (reduzir vale na hora, aumentar so 24 horas depois) e
o AUMENTO_PENDENTE, que usa esse historico como sinal de risco."""
from datetime import timedelta

from tests.utils.pix import AntifraudApi, Pagador, Recebedor, analisa, disparou, nova_base, pix, pontos


def _limite(pagador, valor, quando):
    corpo = pagador.conta_json()
    corpo.update({"amount": valor, "requested_at": quando.isoformat()})
    return AntifraudApi.put_limit(corpo)


def test_primeiro_limite_vale_na_hora():
    pagador, base = Pagador(), nova_base()

    resposta = _limite(pagador, 200000, base)

    assert resposta.status_code == 200
    assert resposta.json()["change_type"] == "initial"
    assert resposta.json()["effective_from"] == resposta.json()["requested_at"]


def test_reducao_vale_na_hora():
    pagador, base = Pagador(), nova_base()
    _limite(pagador, 500000, base)

    resposta = _limite(pagador, 100000, base + timedelta(hours=1))

    assert resposta.json()["change_type"] == "decrease"
    assert resposta.json()["effective_from"] == resposta.json()["requested_at"]


def test_aumento_so_vale_depois_de_24h():
    pagador, base = Pagador(), nova_base()
    _limite(pagador, 200000, base)

    resposta = _limite(pagador, 2000000, base + timedelta(hours=1))

    assert resposta.json()["change_type"] == "increase"
    assert resposta.json()["effective_from"] != resposta.json()["requested_at"]


def test_pix_acima_do_limite_nao_e_bloqueado_pelo_motor():
    # O limite do cliente e da plataforma: o motor nao recusa por ele.
    pagador, base = Pagador(), nova_base()
    _limite(pagador, 200000, base)

    corpo = analisa(pix(pagador, Recebedor(), 300000, (base + timedelta(minutes=5)).isoformat()))

    assert corpo["status"] == "approved"


def test_pix_alto_com_aumento_pendente_soma_40():
    pagador, base = Pagador(), nova_base()
    _limite(pagador, 200000, base)
    _limite(pagador, 2000000, base + timedelta(hours=1))

    corpo = analisa(pix(pagador, Recebedor(), 150000, (base + timedelta(hours=2)).isoformat()))

    assert pontos(corpo, "AUMENTO_PENDENTE") == 40


def test_reducao_depois_de_um_aumento_pendente_cancela_o_aumento():
    # O pedido mais recente e a reducao: nao ha mais aumento pendente.
    pagador, base = Pagador(), nova_base()
    _limite(pagador, 200000, base)
    _limite(pagador, 2000000, base + timedelta(hours=1))
    _limite(pagador, 100000, base + timedelta(hours=2))

    corpo = analisa(pix(pagador, Recebedor(), 150000, (base + timedelta(hours=3)).isoformat()))

    assert not disparou(corpo, "AUMENTO_PENDENTE")


def test_limite_zero_da_400():
    resposta = _limite(Pagador(), 0, nova_base())

    assert resposta.status_code == 400
    assert resposta.json()["code"] == "QIT000001"


def test_limite_com_data_no_futuro_da_422():
    from tests.utils.pix import agora_sp

    resposta = _limite(Pagador(), 100000, agora_sp() + timedelta(hours=1))

    assert resposta.status_code == 422
