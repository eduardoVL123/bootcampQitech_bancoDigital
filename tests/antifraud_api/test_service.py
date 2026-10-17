"""O servico sobe e protege as rotas com o INTERNAL-TOKEN."""
from tests.utils.pix import AntifraudApi, pix_normal


def test_health_check_responde_sem_token():
    resposta = AntifraudApi.health()

    assert resposta.status_code == 204


def test_rota_sem_internal_token_da_403():
    resposta = AntifraudApi.post(pix_normal(), token=None)

    assert resposta.status_code == 403
    assert resposta.json()["code"] == "QIT000002"


def test_rota_com_internal_token_errado_da_403():
    resposta = AntifraudApi.post(pix_normal(), token="errado")

    assert resposta.status_code == 403
    assert resposta.json()["code"] == "QIT000002"
