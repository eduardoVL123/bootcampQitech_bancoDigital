"""Quem e o dono de cada conta que ESTE teste criou.

A R8 faz as rotas de cliente exigirem credencial, e a credencial certa
e a do titular. Em vez de espalhar o token por 120 chamadas, o
RequestGenerator lembra quem abriu cada conta e manda a credencial dela
por padrao. O teste que quer agir como OUTRA pessoa passa a credencial
na mao, e e exatamente isso que a fatia F7 faz.

Isto e preparacao de teste, nao assercao: nenhum teste prova nada por
causa deste arquivo. Quem prova que a credencial e obrigatoria e o
F7-04, que manda a requisicao sem nenhuma.
"""

from tests.utils.credential import token_de_cliente, token_de_operador

_dono_da_conta = {}
_conta_da_transacao = {}


def registra_conta(account_key: str, customer_key: str) -> None:
    if account_key and customer_key:
        _dono_da_conta[str(account_key).strip()] = str(customer_key).strip()


def registra_transacao(transaction_key: str, account_key: str) -> None:
    if transaction_key and account_key:
        _conta_da_transacao[str(transaction_key).strip()] = str(account_key).strip()


def credencial_da_conta(account_key: str) -> str:
    """A credencial do titular. Conta desconhecida cai no operador.

    Conta desconhecida e, na pratica, chave inventada: o teste quer o
    404, e o operador tambem recebe 404 numa conta que nao existe.
    """
    customer_key = _dono_da_conta.get(str(account_key).strip())
    if customer_key:
        return token_de_cliente(customer_key)
    return token_de_operador()


def credencial_da_transacao(transaction_key: str) -> str:
    account_key = _conta_da_transacao.get(str(transaction_key).strip())
    if account_key:
        return credencial_da_conta(account_key)
    return token_de_operador()
