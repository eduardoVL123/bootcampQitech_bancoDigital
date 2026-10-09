from uuid import uuid4

import pytest

from tests.utils import PayloadGenerator, RequestGenerator
from tests.utils.credential import token_de_cliente, token_de_operador
from tests.utils.run_at_the_same_time import run_at_the_same_time


def cliente_com_conta(centavos: int = 0) -> tuple:
    """Devolve (customer_key, account_key), preparado pela porta da frente."""
    _status, cliente = RequestGenerator.POST_customer(PayloadGenerator.create_customer_payload())
    customer_key = cliente["customer_key"]

    status, conta = RequestGenerator.POST_account({"customer_key": customer_key})
    assert status == 201, f"nao consegui preparar a conta: {conta}"
    account_key = conta["account_key"]

    if centavos:
        status, deposito = RequestGenerator.POST_transaction(
            {"type": "DEPOSIT", "destination_account_key": account_key, "amount": centavos},
            idempotency_key=str(uuid4()),
            credential=token_de_operador(),
        )
        assert status == 201, f"nao consegui depositar: {deposito}"

    return customer_key, account_key


def define_tarifa(centavos: int) -> None:
    status, corpo = RequestGenerator.POST_fee_policy({"transfer_fee_cents": centavos})
    assert status == 201, f"nao consegui definir a tarifa: {corpo}"


def conta(account_key: str) -> dict:
    status, corpo = RequestGenerator.GET_account(account_key, credential=token_de_operador())
    assert status == 200, corpo
    return corpo


def transfere_de(origem: str, dono_da_origem: str, centavos: int = 1000) -> tuple:
    _outro, destino = cliente_com_conta()
    return RequestGenerator.POST_transaction(
        {
            "type": "TRANSFER",
            "origin_account_key": origem,
            "destination_account_key": destino,
            "amount": centavos,
        },
        idempotency_key=str(uuid4()),
        credential=token_de_cliente(dono_da_origem),
    )


def eventos_de(account_key: str, status_procurado: str) -> list:
    return [e for e in conta(account_key)["status_events"] if e["status"] == status_procurado]


class TestAccountBlock:
    """F8: bloquear e desbloquear.

    Antes desta fatia a regra "conta bloqueada nao movimenta" existia no
    posting_controller e nao tinha teste nenhum, porque nao havia como
    bloquear uma conta pela porta da frente.
    """

    def test_f8_01_operador_bloqueia_a_conta(self):
        _dono, account_key = cliente_com_conta()

        status, corpo = RequestGenerator.PATCH_account(
            account_key, {"status": "BLOCKED", "reason": "OPERATOR"}
        )

        assert status == 200
        assert corpo["status"] == "BLOCKED"
        bloqueios = [e for e in corpo["status_events"] if e["status"] == "BLOCKED"]
        assert len(bloqueios) == 1
        assert bloqueios[0]["reason"] == "OPERATOR"

    def test_f8_02_conta_bloqueada_nao_movimenta(self):
        """O teste que o QIT002011 nunca teve."""
        define_tarifa(200)
        dono, account_key = cliente_com_conta(100000)
        RequestGenerator.PATCH_account(account_key, {"status": "BLOCKED", "reason": "OPERATOR"})

        status, corpo = transfere_de(account_key, dono)

        assert status == 409
        assert corpo["code"] == "QIT002011"
        assert conta(account_key)["balance"] == 100000, "nenhum centavo pode ter saido"

    def test_f8_03_operador_desbloqueia_e_a_conta_volta_a_movimentar(self):
        define_tarifa(200)
        dono, account_key = cliente_com_conta(100000)
        RequestGenerator.PATCH_account(account_key, {"status": "BLOCKED", "reason": "OPERATOR"})

        status, corpo = RequestGenerator.PATCH_account(
            account_key, {"status": "ACTIVE", "reason": "OPERATOR"}
        )

        assert status == 200
        assert corpo["status"] == "ACTIVE"
        status, transacao = transfere_de(account_key, dono, 1000)
        assert status == 201, transacao
        assert conta(account_key)["balance"] == 98800

    def test_f8_04_bloqueio_por_suspeita_registra_o_motivo(self):
        """O motivo nao e enfeite: e o que explica o bloqueio depois."""
        _dono, account_key = cliente_com_conta()

        status, corpo = RequestGenerator.PATCH_account(
            account_key, {"status": "BLOCKED", "reason": "SUSPICIOUS_ACTIVITY"}
        )

        assert status == 200
        bloqueios = [e for e in corpo["status_events"] if e["status"] == "BLOCKED"]
        assert bloqueios[0]["reason"] == "SUSPICIOUS_ACTIVITY"

    def test_f8_10_pedir_o_mesmo_estado_duas_vezes_e_idempotente(self):
        """PATCH e idempotente por definicao: repetir nao infla o historico."""
        _dono, account_key = cliente_com_conta()
        RequestGenerator.PATCH_account(account_key, {"status": "BLOCKED", "reason": "OPERATOR"})

        status, corpo = RequestGenerator.PATCH_account(
            account_key, {"status": "BLOCKED", "reason": "OPERATOR"}
        )

        assert status == 200
        assert corpo["status"] == "BLOCKED"
        assert len(eventos_de(account_key, "BLOCKED")) == 1, "o segundo pedido nao grava evento"


class TestAccountClose:
    """Encerrar e irreversivel, e por isso tem mais recusas que o resto."""

    def test_f8_05_encerra_conta_com_saldo_zero(self):
        _dono, account_key = cliente_com_conta()

        status, corpo = RequestGenerator.PATCH_account(
            account_key, {"status": "CLOSED", "reason": "OPERATOR"}
        )

        assert status == 200
        assert corpo["status"] == "CLOSED"

    def test_f8_06_recusa_encerrar_conta_com_saldo(self):
        """O que sobrou e do cliente: encerrar sumiria com o dinheiro."""
        _dono, account_key = cliente_com_conta(5000)

        status, corpo = RequestGenerator.PATCH_account(
            account_key, {"status": "CLOSED", "reason": "OPERATOR"}
        )

        assert status == 409
        assert corpo["code"] == "QIT002014"
        assert conta(account_key)["status"] == "ACTIVE"
        assert conta(account_key)["balance"] == 5000

    def test_f8_07_conta_encerrada_nao_movimenta(self):
        define_tarifa(200)
        dono, account_key = cliente_com_conta()
        RequestGenerator.PATCH_account(account_key, {"status": "CLOSED", "reason": "OPERATOR"})

        status, corpo = transfere_de(account_key, dono)

        assert status == 409
        assert corpo["code"] == "QIT002011"

    def test_f8_08_conta_encerrada_nao_reabre(self):
        """CLOSED e terminal: reabrir apagaria a historia."""
        _dono, account_key = cliente_com_conta()
        RequestGenerator.PATCH_account(account_key, {"status": "CLOSED", "reason": "OPERATOR"})

        status, corpo = RequestGenerator.PATCH_account(
            account_key, {"status": "ACTIVE", "reason": "OPERATOR"}
        )

        assert status == 422
        assert corpo["code"] == "QIT002018"
        assert conta(account_key)["status"] == "CLOSED"

    def test_f8_09_depois_de_encerrar_o_cliente_pode_abrir_conta_nova(self):
        """Prova que o indice unico parcial olha closed_at, e nao o estado."""
        customer_key, antiga = cliente_com_conta()
        RequestGenerator.PATCH_account(antiga, {"status": "CLOSED", "reason": "OPERATOR"})

        status, nova = RequestGenerator.POST_account({"customer_key": customer_key})

        assert status == 201, f"esperava conta nova, veio {status} {nova}"
        assert nova["account_key"] != antiga
        assert nova["balance"] == 0
        assert nova["status"] == "ACTIVE"


class TestAccountStateRefusals:
    def test_f8_11_credencial_de_cliente_nao_muda_estado(self):
        dono, account_key = cliente_com_conta()

        status, corpo = RequestGenerator.PATCH_account(
            account_key,
            {"status": "BLOCKED", "reason": "OPERATOR"},
            credential=token_de_cliente(dono),
        )

        assert status == 403
        assert corpo["code"] == "QIT000006"
        assert conta(account_key)["status"] == "ACTIVE"

    def test_f8_12_recusa_estado_que_nao_existe(self):
        _dono, account_key = cliente_com_conta()

        for payload in (
            {"status": "FROZEN", "reason": "OPERATOR"},
            {"status": "BLOCKED", "reason": "PORQUE_EU_QUIS"},
            {"status": "BLOCKED"},
            {"status": "BLOCKED", "reason": "OPERATOR", "balance": 999},
        ):
            status, corpo = RequestGenerator.PATCH_account(account_key, payload)
            assert status == 400, f"{payload} tinha de ser recusado, veio {status} {corpo}"
            assert corpo["code"] == "QIT000001"

        assert conta(account_key)["status"] == "ACTIVE"

    def test_f8_13_conta_que_nao_existe_responde_404(self):
        status, corpo = RequestGenerator.PATCH_account(
            str(uuid4()), {"status": "BLOCKED", "reason": "OPERATOR"}
        )

        assert status == 404
        assert corpo["code"] == "QIT002010"


class TestAccountStateConcurrency:
    """A trava do PATCH, provada por disputa de verdade."""

    @pytest.mark.concurrency
    def test_f8_14_encerrar_e_transferir_ao_mesmo_tempo_nao_perde_dinheiro(self):
        """Encerrar decide em cima do saldo, e o saldo pode estar mudando.

        Sem a trava, as duas requisicoes leem saldo 1000: o encerramento
        ve "ainda tem saldo" e recusa, ou pior, le zero depois de a
        transferencia debitar e encerra uma conta que acabou de mandar
        dinheiro. O que nao pode acontecer, nunca, e conta CLOSED com
        saldo diferente de zero: seria dinheiro do cliente preso numa
        conta que nao movimenta mais.

        Qual das duas ganha e indiferente, e por isso a assercao e sobre
        a regra, nao sobre o vencedor.
        """
        define_tarifa(0)
        dono, account_key = cliente_com_conta(1000)
        _outro, destino = cliente_com_conta()

        def encerra(_):
            return RequestGenerator.PATCH_account(
                account_key, {"status": "CLOSED", "reason": "OPERATOR"}
            )

        def transfere(_):
            return RequestGenerator.POST_transaction(
                {
                    "type": "TRANSFER",
                    "origin_account_key": account_key,
                    "destination_account_key": destino,
                    "amount": 1000,
                },
                idempotency_key=str(uuid4()),
                credential=token_de_cliente(dono),
            )

        respostas = run_at_the_same_time(
            lambda i: encerra(i) if i % 2 == 0 else transfere(i), list(range(10))
        )
        status = [r[0] for r in respostas]
        assert not [s for s in status if s >= 500], f"ninguem pode receber 5xx: {status}"

        final = conta(account_key)
        assert not (final["status"] == "CLOSED" and final["balance"] != 0), (
            f"conta encerrada com saldo preso dentro: {final}"
        )
        _status, conciliacao = RequestGenerator.GET_reconciliation()
        assert conciliacao["total"] == 0

    @pytest.mark.concurrency
    def test_f8_15_depositar_e_encerrar_ao_mesmo_tempo_nao_prende_dinheiro(self):
        """O caso que de verdade exige a trava, e o F8-14 nao pegava.

        No F8-14 a disputa e com uma TRANSFERENCIA, que so DIMINUI o
        saldo: encerrar le 1000 e recusa, ou le 0 e encerra uma conta
        vazia. As duas saidas respeitam a regra, e por isso aquele teste
        passava mesmo sem trava nenhuma. Foi um mutante que mostrou
        isso: tirar o with_for_update nao derrubava teste algum.

        Com DEPOSITO a disputa muda de sentido, porque ele AUMENTA o
        saldo. Sem a trava, o encerramento le saldo 0, decide que pode
        encerrar, e o deposito entra em seguida: sobra uma conta CLOSED
        com dinheiro preso dentro, que nao movimenta mais. Com a trava,
        uma das duas espera, e quem chega depois ve o estado de verdade.
        """
        _dono, account_key = cliente_com_conta()

        def encerra(_):
            return RequestGenerator.PATCH_account(
                account_key, {"status": "CLOSED", "reason": "OPERATOR"}
            )

        def deposita(_):
            return RequestGenerator.POST_transaction(
                {"type": "DEPOSIT", "destination_account_key": account_key, "amount": 1000},
                idempotency_key=str(uuid4()),
                credential=token_de_operador(),
            )

        respostas = run_at_the_same_time(
            lambda i: encerra(i) if i % 2 == 0 else deposita(i), list(range(10))
        )
        status = [r[0] for r in respostas]
        assert not [s for s in status if s >= 500], f"ninguem pode receber 5xx: {status}"

        final = conta(account_key)
        assert not (final["status"] == "CLOSED" and final["balance"] != 0), (
            f"conta encerrada com dinheiro preso dentro: {final}"
        )
        _status, conciliacao = RequestGenerator.GET_reconciliation()
        assert conciliacao["total"] == 0
