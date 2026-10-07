from uuid import uuid4

from tests.utils import PayloadGenerator, RequestGenerator
from tests.utils.run_at_the_same_time import run_at_the_same_time


def conta_com_saldo(centavos: int = 0) -> str:
    """Prepara pela porta da frente: cliente, conta e, se preciso, um deposito."""
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
    """Fixa a tarifa vigente para este teste.

    A politica de tarifa e configuracao GLOBAL e append-only: criar uma
    nova muda o que todos os testes seguintes vao cobrar. Por isso todo
    teste que afirma um valor de tarifa define o valor antes, em vez de
    confiar na semente do database.sql. Sem isso, a ordem dos testes
    muda o resultado, e rodar um teste sozinho da outro numero.
    """
    status, corpo = RequestGenerator.POST_fee_policy({"transfer_fee_cents": centavos})
    assert status == 201, f"nao consegui definir a tarifa: {corpo}"


def saldo(account_key: str) -> int:
    _status, corpo = RequestGenerator.GET_account(account_key)
    return corpo["balance"]


def transferir(origem: str, destino: str, centavos: int, chave: str = None) -> tuple:
    return RequestGenerator.POST_transaction(
        {
            "type": "TRANSFER",
            "origin_account_key": origem,
            "destination_account_key": destino,
            "amount": centavos,
        },
        idempotency_key=chave or str(uuid4()),
    )


class TestTransaction:
    """F3: transferencia com tarifa.

    A transacao nao move dinheiro. Ela decide a regra (quem pode, quanto
    e a tarifa), grava o que foi PEDIDO, e pede o posting. Quem move e
    o livro.
    """

    def test_f3_01_transferencia_move_valor_e_cobra_tarifa(self):
        """O exemplo da apresentacao: Ana com R$ 898, Bruno com R$ 100."""
        define_tarifa(200)
        ana = conta_com_saldo(100000)
        bruno = conta_com_saldo()

        status, corpo = transferir(ana, bruno, 10000)

        assert status == 201
        assert corpo["amount"] == 10000
        assert corpo["fee_amount"] == 200
        assert corpo["status"] == "COMPLETED"
        assert saldo(ana) == 89800
        assert saldo(bruno) == 10000

    def test_f3_02_transferencia_gera_quatro_lancamentos_somando_zero(self):
        define_tarifa(200)
        ana = conta_com_saldo(100000)
        bruno = conta_com_saldo()

        transferir(ana, bruno, 10000)

        _status, conciliacao = RequestGenerator.GET_reconciliation()
        assert conciliacao["total"] == 0

        _status, extrato_ana = RequestGenerator.GET_account(ana)
        assert extrato_ana["balance"] == 89800

    def test_f3_03_tarifa_e_copiada_da_politica_vigente(self):
        """O fee_amount e copiado no momento da operacao, nunca recalculado."""
        define_tarifa(200)
        ana = conta_com_saldo(100000)
        bruno = conta_com_saldo()

        _status, criada = transferir(ana, bruno, 10000)
        status, consultada = RequestGenerator.GET_transaction(criada["transaction_key"])

        assert status == 200
        assert consultada["fee_amount"] == 200
        assert consultada["fee_policy_key"] is not None

    def test_f3_04_tarifa_antiga_preservada_depois_de_mudar_a_regra(self):
        """Mudar a tarifa amanha nao muda o que ja foi cobrado ontem.

        A fee_policy e append-only: a trigger do banco recusa UPDATE.
        Mudar a tarifa e criar outra politica, e a transacao guarda qual
        delas usou.
        """
        define_tarifa(200)
        ana = conta_com_saldo(100000)
        bruno = conta_com_saldo()

        _status, antiga = transferir(ana, bruno, 10000)
        assert antiga["fee_amount"] == 200

        status, _nova_politica = RequestGenerator.POST_fee_policy({"transfer_fee_cents": 500})
        assert status == 201

        _status, nova = transferir(ana, bruno, 10000)
        assert nova["fee_amount"] == 500

        _status, antiga_de_novo = RequestGenerator.GET_transaction(antiga["transaction_key"])
        assert antiga_de_novo["fee_amount"] == 200, "a transacao velha mantem a tarifa velha"

    def test_f3_05_recusa_saldo_que_nao_cobre_valor_mais_tarifa(self):
        """O saldo cobre o valor mas nao o valor mais a tarifa."""
        define_tarifa(200)
        ana = conta_com_saldo(10100)
        bruno = conta_com_saldo()

        status, corpo = transferir(ana, bruno, 10000)

        assert status == 409
        assert corpo["code"] == "QIT002012"
        assert saldo(ana) == 10100, "nada muda quando a tarifa nao cabe"
        assert saldo(bruno) == 0

    def test_f3_06_recusa_transferencia_para_a_propria_conta(self):
        ana = conta_com_saldo(100000)

        status, corpo = transferir(ana, ana, 1000)

        assert status == 422
        assert corpo["code"] == "QIT002019"

    def test_f3_07_recusa_transferencia_sem_destino(self):
        ana = conta_com_saldo(100000)

        status, corpo = RequestGenerator.POST_transaction(
            {"type": "TRANSFER", "origin_account_key": ana, "amount": 1000},
            idempotency_key=str(uuid4()),
        )

        assert status == 422
        assert corpo["code"] == "QIT002019"

    def test_f3_08_recusa_pedido_sem_chave_de_idempotencia(self):
        ana = conta_com_saldo(100000)
        bruno = conta_com_saldo()

        status, corpo = RequestGenerator.POST_transaction(
            {
                "type": "TRANSFER",
                "origin_account_key": ana,
                "destination_account_key": bruno,
                "amount": 1000,
            }
        )

        assert status == 400
        assert corpo["code"] == "QIT002021"

    def test_f3_09_mesma_chave_com_outro_pedido_e_conflito(self):
        define_tarifa(200)
        ana = conta_com_saldo(100000)
        bruno = conta_com_saldo()
        chave = str(uuid4())

        transferir(ana, bruno, 10000, chave=chave)
        status, corpo = transferir(ana, bruno, 20000, chave=chave)

        assert status == 409
        assert corpo["code"] == "QIT002020"
        assert saldo(ana) == 89800, "o segundo pedido nao pode ter movido nada"

    def test_f3_10_deposito_credita_sem_cobrar_tarifa(self):
        bruno = conta_com_saldo()

        status, corpo = RequestGenerator.POST_transaction(
            {"type": "DEPOSIT", "destination_account_key": bruno, "amount": 50000},
            idempotency_key=str(uuid4()),
        )

        assert status == 201
        assert corpo["fee_amount"] == 0
        assert saldo(bruno) == 50000


class TestTransactionConcurrency:
    """F3-11: o clique duplo."""

    def test_f3_11_dez_cliques_com_a_mesma_chave_geram_uma_transferencia(self):
        """Dez vezes o mesmo pedido: um debito, uma tarifa.

        A chave de idempotencia torna idempotente um metodo que o HTTP
        nao garante. O UNIQUE no banco e a rede final: entre consultar a
        chave e gravar a transacao cabe outra requisicao.
        """
        define_tarifa(200)
        ana = conta_com_saldo(100000)
        bruno = conta_com_saldo()
        chave = str(uuid4())

        def clique(_):
            return transferir(ana, bruno, 10000, chave=chave)

        respostas = run_at_the_same_time(clique, list(range(10)))
        status = [r[0] for r in respostas]

        assert not [s for s in status if s >= 500], f"ninguem pode receber 5xx: {status}"
        assert status.count(201) == 1, f"uma transferencia so, veio {status}"
        assert saldo(ana) == 89800, "um debito e uma tarifa, nao dez"
        assert saldo(bruno) == 10000

        chaves = {r[1]["transaction_key"] for r in respostas if "transaction_key" in r[1]}
        assert len(chaves) == 1, "todas as respostas apontam para a mesma transacao"

        _status, conciliacao = RequestGenerator.GET_reconciliation()
        assert conciliacao["total"] == 0
