"""Pedidos simultaneos de verdade: as travas consultivas serializam o
pagador, o recebedor, o aparelho e o IP, e nenhum par cruzado trava."""
import pytest

from tests.utils.pix import AntifraudApi, Pagador, Recebedor, mutar, nova_base, pix, regra
from tests.utils.random_generator import RandomGenerator
from tests.utils.run_at_the_same_time import run_at_the_same_time

CASA = "99999999"


@pytest.mark.concurrency
def test_concorrencia_velocity_conta_certo():
    pagador, data = Pagador(), nova_base().isoformat()
    payloads = [pix(pagador, Recebedor(), 5000, data) for _ in range(8)]

    respostas = run_at_the_same_time(AntifraudApi.post, payloads)

    assert all(r.status_code == 201 for r in respostas)
    velocity = [regra(r.json(), "VELOCITY") for r in respostas]
    pontos = sorted(v["raw_points"] if v and v["evaluation"] == "triggered" else 0 for v in velocity)
    assert pontos == [0, 0, 25, 25, 40, 40, 40, 40]


@pytest.mark.concurrency
def test_concorrencia_conta_laranja_conta_certo():
    recebedor, data = Recebedor(aberta_em=nova_base().replace(year=2019)), nova_base().isoformat()
    payloads = [pix(Pagador(), recebedor, 5000, data) for _ in range(8)]

    respostas = run_at_the_same_time(AntifraudApi.post, payloads)

    assert all(r.status_code == 201 for r in respostas)
    laranja = [regra(r.json(), "CONTA_LARANJA") for r in respostas]
    disparadas = [c for c in laranja if c and c["evaluation"] == "triggered"]
    assert len(disparadas) == 4


@pytest.mark.concurrency
def test_pix_cruzados_nao_dao_deadlock():
    ana, bruno = Recebedor(), Recebedor()
    ana_paga, bruno_paga = ana.como_pagador(), bruno.como_pagador()
    data = nova_base().isoformat()
    payloads = [pix(ana_paga, bruno, 5000, data) for _ in range(6)]
    payloads += [pix(bruno_paga, ana, 5000, data) for _ in range(6)]

    respostas = run_at_the_same_time(AntifraudApi.post, payloads)

    assert [r.status_code for r in respostas] == [201] * 12


@pytest.mark.concurrency
def test_pix_cruzados_entre_contas_novas_da_casa_nao_dao_deadlock():
    # No teste de cima, o destino tem outro participant: a conta da Ana como
    # origem e como destino sao contas DIFERENTES, e nenhum INSERT disputa
    # com outro. Aqui as duas sao da casa e nunca foram vistas, entao A -> B
    # e B -> A criam as mesmas duas contas, cada um comecando pela sua. Varias
    # rodadas, porque o deadlock depende de quem chega primeiro (2 em 10
    # antes da correcao).
    for _ in range(10):
        ana, bruno = Recebedor(participante=CASA), Recebedor(participante=CASA)
        data = nova_base().isoformat()
        payloads = [pix(ana.como_pagador(), bruno, 5000, data) for _ in range(3)]
        payloads += [pix(bruno.como_pagador(), ana, 5000, data) for _ in range(3)]

        respostas = run_at_the_same_time(AntifraudApi.post, payloads)

        assert [r.status_code for r in respostas] == [201] * 6


@pytest.mark.concurrency
def test_conta_nova_descrita_com_dois_titulares_ao_mesmo_tempo_fica_com_um_so():
    # Quem insere a conta primeiro define o titular. Os pedidos com o outro
    # titular esperam esse INSERT, leem a conta gravada e voltam 409, sem 500.
    destino, data = Recebedor(), nova_base().isoformat()
    outro_titular = RandomGenerator.generate_cpf()
    payloads = [pix(Pagador(), destino, 5000, data) for _ in range(6)]
    payloads[3:] = [mutar(p, "destination_account.owner.document_number", outro_titular) for p in payloads[3:]]

    respostas = run_at_the_same_time(AntifraudApi.post, payloads)

    assert sorted(r.status_code for r in respostas) == [201] * 3 + [409] * 3
    assert all(r.json()["code"] == "QIT006007" for r in respostas if r.status_code == 409)
    titulares = {p["destination_account"]["owner"]["document_number"]
                 for p, r in zip(payloads, respostas) if r.status_code == 201}
    assert len(titulares) == 1


@pytest.mark.concurrency
def test_mesmo_id_ao_mesmo_tempo_grava_uma_analise_so():
    payload = pix(Pagador(), Recebedor(), 5000, nova_base().isoformat())

    respostas = run_at_the_same_time(AntifraudApi.post, [payload] * 6)

    assert sorted(r.status_code for r in respostas) == [200] * 5 + [201]
    assert len({r.json()["key"] for r in respostas}) == 1
