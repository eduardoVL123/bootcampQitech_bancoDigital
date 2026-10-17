"""O resultado do desafio (2FA), como na API Pix da QI: o cliente informa
depois se confirmou ou negou. A analise original nao muda."""
from datetime import timedelta

from tests.utils.pix import AntifraudApi, Pagador, Recebedor, analisa, disparou, nova_base, pix


def _confirma(pix_id, resultado="approved_by_client", quando=None):
    corpo = {"challenge_result": resultado, "event_date": (quando or nova_base()).isoformat()}
    return AntifraudApi.patch(pix_id, corpo)


def test_confirmar_o_2fa_registra_e_aparece_no_get():
    payload = pix(Pagador(), Recebedor(), 2500000, nova_base().isoformat())
    assert analisa(payload)["status"] == "two_factor_required"

    resposta = _confirma(payload["id"])
    lido = AntifraudApi.get(payload["id"]).json()

    assert resposta.status_code == 200
    assert lido["status"] == "two_factor_required"
    assert lido["metadata"]["challenge"]["result"] == "approved_by_client"


def test_pix_aprovado_nao_aceita_resultado_de_desafio():
    payload = pix(Pagador(), Recebedor(), 5000, nova_base().isoformat())
    analisa(payload)

    resposta = _confirma(payload["id"])

    assert resposta.status_code == 409
    assert resposta.json()["code"] == "QIT006005"


def test_mesmo_resultado_duas_vezes_e_idempotente():
    payload = pix(Pagador(), Recebedor(), 2500000, nova_base().isoformat())
    analisa(payload)
    _confirma(payload["id"])

    resposta = _confirma(payload["id"])

    assert resposta.status_code == 200


def test_resultado_diferente_depois_da_409():
    payload = pix(Pagador(), Recebedor(), 2500000, nova_base().isoformat())
    analisa(payload)
    _confirma(payload["id"])

    resposta = _confirma(payload["id"], "reproved_by_client")

    assert resposta.status_code == 409
    assert resposta.json()["code"] == "QIT006006"


def test_resultado_de_pix_inexistente_da_404():
    resposta = _confirma("pix-que-nao-existe")

    assert resposta.status_code == 404


def test_resultado_invalido_da_400():
    payload = pix(Pagador(), Recebedor(), 2500000, nova_base().isoformat())
    analisa(payload)

    resposta = AntifraudApi.patch(payload["id"], {"challenge_result": "talvez", "event_date": nova_base().isoformat()})

    assert resposta.status_code == 400


def test_2fa_confirmado_conta_como_dinheiro_que_saiu():
    pagador, recebedor, base = Pagador(), Recebedor(), nova_base()
    primeiro = pix(pagador, recebedor, 2500000, base.isoformat())
    analisa(primeiro)
    _confirma(primeiro["id"], quando=base + timedelta(minutes=1))

    segundo = analisa(pix(pagador, recebedor, 3000000, (base + timedelta(hours=1)).isoformat()))

    assert disparou(segundo, "MONTANTE_24H")


def test_2fa_sem_confirmacao_nao_conta():
    pagador, recebedor, base = Pagador(), Recebedor(), nova_base()
    analisa(pix(pagador, recebedor, 2500000, base.isoformat()))

    segundo = analisa(pix(pagador, recebedor, 3000000, (base + timedelta(hours=1)).isoformat()))

    assert not disparou(segundo, "MONTANTE_24H")
