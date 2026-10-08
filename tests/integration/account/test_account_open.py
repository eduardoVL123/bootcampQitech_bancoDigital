from uuid import UUID, uuid4

from tests.utils import PayloadGenerator, RequestGenerator
from tests.utils.run_at_the_same_time import run_at_the_same_time


def cria_cliente() -> str:
    """Prepara pela porta da frente: um cliente de verdade, pela rota.

    Nada de INSERT no banco. Assim a preparacao tambem passa pelas
    regras, e o teste quebra se a criacao de cliente quebrar.
    """
    status, corpo = RequestGenerator.POST_customer(PayloadGenerator.create_customer_payload())
    assert status == 201, f"nao consegui preparar o cliente: {status} {corpo}"
    return corpo["customer_key"]


def e_uuid(valor: str) -> bool:
    try:
        UUID(str(valor))
        return True
    except (ValueError, TypeError, AttributeError):
        return False


class TestAccountOpen:
    """F1: abrir a conta e ler o saldo.

    Sem conta nao existe lancamento, nem extrato, nem transferencia.
    Por isso esta fatia vem antes de todas.
    """

    def test_f1_01_abre_conta_para_cliente_novo(self):
        customer_key = cria_cliente()

        status, corpo = RequestGenerator.POST_account({"customer_key": customer_key})

        assert status == 201
        assert e_uuid(corpo["account_key"])
        assert corpo["balance"] == 0
        assert corpo["status"] == "ACTIVE"

    def test_f1_02_resposta_traz_so_os_campos_do_contrato(self):
        """R5: o id interno nunca sai na resposta."""
        customer_key = cria_cliente()

        _status, corpo = RequestGenerator.POST_account({"customer_key": customer_key})

        assert set(corpo.keys()) == {"account_key", "balance", "status"}

    def test_f1_03_consulta_a_conta_recem_aberta(self):
        customer_key = cria_cliente()
        _status, criada = RequestGenerator.POST_account({"customer_key": customer_key})

        status, corpo = RequestGenerator.GET_account(criada["account_key"])

        assert status == 200
        assert corpo["account_key"] == criada["account_key"]
        assert corpo["balance"] == 0
        assert corpo["status"] == "ACTIVE"

    def test_f1_04_abertura_grava_o_evento_de_estado(self):
        """Estado e tabela de lookup mais evento, gravados no mesmo commit."""
        customer_key = cria_cliente()
        _status, criada = RequestGenerator.POST_account({"customer_key": customer_key})

        _status, corpo = RequestGenerator.GET_account(criada["account_key"])

        assert len(corpo["status_events"]) == 1
        assert corpo["status_events"][0]["status"] == "ACTIVE"
        assert corpo["status_events"][0]["event_datetime"] is not None

    def test_f1_05_abrir_duas_vezes_para_o_mesmo_cliente_devolve_a_mesma_conta(self):
        """E o contrato que a onboarding-api usa: 201 conta nova, 200 a que ja existia.

        Quem garante nao e um if no controller: e o indice unico parcial
        account_one_open_per_customer. Entre consultar e gravar cabe
        outra requisicao.
        """
        customer_key = cria_cliente()

        primeiro_status, primeira = RequestGenerator.POST_account({"customer_key": customer_key})
        segundo_status, segunda = RequestGenerator.POST_account({"customer_key": customer_key})

        assert primeiro_status == 201
        assert segundo_status == 200
        assert segunda["account_key"] == primeira["account_key"]

    def test_f1_07_recusa_cliente_que_nao_existe(self):
        status, corpo = RequestGenerator.POST_account({"customer_key": str(uuid4())})

        assert status == 404
        assert corpo["code"] == "QIT002001"

    def test_f1_08_recusa_customer_key_fora_do_formato(self):
        status, corpo = RequestGenerator.POST_account({"customer_key": "nao-sou-uuid"})

        assert status == 400
        assert corpo["code"] == "QIT000001"

    def test_f1_09_recusa_campo_a_mais(self):
        """additionalProperties: false. Ninguem escolhe o proprio saldo."""
        customer_key = cria_cliente()

        status, corpo = RequestGenerator.POST_account(
            {"customer_key": customer_key, "balance": 100000}
        )

        assert status == 400
        assert corpo["code"] == "QIT000001"

    def test_f1_10_conta_que_nao_existe_responde_404(self):
        status, corpo = RequestGenerator.GET_account(str(uuid4()))

        assert status == 404
        assert corpo["code"] == "QIT002010"

    def test_f1_11_sem_token_do_aplicativo_nada_passa(self):
        status, corpo = RequestGenerator.POST_account_sem_token({"customer_key": str(uuid4())})

        assert status == 403
        assert corpo["code"] == "QIT000002"


class TestAccountOpenConcurrency:
    """F1-06: dois pedidos no mesmo instante abrem uma conta so."""

    def test_f1_06_dez_pedidos_simultaneos_abrem_uma_conta_so(self):
        """Dez no mesmo instante, nao dois.

        Com dois, a janela entre consultar e gravar e tao curta que um
        codigo errado passa por sorte: provei isso mutando o controller
        para "consultar antes de gravar" e o teste continuou verde. Com
        dez, o indice unico parcial e exercitado de verdade.

        Dez, e nao mil: o pool da API e de 5 mais overflow, e cada
        requisicao parada esperando a trava segura uma conexao.
        """
        customer_key = cria_cliente()

        respostas = run_at_the_same_time(
            RequestGenerator.POST_account, [{"customer_key": customer_key}] * 10
        )

        status = [r[0] for r in respostas]
        criadas = [s for s in status if s == 201]
        existentes = [s for s in status if s == 200]

        assert not [s for s in status if s >= 500], f"ninguem pode receber 5xx: {status}"
        assert len(criadas) == 1, f"exatamente uma conta nasce, veio {status}"
        assert len(existentes) == 9, f"as outras nove acham a que existe, veio {status}"

        chaves = {r[1]["account_key"] for r in respostas}
        assert len(chaves) == 1, "as dez respostas tem de apontar para a mesma conta"
