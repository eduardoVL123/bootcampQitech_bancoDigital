from uuid import uuid4

from tests.utils import PayloadGenerator, RequestGenerator
from tests.utils.credential import (
    token_com_alg_none,
    token_com_outro_segredo,
    token_de_cliente,
    token_de_operador,
    token_vencido,
)


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


def saldo_pelo_operador(account_key: str) -> int:
    status, corpo = RequestGenerator.GET_account(account_key, credential=token_de_operador())
    assert status == 200, corpo
    return corpo["balance"]


class TestAuthorizationOwner:
    """F7: a R8, e o item #1 do OWASP API Top 10.

    O INTERNAL-TOKEN diz QUE APLICACAO esta falando. Ele nao diz QUEM.
    Sem esta fatia, qualquer um que tenha o token do aplicativo le o
    saldo e o extrato de qualquer conta do banco.
    """

    def test_f7_01_dono_le_a_propria_conta(self):
        customer_key, account_key = cliente_com_conta(5000)

        status, corpo = RequestGenerator.GET_account(
            account_key, credential=token_de_cliente(customer_key)
        )

        assert status == 200
        assert corpo["balance"] == 5000

    def test_f7_02_conta_de_outro_cliente_responde_404(self):
        """404 e nao 403, para nao confirmar que a conta existe.

        A MDN diz a frase: o servidor pode responder 404 em vez de 403
        para esconder a existencia do recurso de quem nao tem direito a
        ele. Um 403 aqui ja contaria que aquela conta existe.
        """
        _dono, conta_da_ana = cliente_com_conta(5000)
        bruno, _conta_do_bruno = cliente_com_conta()

        status, corpo = RequestGenerator.GET_account(
            conta_da_ana, credential=token_de_cliente(bruno)
        )

        assert status == 404
        assert corpo["code"] == "QIT002010"
        assert "balance" not in corpo

    def test_f7_03_extrato_de_outro_cliente_responde_404(self):
        _dono, conta_da_ana = cliente_com_conta(5000)
        bruno, _conta_do_bruno = cliente_com_conta()

        status, corpo = RequestGenerator.GET_statement(
            conta_da_ana, credential=token_de_cliente(bruno)
        )

        assert status == 404
        assert corpo["code"] == "QIT002010"
        assert "data" not in corpo


class TestAuthorizationCredential:
    """A credencial em si: sem ela, forjada, vencida ou com alg none."""

    def test_f7_04_sem_credencial_a_conta_nao_abre(self):
        _customer_key, account_key = cliente_com_conta()

        status, corpo = RequestGenerator.GET_account_sem_credencial(account_key)

        assert status == 401
        assert corpo["code"] == "QIT000003"

    def test_f7_05_credencial_assinada_com_outro_segredo_e_recusada(self):
        customer_key, account_key = cliente_com_conta()

        status, corpo = RequestGenerator.GET_account(
            account_key, credential=token_com_outro_segredo(customer_key)
        )

        assert status == 401
        assert corpo["code"] == "QIT000004"

    def test_f7_06_credencial_vencida_e_recusada(self):
        customer_key, account_key = cliente_com_conta()

        status, corpo = RequestGenerator.GET_account(
            account_key, credential=token_vencido(customer_key)
        )

        assert status == 401
        assert corpo["code"] == "QIT000005"

    def test_f7_07_credencial_com_alg_none_e_recusada(self):
        """O ataque classico de JWT: trocar o algoritmo por none.

        Quem decodifica sem fixar algorithms=["HS256"] aceita um token
        sem assinatura nenhuma e confia no sub que o atacante escreveu.
        """
        customer_key, account_key = cliente_com_conta()

        status, corpo = RequestGenerator.GET_account(
            account_key, credential=token_com_alg_none(customer_key)
        )

        assert status == 401
        assert corpo["code"] == "QIT000004"


class TestAuthorizationTransaction:
    """Mover dinheiro de conta alheia e o caso que custa caro."""

    def test_f7_08_transferencia_de_conta_que_nao_e_sua_responde_404(self):
        define_tarifa(200)
        _ana, conta_da_ana = cliente_com_conta(100000)
        bruno, conta_do_bruno = cliente_com_conta()

        status, corpo = RequestGenerator.POST_transaction(
            {
                "type": "TRANSFER",
                "origin_account_key": conta_da_ana,
                "destination_account_key": conta_do_bruno,
                "amount": 10000,
            },
            idempotency_key=str(uuid4()),
            credential=token_de_cliente(bruno),
        )

        assert status == 404
        assert corpo["code"] == "QIT002010"
        assert saldo_pelo_operador(conta_da_ana) == 100000, "nenhum centavo pode ter saido"
        assert saldo_pelo_operador(conta_do_bruno) == 0

    def test_f7_09_transferencia_para_conta_de_outro_e_permitida(self):
        """O destino nao precisa ser seu, senao transferencia nao existiria."""
        define_tarifa(200)
        ana, conta_da_ana = cliente_com_conta(100000)
        _bruno, conta_do_bruno = cliente_com_conta()

        status, corpo = RequestGenerator.POST_transaction(
            {
                "type": "TRANSFER",
                "origin_account_key": conta_da_ana,
                "destination_account_key": conta_do_bruno,
                "amount": 10000,
            },
            idempotency_key=str(uuid4()),
            credential=token_de_cliente(ana),
        )

        assert status == 201, corpo
        assert saldo_pelo_operador(conta_da_ana) == 89800
        assert saldo_pelo_operador(conta_do_bruno) == 10000

    def test_f7_10_deposito_com_credencial_de_cliente_e_recusado(self):
        """403 e nao 404: falta permissao para a operacao.

        Nao ha recurso de outra pessoa a esconder aqui. A conta e dele
        mesmo; o que ele nao pode e criar dinheiro.
        """
        ana, conta_da_ana = cliente_com_conta()

        status, corpo = RequestGenerator.POST_transaction(
            {"type": "DEPOSIT", "destination_account_key": conta_da_ana, "amount": 50000},
            idempotency_key=str(uuid4()),
            credential=token_de_cliente(ana),
        )

        assert status == 403
        assert corpo["code"] == "QIT000006"
        assert saldo_pelo_operador(conta_da_ana) == 0

    def test_f7_11_operador_deposita_em_qualquer_conta(self):
        _ana, conta_da_ana = cliente_com_conta()

        status, corpo = RequestGenerator.POST_transaction(
            {"type": "DEPOSIT", "destination_account_key": conta_da_ana, "amount": 50000},
            idempotency_key=str(uuid4()),
            credential=token_de_operador(),
        )

        assert status == 201, corpo
        assert saldo_pelo_operador(conta_da_ana) == 50000

    def test_f7_12_comprovante_de_transacao_alheia_responde_404(self):
        define_tarifa(200)
        ana, conta_da_ana = cliente_com_conta(100000)
        _bruno, conta_do_bruno = cliente_com_conta()
        carlos, _conta_do_carlos = cliente_com_conta()

        status, transacao = RequestGenerator.POST_transaction(
            {
                "type": "TRANSFER",
                "origin_account_key": conta_da_ana,
                "destination_account_key": conta_do_bruno,
                "amount": 10000,
            },
            idempotency_key=str(uuid4()),
            credential=token_de_cliente(ana),
        )
        assert status == 201, transacao

        status, corpo = RequestGenerator.GET_transaction(
            transacao["transaction_key"], credential=token_de_cliente(carlos)
        )

        assert status == 404
        assert corpo["code"] == "QIT002010"
