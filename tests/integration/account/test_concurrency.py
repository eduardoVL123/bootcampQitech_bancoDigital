from uuid import uuid4

import pytest

from tests.utils import PayloadGenerator, RequestGenerator
from tests.utils.run_at_the_same_time import run_at_the_same_time


def conta_com_saldo(centavos: int = 0) -> str:
    _status, cliente = RequestGenerator.POST_customer(PayloadGenerator.create_customer_payload())
    status, conta = RequestGenerator.POST_account({"customer_key": cliente["customer_key"]})
    assert status == 201, f"nao consegui preparar a conta: {conta}"

    if centavos:
        status, deposito = RequestGenerator.POST_transaction(
            {"type": "DEPOSIT", "destination_account_key": conta["account_key"], "amount": centavos},
            idempotency_key=str(uuid4()),
        )
        assert status == 201, f"nao consegui depositar: {deposito}"

    return conta["account_key"]


def define_tarifa(centavos: int) -> None:
    """A politica de tarifa e global e append-only: fixe antes de afirmar valor."""
    status, corpo = RequestGenerator.POST_fee_policy({"transfer_fee_cents": centavos})
    assert status == 201, f"nao consegui definir a tarifa: {corpo}"


def saldo(account_key: str) -> int:
    _status, corpo = RequestGenerator.GET_account(account_key)
    return corpo["balance"]


def transferir(origem: str, destino: str, centavos: int) -> tuple:
    return RequestGenerator.POST_transaction(
        {
            "type": "TRANSFER",
            "origin_account_key": origem,
            "destination_account_key": destino,
            "amount": centavos,
        },
        idempotency_key=str(uuid4()),
    )


class TestConcurrency:
    """F6: as garantias sob disputa de verdade.

    A F2-11 ja provou a trava num saque. Aqui a disputa e entre
    transferencias, que travam DUAS contas cada: e onde aparece o
    deadlock, se a ordem da trava estiver errada.

    Dez chamadas, nao mil: o pool da API e de 5 mais overflow, e cada
    requisicao parada na trava segura uma conexao.
    """

    @pytest.mark.concurrency
    def test_f6_01_dez_transferencias_juntas_com_saldo_para_cinco(self):
        """Saldo que cobre exatamente cinco, dez pedidos no mesmo instante.

        Cada transferencia custa 1000 mais 200 de tarifa. Com 6000 na
        origem, cabem cinco e nao cabem seis. Sem a trava, as dez leem
        6000, as dez acham que cabe, e o saldo fecha negativo.
        """
        define_tarifa(200)
        ana = conta_com_saldo(6000)
        bruno = conta_com_saldo()

        respostas = run_at_the_same_time(lambda _: transferir(ana, bruno, 1000), list(range(10)))
        status = [r[0] for r in respostas]

        assert not [s for s in status if s >= 500], f"ninguem pode receber 5xx: {status}"
        assert status.count(201) == 5, f"exatamente cinco passam, veio {status}"
        assert status.count(409) == 5, f"os outros cinco levam 409, veio {status}"
        assert saldo(ana) == 0, "a origem fecha em zero, nunca negativa"
        assert saldo(bruno) == 5000

    @pytest.mark.concurrency
    def test_f6_02_transferencias_cruzadas_nao_travam(self):
        """A para B e B para A no mesmo instante.

        E o cenario classico de deadlock: se cada requisicao travasse
        na ordem em que os parametros chegaram, uma seguraria A
        esperando B e a outra seguraria B esperando A. O Postgres
        mataria uma das duas e a API responderia 5xx.

        A trava sai em ordem crescente de id, entao as duas pedem a
        mesma linha primeiro e uma espera a outra.
        """
        define_tarifa(200)
        ana = conta_com_saldo(100000)
        bruno = conta_com_saldo(100000)

        def transfere(indice):
            if indice % 2 == 0:
                return transferir(ana, bruno, 1000)
            return transferir(bruno, ana, 1000)

        respostas = run_at_the_same_time(transfere, list(range(10)))
        status = [r[0] for r in respostas]

        assert not [s for s in status if s >= 500], f"deadlock aparece como 5xx: {status}"
        assert status.count(201) == 10, f"as dez tinham saldo e tinham de passar: {status}"
        # Cada uma mandou cinco de 1000, recebeu cinco de 1000 e pagou
        # cinco tarifas de 200: 100000 menos 1000.
        assert saldo(ana) == 99000
        assert saldo(bruno) == 99000

    @pytest.mark.concurrency
    def test_f6_03_varias_origens_para_um_destino_somam_exato(self):
        """Dez contas diferentes creditando a mesma conta ao mesmo tempo.

        Aqui a disputa e pela linha do DESTINO. Sem a trava, dois
        creditos leem o mesmo saldo e um sobrescreve o outro: o destino
        recebe menos do que a soma, e a diferenca desaparece.
        """
        define_tarifa(200)
        origens = [conta_com_saldo(5000) for _ in range(10)]
        destino = conta_com_saldo()

        respostas = run_at_the_same_time(lambda origem: transferir(origem, destino, 1000), origens)
        status = [r[0] for r in respostas]

        assert status.count(201) == 10, f"todas tinham saldo: {status}"
        assert saldo(destino) == 10000, "o destino recebe a soma exata, sem credito perdido"
        for origem in origens:
            assert saldo(origem) == 3800

    @pytest.mark.concurrency
    def test_f6_04_conciliacao_fecha_em_zero_depois_da_corrida(self):
        """A prova final: depois da disputa, nenhum centavo sobrou nem faltou.

        Metade das transferencias e recusada por saldo. A conciliacao
        tem de fechar em zero de qualquer jeito: o pedido recusado nao
        grava lancamento nenhum.
        """
        define_tarifa(200)
        ana = conta_com_saldo(6000)
        bruno = conta_com_saldo()

        run_at_the_same_time(lambda _: transferir(ana, bruno, 1000), list(range(10)))

        status, conciliacao = RequestGenerator.GET_reconciliation()
        assert status == 200
        assert conciliacao["total"] == 0
