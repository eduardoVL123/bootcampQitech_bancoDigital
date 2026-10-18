"""O id do Pix: o POST so aceita o id que o GET e o PATCH conseguem consultar.

GET e PATCH levam o id num segmento so do endereco. Um id com "/" era
aceito no POST (201) e nunca mais encontrado: o GET de "review%2Fa" dava 404.
O alfabeto: de 1 a 64 caracteres, o primeiro uma letra ASCII ou um numero,
os outros letras ASCII, numeros, ponto, hifen e sublinhado. O id nunca e
alterado, aparado ou truncado: fora disso, 400, e nada e gravado.
"""
import random
from urllib.parse import quote
from uuid import uuid4

import pytest

from tests.utils.pix import AntifraudApi, Pagador, Recebedor, mutar, nova_base, pix, pix_normal
from tests.utils.random_generator import RandomGenerator


def _get(pix_id):
    return AntifraudApi.get(quote(pix_id, safe=""))


@pytest.mark.parametrize("pix_id", [
    lambda: f"pix-{random.randint(10**8, 10**9)}",
    lambda: str(uuid4()),
    lambda: f"PIX.{uuid4().hex[:8]}_teste-1",
    lambda: "9" + uuid4().hex[:8],
], ids=["pix_e_numero", "uuid", "ponto_e_sublinhado", "comeca_com_numero"])
def test_ids_usuais_continuam_funcionando(pix_id):
    payload = pix_normal(id=pix_id())

    criado = AntifraudApi.post(payload)

    assert criado.status_code == 201, criado.text
    assert _get(payload["id"]).json()["key"] == criado.json()["key"]


def test_id_de_64_caracteres_e_aceito_e_o_de_65_nao():
    de_64 = ("p" + uuid4().hex + uuid4().hex)[:64]

    aceito = AntifraudApi.post(pix_normal(id=de_64))
    recusado = AntifraudApi.post(pix_normal(id=de_64 + "x"))

    assert aceito.status_code == 201
    assert recusado.status_code == 400


def test_post_get_patch_e_replay_usam_o_mesmo_id():
    payload = pix(Pagador(), Recebedor(), 2500000, nova_base().isoformat(), id=f"pix.{uuid4().hex[:10]}_a-b")

    criado = AntifraudApi.post(payload)
    lido = _get(payload["id"])
    respondido = AntifraudApi.patch(payload["id"], {"challenge_result": "approved_by_client",
                                                    "event_date": payload["transaction_date"]})
    repetido = AntifraudApi.post(payload)

    assert criado.status_code == 201
    assert criado.json()["status"] == "two_factor_required"
    assert lido.status_code == 200 and lido.json()["key"] == criado.json()["key"]
    assert respondido.status_code == 200
    assert repetido.status_code == 200 and repetido.json()["key"] == criado.json()["key"]


@pytest.mark.parametrize("pix_id", [
    "review/a", "a?b", "a#b", "a b", "a\tb", "a\u0001b", "abc\n", "abc\r", ".", "..", "../abc", "-abc", "_abc",
    "a%2Fb", "pix-ação", "a\\b",
], ids=["barra", "interrogacao", "cerquilha", "espaco", "tab", "controle", "quebra_de_linha_no_fim", "cr_no_fim",
        "ponto", "dois_pontos", "navegacao", "comeca_com_hifen", "comeca_com_sublinhado", "porcento",
        "fora_do_ascii", "barra_invertida"])
def test_id_fora_do_alfabeto_da_400_e_nao_cria_nada(pix_id):
    payload = pix_normal(id=pix_id)

    resposta = AntifraudApi.post(payload)

    assert resposta.status_code == 400, resposta.text
    assert resposta.json()["code"] == "QIT000001"
    assert _get(pix_id).status_code in (404, 405)


def test_id_recusado_nao_deixa_a_conta_gravada():
    # A conta de origem do pedido recusado nao pode ter ficado gravada com o
    # titular dele: outro titular estreia a mesma conta depois, sem 409.
    hoje, pagador = nova_base(), Pagador()
    recusado = pix(pagador, Recebedor(), 5000, hoje.isoformat(), id="review/a")
    assert AntifraudApi.post(recusado).status_code == 400

    estreia = mutar(pix(pagador, Recebedor(), 5000, hoje.isoformat()),
                    "source_account.owner.document_number", RandomGenerator.generate_cpf())

    assert AntifraudApi.post(estreia).status_code == 201
