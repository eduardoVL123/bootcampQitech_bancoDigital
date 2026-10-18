"""A data que o chamador informa fora do Pix: a resposta do desafio.

O DATA_RETROATIVA protege as janelas do Pix contra data fora de ordem. O
`event_date` do desafio nao tem protecao nenhuma, e ele decide o que o
motor promete no "nao fui eu": o recebedor fica em observacao por 24 horas
e o aparelho por 30 dias.

Cada teste aceita duas respostas certas: recusar a data (422) ou aceitar
sem deixar a data desfazer a protecao. A errada e a data apagar a regra.
A resposta anterior ao Pix e recusada (422 QIT006008). A posterior vale a
partir dela: a lista interna, como a confirmacao do 2FA, nao vale antes do
instante em que o titular falou.
"""
from datetime import timedelta

from tests.utils.pix import AntifraudApi, Pagador, Recebedor, analisa, disparou, nova_base, pix


def _responde(pix_id, resultado, quando):
    return AntifraudApi.patch(pix_id, {"challenge_result": resultado, "event_date": quando.isoformat()})


def test_nao_fui_eu_com_data_antiga_nao_apaga_a_cautelar():
    # A cautelar dura 24h a partir do event_date. Com a data de um ano
    # antes, ela nasce vencida, e o "nao fui eu" nao protege ninguem.
    agora, golpista = nova_base(), Recebedor()
    desafio = pix(Pagador(), golpista, 2500000, agora.isoformat())
    assert analisa(desafio)["status"] == "two_factor_required"

    resposta = _responde(desafio["id"], "reproved_by_client", agora - timedelta(days=365))
    if resposta.status_code == 422:
        return
    assert resposta.status_code == 200, resposta.text

    seguinte = analisa(pix(Pagador(), golpista, 15000, (agora + timedelta(minutes=10)).isoformat()))
    assert disparou(seguinte, "REPUTACAO_INTERNA")


def test_nao_fui_eu_dias_depois_do_pix_vale_a_partir_da_denuncia():
    # O titular respondeu cinco dias depois do Pix. Quem pagou o golpista
    # nesses dias analisou sem a denuncia, que ainda nao existia: usar a
    # palavra do titular antes de ele falar seria informacao do futuro. Dali
    # em diante, a cautelar vale.
    agora, golpista = nova_base(), Recebedor()
    desafio = pix(Pagador(), golpista, 2500000, agora.isoformat())
    analisa(desafio)

    resposta = _responde(desafio["id"], "reproved_by_client", agora + timedelta(days=5))
    assert resposta.status_code == 200, resposta.text

    antes = analisa(pix(Pagador(), golpista, 15000, (agora + timedelta(minutes=10)).isoformat()))
    depois = analisa(pix(Pagador(), golpista, 15000, (agora + timedelta(days=5, minutes=10)).isoformat()))
    assert not disparou(antes, "REPUTACAO_INTERNA")
    assert disparou(depois, "REPUTACAO_INTERNA")


def test_aparelho_do_nao_fui_eu_com_data_antiga_continua_marcado():
    # O aparelho de quem disse "nao fui eu" fica 30 dias com +40. Datado de
    # um ano antes, sai da lista no mesmo instante em que entra.
    agora, vitima = nova_base(), Pagador()
    desafio = pix(vitima, Recebedor(), 2500000, agora.isoformat())
    analisa(desafio)

    resposta = _responde(desafio["id"], "reproved_by_client", agora - timedelta(days=365))
    if resposta.status_code == 422:
        return

    outro_titular = Pagador()
    seguinte = analisa(pix(outro_titular, Recebedor(), 15000, (agora + timedelta(hours=1)).isoformat(),
                           aparelho=vitima.aparelho))
    assert disparou(seguinte, "REPUTACAO_INTERNA")


def test_segunda_denuncia_com_data_recuada_ainda_confirma():
    # Dois titulares distintos dizem "nao fui eu" para o mesmo recebedor: a
    # fraude e confirmada e o Pix seguinte e bloqueado. A segunda denuncia,
    # datada antes da primeira, nao pode desfazer a confirmacao.
    agora, golpista = nova_base(), Recebedor()
    primeiro = pix(Pagador(), golpista, 2500000, agora.isoformat())
    analisa(primeiro)
    assert _responde(primeiro["id"], "reproved_by_client", agora + timedelta(minutes=2)).status_code == 200

    # Valor baixo: a cautelar (+40) sozinha pede a selfie, e o segundo titular nega.
    segundo = pix(Pagador(), golpista, 15000, (agora + timedelta(hours=1)).isoformat())
    assert analisa(segundo)["status"] == "two_factor_required"
    resposta = _responde(segundo["id"], "reproved_by_client", agora - timedelta(days=40))
    if resposta.status_code == 422:
        return

    seguinte = analisa(pix(Pagador(), golpista, 15000, (agora + timedelta(hours=2)).isoformat()))
    assert seguinte["status"] == "rejected"
