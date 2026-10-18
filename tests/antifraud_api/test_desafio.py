"""O resultado do desafio (2FA), como na API Pix da QI: o cliente informa
depois se confirmou ou negou. A analise original nao muda.

A resposta tem cronologia: nao pode ser anterior ao Pix nem estar no futuro
do relogio do servidor (mais a folga). A data vem sempre da base do proprio
cenario: uma base sorteada a parte podia cair antes do Pix.
"""
from datetime import datetime, timedelta

import pytest

from tests.utils.pix import (
    AntifraudApi, Pagador, Recebedor, agora_sp, analisa, disparou, nova_base, pix, pontos,
)
from tests.utils.run_at_the_same_time import run_at_the_same_time


def _data_do_pix(payload) -> datetime:
    return datetime.fromisoformat(payload["transaction_date"])


def _confirma(payload, resultado="approved_by_client", quando=None):
    """Responde o desafio. Sem `quando`, um minuto depois do proprio Pix."""
    quando = quando or _data_do_pix(payload) + timedelta(minutes=1)
    return AntifraudApi.patch(payload["id"], {"challenge_result": resultado, "event_date": quando.isoformat()})


def _desafio(base=None, recebedor=None):
    payload = pix(Pagador(), recebedor or Recebedor(), 2500000, (base or nova_base()).isoformat())
    assert analisa(payload)["status"] == "two_factor_required"
    return payload


def test_confirmar_o_2fa_registra_e_aparece_no_get():
    payload = _desafio()

    resposta = _confirma(payload)
    lido = AntifraudApi.get(payload["id"]).json()

    assert resposta.status_code == 200
    assert lido["status"] == "two_factor_required"
    assert lido["metadata"]["challenge"]["result"] == "approved_by_client"


def test_pix_aprovado_nao_aceita_resultado_de_desafio():
    payload = pix(Pagador(), Recebedor(), 5000, nova_base().isoformat())
    analisa(payload)

    resposta = _confirma(payload)

    assert resposta.status_code == 409
    assert resposta.json()["code"] == "QIT006005"


def test_mesmo_resultado_duas_vezes_e_idempotente():
    payload = _desafio()
    _confirma(payload)

    resposta = _confirma(payload)

    assert resposta.status_code == 200


def test_resultado_diferente_depois_da_409():
    payload = _desafio()
    _confirma(payload)

    resposta = _confirma(payload, "reproved_by_client")

    assert resposta.status_code == 409
    assert resposta.json()["code"] == "QIT006006"


def test_resultado_de_pix_inexistente_da_404():
    resposta = AntifraudApi.patch("pix-que-nao-existe", {"challenge_result": "approved_by_client",
                                                         "event_date": nova_base().isoformat()})

    assert resposta.status_code == 404


def test_resultado_invalido_da_400():
    payload = _desafio()

    resposta = AntifraudApi.patch(payload["id"], {"challenge_result": "talvez",
                                                  "event_date": _data_do_pix(payload).isoformat()})

    assert resposta.status_code == 400


def test_resposta_anterior_ao_pix_da_422_e_nao_grava():
    payload = _desafio()

    resposta = _confirma(payload, quando=_data_do_pix(payload) - timedelta(seconds=1))

    assert resposta.status_code == 422
    assert resposta.json()["code"] == "QIT006008"
    assert "challenge" not in AntifraudApi.get(payload["id"]).json()["metadata"]
    assert _confirma(payload).status_code == 200


def test_resposta_no_futuro_da_422():
    payload = _desafio()

    resposta = _confirma(payload, quando=agora_sp() + timedelta(hours=1))

    assert resposta.status_code == 422
    assert resposta.json()["code"] == "QIT006002"


def test_resposta_no_mesmo_instante_do_pix_e_aceita():
    payload = _desafio()

    resposta = _confirma(payload, quando=_data_do_pix(payload))

    assert resposta.status_code == 200


def test_resposta_historica_dias_depois_do_pix_e_aceita():
    # A data e de anos atras, longe do relogio de hoje, e vale para a
    # simulacao daquela epoca. Nao ha prazo maximo de resposta.
    payload = _desafio()

    resposta = _confirma(payload, quando=_data_do_pix(payload) + timedelta(days=3))

    assert resposta.status_code == 200


def test_repeticao_com_outra_data_devolve_a_resposta_original():
    payload = _desafio()
    primeira = _confirma(payload, quando=_data_do_pix(payload) + timedelta(minutes=1))

    segunda = _confirma(payload, quando=_data_do_pix(payload) + timedelta(minutes=30))

    assert segunda.status_code == 200
    assert segunda.json()["metadata"]["challenge"] == primeira.json()["metadata"]["challenge"]
    gravada = datetime.fromisoformat(AntifraudApi.get(payload["id"]).json()["metadata"]["challenge"]["event_date"])
    assert gravada == _data_do_pix(payload) + timedelta(minutes=1)


def test_repeticao_da_negativa_nao_antecipa_a_denuncia():
    # A negativa das 10h10 lista o destino a partir das 10h10. Repetir a
    # negativa com 10h01 devolve a original e nao cria outra entrada na lista.
    base, destino = nova_base(), Recebedor()
    payload = _desafio(base, destino)
    _confirma(payload, "reproved_by_client", base + timedelta(minutes=10))

    repetida = _confirma(payload, "reproved_by_client", base + timedelta(minutes=1))
    antes = analisa(pix(Pagador(), destino, 5000, (base + timedelta(minutes=5)).isoformat()))
    depois = analisa(pix(Pagador(), destino, 5000, (base + timedelta(minutes=20)).isoformat()))

    assert repetida.status_code == 200
    assert not disparou(antes, "REPUTACAO_INTERNA")
    assert pontos(depois, "REPUTACAO_INTERNA") == 40


def test_repeticao_com_data_que_nao_existe_da_400():
    payload = _desafio()
    _confirma(payload)

    resposta = AntifraudApi.patch(payload["id"], {"challenge_result": "approved_by_client",
                                                  "event_date": "2020-02-30T10:00:00-03:00"})

    assert resposta.status_code == 400


@pytest.mark.concurrency
def test_respostas_iguais_ao_mesmo_tempo_gravam_uma_so():
    payload = _desafio()
    corpos = [{"challenge_result": "approved_by_client",
               "event_date": (_data_do_pix(payload) + timedelta(minutes=minuto)).isoformat()} for minuto in range(6)]

    respostas = run_at_the_same_time(lambda corpo: AntifraudApi.patch(payload["id"], corpo), corpos)

    assert [r.status_code for r in respostas] == [200] * 6
    assert len({r.json()["metadata"]["challenge"]["event_date"] for r in respostas}) == 1


@pytest.mark.concurrency
def test_respostas_opostas_ao_mesmo_tempo_tem_uma_vencedora_e_409_sem_500():
    payload = _desafio()
    quando = (_data_do_pix(payload) + timedelta(minutes=1)).isoformat()
    corpos = [{"challenge_result": resultado, "event_date": quando}
              for resultado in ["approved_by_client", "reproved_by_client"] * 3]

    respostas = run_at_the_same_time(lambda corpo: AntifraudApi.patch(payload["id"], corpo), corpos)

    vencedor = AntifraudApi.get(payload["id"]).json()["metadata"]["challenge"]["result"]
    for corpo, resposta in zip(corpos, respostas):
        if corpo["challenge_result"] == vencedor:
            assert resposta.status_code == 200
        else:
            assert resposta.status_code == 409
            assert resposta.json()["code"] == "QIT006006"


def test_2fa_confirmado_conta_como_dinheiro_que_saiu():
    pagador, recebedor, base = Pagador(), Recebedor(), nova_base()
    primeiro = pix(pagador, recebedor, 2500000, base.isoformat())
    analisa(primeiro)
    _confirma(primeiro, quando=base + timedelta(minutes=1))

    segundo = analisa(pix(pagador, recebedor, 3000000, (base + timedelta(hours=1)).isoformat()))

    assert disparou(segundo, "MONTANTE_24H")


def test_2fa_sem_confirmacao_nao_conta():
    pagador, recebedor, base = Pagador(), Recebedor(), nova_base()
    analisa(pix(pagador, recebedor, 2500000, base.isoformat()))

    segundo = analisa(pix(pagador, recebedor, 3000000, (base + timedelta(hours=1)).isoformat()))

    assert not disparou(segundo, "MONTANTE_24H")
