from uuid import uuid4

from tests.utils import PayloadGenerator, RequestGenerator


def conta_com_depositos(quantidade: int, valor: int = 1000) -> str:
    """Uma conta com N depositos, pela porta da frente.

    Cada deposito gera um lancamento na conta do cliente. Sao eles que
    o extrato pagina.
    """
    _status, cliente = RequestGenerator.POST_customer(PayloadGenerator.create_customer_payload())
    status, conta = RequestGenerator.POST_account({"customer_key": cliente["customer_key"]})
    assert status == 201, f"nao consegui preparar a conta: {conta}"

    for _ in range(quantidade):
        status, corpo = RequestGenerator.POST_transaction(
            {"type": "DEPOSIT", "destination_account_key": conta["account_key"], "amount": valor},
            idempotency_key=str(uuid4()),
        )
        assert status == 201, f"nao consegui depositar: {corpo}"

    return conta["account_key"]


class TestStatement:
    """F4: o extrato, paginado por cursor opaco e assinado."""

    def test_f4_01_traz_os_lancamentos_da_conta_do_mais_novo_para_o_mais_velho(self):
        account_key = conta_com_depositos(3)

        status, corpo = RequestGenerator.GET_statement(account_key)

        assert status == 200
        assert len(corpo["data"]) == 3
        sequencias = [linha["sequence"] for linha in corpo["data"]]
        assert sequencias == [3, 2, 1], f"mais novo primeiro, veio {sequencias}"

    def test_f4_02_cada_linha_traz_o_saldo_depois_dela(self):
        """E o que faz o extrato provar o saldo sozinho.

        Ninguem precisa recalcular nada: a linha mais nova ja diz quanto
        a conta tinha depois dela, e esse numero bate com o saldo atual.
        """
        account_key = conta_com_depositos(3, valor=1000)

        _status, extrato = RequestGenerator.GET_statement(account_key)
        _status, conta = RequestGenerator.GET_account(account_key)

        assert [linha["balance_after"] for linha in extrato["data"]] == [3000, 2000, 1000]
        assert extrato["data"][0]["balance_after"] == conta["balance"]

    def test_f4_03_pagina_por_cursor_sem_repetir_item(self):
        account_key = conta_com_depositos(5)

        _status, primeira = RequestGenerator.GET_statement(account_key, {"limit": 2})
        assert len(primeira["data"]) == 2
        assert primeira["is_last_page"] is False
        assert primeira["next_cursor"] is not None

        _status, segunda = RequestGenerator.GET_statement(
            account_key, {"limit": 2, "cursor": primeira["next_cursor"]}
        )

        chaves_primeira = {linha["entry_key"] for linha in primeira["data"]}
        chaves_segunda = {linha["entry_key"] for linha in segunda["data"]}
        assert not (chaves_primeira & chaves_segunda), "nenhum item pode aparecer nas duas paginas"
        assert [linha["sequence"] for linha in segunda["data"]] == [3, 2]

    def test_f4_04_ultima_pagina_se_anuncia(self):
        account_key = conta_com_depositos(3)

        _status, primeira = RequestGenerator.GET_statement(account_key, {"limit": 2})
        _status, segunda = RequestGenerator.GET_statement(
            account_key, {"limit": 2, "cursor": primeira["next_cursor"]}
        )

        assert len(segunda["data"]) == 1
        assert segunda["is_last_page"] is True
        assert segunda["next_cursor"] is None

    def test_f4_05_extrato_estavel_enquanto_chegam_lancamentos(self):
        """O motivo de ser cursor e nao OFFSET.

        Com OFFSET 2, os lancamentos novos empurrariam a janela e o
        cliente veria de novo, na segunda pagina, itens que ja viu na
        primeira. O cursor aponta para um numero de ordem que nao se
        move: o livro e append-only, e a sequencia de uma linha nunca
        muda.
        """
        account_key = conta_com_depositos(5)

        _status, primeira = RequestGenerator.GET_statement(account_key, {"limit": 2})
        chaves_primeira = {linha["entry_key"] for linha in primeira["data"]}

        # Chegam tres lancamentos novos entre uma pagina e a seguinte.
        for _ in range(3):
            RequestGenerator.POST_transaction(
                {"type": "DEPOSIT", "destination_account_key": account_key, "amount": 500},
                idempotency_key=str(uuid4()),
            )

        _status, segunda = RequestGenerator.GET_statement(
            account_key, {"limit": 2, "cursor": primeira["next_cursor"]}
        )
        chaves_segunda = {linha["entry_key"] for linha in segunda["data"]}

        assert not (chaves_primeira & chaves_segunda), "nada pode repetir entre as paginas"
        assert [linha["sequence"] for linha in segunda["data"]] == [3, 2]

    def test_f4_06_recusa_cursor_adulterado(self):
        """Sem assinatura, daria para montar um cursor a mao e espiar outra conta."""
        account_key = conta_com_depositos(3)

        _status, primeira = RequestGenerator.GET_statement(account_key, {"limit": 1})
        adulterado = primeira["next_cursor"][:-4] + "aaaa"

        status, corpo = RequestGenerator.GET_statement(account_key, {"cursor": adulterado})

        assert status == 400
        assert corpo["code"] == "QIT002015"

    def test_f4_07_recusa_cursor_de_outra_conta(self):
        """O cursor carrega a conta a que pertence, e nao vale em outra."""
        uma = conta_com_depositos(3)
        outra = conta_com_depositos(3)

        _status, primeira = RequestGenerator.GET_statement(uma, {"limit": 1})

        status, corpo = RequestGenerator.GET_statement(
            outra, {"cursor": primeira["next_cursor"]}
        )

        assert status == 400
        assert corpo["code"] == "QIT002015"

    def test_f4_08_recusa_limite_fora_do_intervalo(self):
        account_key = conta_com_depositos(1)

        for limite in [0, 101, "abc"]:
            status, corpo = RequestGenerator.GET_statement(account_key, {"limit": limite})
            assert status == 400, f"limit={limite} foi aceito"
            assert corpo["code"] == "QIT000001"

    def test_f4_09_conta_que_nao_existe_responde_404(self):
        status, corpo = RequestGenerator.GET_statement(str(uuid4()))

        assert status == 404
        assert corpo["code"] == "QIT002010"

    def test_f4_10_conta_sem_movimento_tem_extrato_vazio(self):
        account_key = conta_com_depositos(0)

        status, corpo = RequestGenerator.GET_statement(account_key)

        assert status == 200
        assert corpo["data"] == []
        assert corpo["is_last_page"] is True
        assert corpo["next_cursor"] is None
