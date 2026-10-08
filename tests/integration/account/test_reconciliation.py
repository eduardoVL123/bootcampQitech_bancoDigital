from uuid import uuid4

from tests.utils import PayloadGenerator, RequestGenerator
from tests.utils.db_utils import DbUtils


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


def conciliacao() -> dict:
    status, corpo = RequestGenerator.GET_reconciliation()
    assert status == 200, f"a conciliacao nao respondeu: {status} {corpo}"
    return corpo


class TestReconciliation:
    """F5: a soma de todos os lancamentos de todas as contas.

    E o unico teste que olha o sistema inteiro de uma vez. Se ele
    fechar em zero, nenhum centavo foi criado nem destruido: todo
    debito tem o credito dele em algum lugar.
    """

    def test_f5_01_conciliacao_fecha_em_zero_no_sistema_vazio(self):
        """Zera o banco antes, porque a assercao e sobre o total de tudo.

        E a excecao que a Aula 3 permite: DbUtils so para zerar, nunca
        para montar cenario.
        """
        DbUtils.rollback()

        corpo = conciliacao()

        assert corpo["total"] == 0
        assert corpo["entry_count"] == 0

    def test_f5_02_conciliacao_continua_zero_depois_de_depositos_e_transferencias(self):
        DbUtils.rollback()
        ana = conta_com_saldo(100000)
        bruno = conta_com_saldo(50000)

        status, corpo = RequestGenerator.POST_transaction(
            {
                "type": "TRANSFER",
                "origin_account_key": ana,
                "destination_account_key": bruno,
                "amount": 10000,
            },
            idempotency_key=str(uuid4()),
        )
        assert status == 201, corpo

        depois = conciliacao()

        assert depois["total"] == 0
        assert depois["entry_count"] == 8, (
            "dois depositos dao dois lancamentos cada, a transferencia da quatro: "
            f"esperava 8, veio {depois['entry_count']}"
        )
