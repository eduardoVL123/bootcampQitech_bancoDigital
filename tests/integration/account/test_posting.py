from uuid import uuid4

from tests.utils import PayloadGenerator, RequestGenerator
from tests.utils.run_at_the_same_time import run_at_the_same_time


def conta_nova() -> str:
    """Um cliente e a conta dele, pela porta da frente. Saldo zero."""
    status, cliente = RequestGenerator.POST_customer(PayloadGenerator.create_customer_payload())
    assert status == 201, f"nao consegui preparar o cliente: {cliente}"
    status, conta = RequestGenerator.POST_account({"customer_key": cliente["customer_key"]})
    assert status == 201, f"nao consegui preparar a conta: {conta}"
    return conta["account_key"]


def deposito(account_key: str, centavos: int, posting_key: str = None) -> tuple:
    """Deposito: entra na conta do cliente, sai da conta de liquidacao.

    Dois lancamentos que somam zero. A SETTLEMENT e a contrapartida: o
    dinheiro nao aparece do nada, ele vem de algum lugar no livro.
    """
    return RequestGenerator.POST_posting(
        {
            "posting_key": posting_key or str(uuid4()),
            "type": "DEPOSIT",
            "entries": [
                {"account_key": account_key, "amount": centavos},
                {"account_code": "SETTLEMENT", "amount": -centavos},
            ],
        }
    )


def saldo(account_key: str) -> int:
    _status, corpo = RequestGenerator.GET_account(account_key)
    return corpo["balance"]


class TestPosting:
    """F2: POST /internal/posting, a unica rota que move dinheiro."""

    def test_f2_01_deposito_credita_a_conta(self):
        account_key = conta_nova()

        status, corpo = deposito(account_key, 100000)

        assert status == 201
        assert saldo(account_key) == 100000
        assert len(corpo["entries"]) == 2

    def test_f2_02_deposito_mantem_a_conciliacao_em_zero(self):
        """A prova do sistema inteiro: a soma de todo o livro e zero.

        Se um dia alguem gravar um lancamento solto, sem o par que o
        equilibra, este numero deixa de ser zero e o teste fica vermelho.
        """
        account_key = conta_nova()
        deposito(account_key, 50000)

        status, corpo = RequestGenerator.GET_reconciliation()

        assert status == 200
        assert corpo["total"] == 0

    def test_f2_03_lancamento_numera_a_sequencia_da_conta(self):
        """A sequencia e o que o cursor do extrato usa para paginar."""
        account_key = conta_nova()

        _status, primeiro = deposito(account_key, 1000)
        _status, segundo = deposito(account_key, 2000)

        do_cliente = [e for e in primeiro["entries"] if e["account_key"] == account_key]
        assert do_cliente[0]["sequence"] == 1
        assert do_cliente[0]["balance_after"] == 1000

        do_cliente = [e for e in segundo["entries"] if e["account_key"] == account_key]
        assert do_cliente[0]["sequence"] == 2
        assert do_cliente[0]["balance_after"] == 3000

    def test_f2_04_lancamento_de_conta_tecnica_nao_tem_sequencia(self):
        """E o que impede a SETTLEMENT de virar fila de espera do banco.

        Sem sequencia e sem balance_after, o lancamento tecnico e um
        INSERT puro: nao le nada da linha da conta, entao nao precisa
        trava-la.
        """
        account_key = conta_nova()

        _status, corpo = deposito(account_key, 1000)

        tecnico = [e for e in corpo["entries"] if e["account_key"] != account_key][0]
        assert tecnico["sequence"] is None
        assert tecnico["balance_after"] is None

    def test_f2_05_mesma_posting_key_nao_credita_duas_vezes(self):
        account_key = conta_nova()
        chave = str(uuid4())

        primeiro_status, _ = deposito(account_key, 70000, posting_key=chave)
        segundo_status, _ = deposito(account_key, 70000, posting_key=chave)

        assert primeiro_status == 201
        assert segundo_status == 200
        assert saldo(account_key) == 70000, "o replay nao pode creditar de novo"

    def test_f2_06_recusa_conjunto_que_nao_soma_zero(self):
        account_key = conta_nova()

        status, corpo = RequestGenerator.POST_posting(
            {
                "posting_key": str(uuid4()),
                "type": "DEPOSIT",
                "entries": [
                    {"account_key": account_key, "amount": 10000},
                    {"account_code": "SETTLEMENT", "amount": -9000},
                ],
            }
        )

        assert status == 422
        assert corpo["code"] == "QIT002017"
        assert saldo(account_key) == 0, "nada pode ter sido gravado"

    def test_f2_07_recusa_conta_que_nao_existe(self):
        status, corpo = RequestGenerator.POST_posting(
            {
                "posting_key": str(uuid4()),
                "type": "DEPOSIT",
                "entries": [
                    {"account_key": str(uuid4()), "amount": 100},
                    {"account_code": "SETTLEMENT", "amount": -100},
                ],
            }
        )

        assert status == 404
        assert corpo["code"] == "QIT002010"

    def test_f2_08_recusa_saldo_insuficiente(self):
        """409, e nao 422: o pedido e possivel, o estado de agora e que nao deixa."""
        account_key = conta_nova()
        deposito(account_key, 5000)

        status, corpo = RequestGenerator.POST_posting(
            {
                "posting_key": str(uuid4()),
                "type": "WITHDRAWAL",
                "entries": [
                    {"account_key": account_key, "amount": -9000},
                    {"account_code": "SETTLEMENT", "amount": 9000},
                ],
            }
        )

        assert status == 409
        assert corpo["code"] == "QIT002012"
        assert saldo(account_key) == 5000, "nada muda quando o saldo nao cobre"

    def test_f2_09_recusa_lancamento_de_valor_zero(self):
        account_key = conta_nova()

        status, corpo = RequestGenerator.POST_posting(
            {
                "posting_key": str(uuid4()),
                "type": "DEPOSIT",
                "entries": [
                    {"account_key": account_key, "amount": 0},
                    {"account_code": "SETTLEMENT", "amount": 0},
                ],
            }
        )

        assert status == 400
        assert corpo["code"] == "QIT000001"

    def test_f2_10_recusa_entrada_sem_conta_nenhuma(self):
        status, corpo = RequestGenerator.POST_posting(
            {
                "posting_key": str(uuid4()),
                "type": "DEPOSIT",
                "entries": [{"amount": 100}, {"account_code": "SETTLEMENT", "amount": -100}],
            }
        )

        assert status == 400
        assert corpo["code"] == "QIT000001"


class TestPostingConcurrency:
    """F2-11: a trava funciona sob disputa real."""

    def test_f2_11_dez_saques_com_saldo_para_cinco_passam_exatamente_cinco(self):
        """O teste que prova o Principal desafio da RFC 02.

        Saldo de 5000, dez saques de 1000 ao mesmo tempo. Sem a trava,
        todos leem 5000, todos acham que cabe, e o saldo fica negativo
        ou o CHECK do banco derruba metade com 500.
        """
        account_key = conta_nova()
        deposito(account_key, 5000)

        def saque(_):
            return RequestGenerator.POST_posting(
                {
                    "posting_key": str(uuid4()),
                    "type": "WITHDRAWAL",
                    "entries": [
                        {"account_key": account_key, "amount": -1000},
                        {"account_code": "SETTLEMENT", "amount": 1000},
                    ],
                }
            )

        respostas = run_at_the_same_time(saque, list(range(10)))
        status = [r[0] for r in respostas]

        assert not [s for s in status if s >= 500], f"ninguem pode receber 5xx: {status}"
        assert status.count(201) == 5, f"exatamente cinco passam, veio {status}"
        assert status.count(409) == 5, f"os outros cinco levam 409, veio {status}"
        assert saldo(account_key) == 0

        _status, conciliacao = RequestGenerator.GET_reconciliation()
        assert conciliacao["total"] == 0
