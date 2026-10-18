"""POST e GET do Pix: o contrato, a idempotencia e a verificacao de datas."""
import re
from datetime import timedelta

import pytest

from tests.utils.pix import AntifraudApi, agora_sp, mutar, pix_normal

UUID = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")


def test_pix_normal_e_aprovado():
    resposta = AntifraudApi.post(pix_normal())

    assert resposta.status_code == 201
    corpo = resposta.json()
    assert set(corpo) == {"key", "status", "metadata"}
    assert corpo["status"] == "approved"
    assert UUID.match(corpo["key"])
    assert corpo["metadata"]["scenario"] == "sem_alerta_relevante"
    assert corpo["metadata"]["authentication"] == {
        "level": "none",
        "required_checks": [],
        "execution": "not_required",
    }


def test_get_devolve_a_analise_gravada():
    payload = pix_normal()
    criado = AntifraudApi.post(payload).json()

    resposta = AntifraudApi.get(payload["id"])

    assert resposta.status_code == 200
    assert resposta.json() == criado


def test_metadata_registra_as_regras_avaliadas_que_nao_dispararam():
    # O motor nao grava mais uma linha por regra (eram 37 por Pix). O que
    # nao disparou fica so pelo codigo, no metadata: da para saber o que
    # foi avaliado, sem pagar a frase de cada regra em disco.
    payload = pix_normal()
    corpo = AntifraudApi.post(payload).json()

    nao_dispararam = corpo["metadata"]["rules_not_triggered"]
    disparadas = {regra["rule"] for regra in corpo["metadata"]["rules"]}
    assert "LIMITE_POR_PIX" in nao_dispararam
    assert not disparadas & set(nao_dispararam)
    assert AntifraudApi.get(payload["id"]).json()["metadata"]["rules_not_triggered"] == nao_dispararam


def test_limite_do_cliente_nao_e_mais_do_antifraude():
    # O limite que o titular escolhe e do BAS, que o aplica antes de o Pix
    # chegar aqui. A rota saiu junto com LIMITE_DO_CLIENTE e AUMENTO_PENDENTE.
    resposta = AntifraudApi.envia("PUT", "/pix/account_limit", json={})

    assert resposta.status_code == 404


def test_get_de_pix_inexistente_da_404():
    resposta = AntifraudApi.get("pix-que-nao-existe")

    assert resposta.status_code == 404
    assert resposta.json()["code"] == "QIT006001"


def test_mesmo_id_e_mesmo_corpo_devolve_a_original():
    payload = pix_normal()
    primeira = AntifraudApi.post(payload)

    segunda = AntifraudApi.post(payload)

    assert primeira.status_code == 201
    assert segunda.status_code == 200
    assert segunda.json() == primeira.json()


def test_mesmo_id_com_documento_em_outra_mascara_e_o_mesmo_pix():
    payload = pix_normal()
    AntifraudApi.post(payload)
    digitos = re.sub(r"\D", "", payload["source_account"]["owner"]["document_number"])
    outra_escrita = mutar(payload, "source_account.owner.document_number", digitos)

    resposta = AntifraudApi.post(outra_escrita)

    assert resposta.status_code == 200


def test_mesmo_id_com_outro_valor_da_409():
    payload = pix_normal()
    AntifraudApi.post(payload)

    resposta = AntifraudApi.post(mutar(payload, "amount", payload["amount"] + 1))

    assert resposta.status_code == 409
    assert resposta.json()["code"] == "QIT006004"


def test_valor_decimal_da_400():
    resposta = AntifraudApi.post(mutar(pix_normal(), "amount", 150000.5))

    assert resposta.status_code == 400
    assert resposta.json()["code"] == "QIT000001"


def test_valor_zero_da_400():
    resposta = AntifraudApi.post(mutar(pix_normal(), "amount", 0))

    assert resposta.status_code == 400


def test_campo_a_mais_da_400():
    resposta = AntifraudApi.post(mutar(pix_normal(), "source.extra", "x"))

    assert resposta.status_code == 400


def test_canal_invalido_da_400():
    resposta = AntifraudApi.post(mutar(pix_normal(), "source.channel", "fax"))

    assert resposta.status_code == 400


def test_ip_invalido_da_400():
    resposta = AntifraudApi.post(mutar(pix_normal(), "source.ip", "999.1.1.1"))

    assert resposta.status_code == 400


def test_documento_fora_da_mascara_da_400():
    resposta = AntifraudApi.post(mutar(pix_normal(), "destination_account.owner.document_number", "12.34"))

    assert resposta.status_code == 400


def test_latitude_fora_do_intervalo_da_400():
    resposta = AntifraudApi.post(mutar(pix_normal(), "source.geolocation.latitude", 91))

    assert resposta.status_code == 400


def test_sem_geolocalizacao_e_aceito():
    resposta = AntifraudApi.post(mutar(pix_normal(), "source.geolocation", mutar.REMOVER))

    assert resposta.status_code == 201


def test_data_sem_fuso_da_400():
    resposta = AntifraudApi.post(mutar(pix_normal(), "transaction_date", "2026-10-17T22:15:00"))

    assert resposta.status_code == 400


@pytest.mark.parametrize("data", [
    "2025-13-04T14:00:00-03:00",  # mes 13
    "2025-02-30T14:00:00-03:00",  # 30 de fevereiro
    "2025-03-04T14:00:00+25:00",  # fuso que nao existe
])
def test_data_com_formato_certo_que_nao_existe_da_400(data):
    # Passa no pattern do schema e nao existe: antes virava 500.
    resposta = AntifraudApi.post(mutar(pix_normal(), "transaction_date", data))

    assert resposta.status_code == 400
    assert resposta.json()["code"] == "QIT000001"


def test_abertura_de_conta_que_nao_existe_da_400():
    resposta = AntifraudApi.post(mutar(pix_normal(), "destination_account.opening_date", "2019-02-29T10:00:00-03:00"))

    assert resposta.status_code == 400


def test_data_no_futuro_da_422():
    futuro = (agora_sp() + timedelta(minutes=10)).isoformat()

    resposta = AntifraudApi.post(pix_normal(data=futuro))

    assert resposta.status_code == 422
    assert resposta.json()["code"] == "QIT006002"


def test_data_dentro_da_folga_e_aceita():
    quase_agora = (agora_sp() + timedelta(minutes=2)).isoformat()

    resposta = AntifraudApi.post(pix_normal(data=quase_agora))

    assert resposta.status_code == 201


def test_data_antes_da_abertura_da_origem_da_422():
    payload = mutar(pix_normal(), "source_account.opening_date", agora_sp().isoformat())

    resposta = AntifraudApi.post(payload)

    assert resposta.status_code == 422
    assert resposta.json()["code"] == "QIT006003"


def test_data_antes_da_abertura_do_destino_da_422():
    payload = mutar(pix_normal(), "destination_account.opening_date", agora_sp().isoformat())

    resposta = AntifraudApi.post(payload)

    assert resposta.status_code == 422
    assert resposta.json()["code"] == "QIT006003"


def test_cnpj_alfanumerico_e_aceito_e_e_o_mesmo_com_e_sem_mascara():
    # Desde julho de 2026 a Receita emite CNPJ com letras (IN RFB 2.229/2024).
    # Antes: 400 no schema; e "so os digitos" juntaria empresas diferentes.
    payload = mutar(pix_normal(), "destination_account.owner.document_number", "12.ABC.345/01DE-35")

    resposta = AntifraudApi.post(payload)

    assert resposta.status_code == 201
    sinais = resposta.json()["metadata"]["signals"]
    assert sinais["payee_type"] == "PJ"
    assert sinais["destination_document_check_digit_valid"] is True

    sem_mascara = mutar(payload, "destination_account.owner.document_number", "12abc34501de35")
    assert AntifraudApi.post(sem_mascara).status_code == 200


def test_cnpj_alfanumerico_com_digito_errado_vai_para_signals():
    payload = mutar(pix_normal(), "destination_account.owner.document_number", "12.ABC.345/01DE-36")

    corpo = AntifraudApi.post(payload).json()

    assert corpo["metadata"]["signals"]["destination_document_check_digit_valid"] is False


def test_documento_com_digito_errado_vai_para_signals_sem_bloquear():
    payload = mutar(pix_normal(), "destination_account.owner.document_number", "111.111.111-12")

    corpo = AntifraudApi.post(payload).json()

    assert corpo["status"] == "approved"
    assert corpo["metadata"]["signals"]["destination_document_check_digit_valid"] is False
