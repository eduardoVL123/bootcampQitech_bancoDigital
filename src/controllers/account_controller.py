from sqlalchemy.exc import IntegrityError

from constants import STATEMENT_DEFAULT_LIMIT
from controllers.base_controller import BaseController
from errors import (
    AccountHasBalance,
    InvalidStateTransition,
    NotFoundAccount,
    NotFoundCustomer,
)
from models import AccountStatus
from repositories import AccountRepository, CustomerRepository
from utils import statement_cursor


class AccountController(BaseController):
    def __init__(self) -> None:
        super().__init__(__name__)
        self.account_repo = AccountRepository(self.context)
        self.customer_repo = CustomerRepository(self.context)

    def open(self, payload: dict):
        """Abre a conta do cliente. No maximo uma nao encerrada por pessoa.

        Devolve (conta, ja_existia). O resource traduz isso em 201 ou 200,
        que e o contrato que a onboarding-api usa.

        A unicidade NAO e checada antes de gravar. Entre o SELECT e o
        INSERT cabe outra requisicao, e os dois pedidos passariam na
        checagem. Aqui a gente tenta gravar e trata a violacao do indice
        parcial: e o banco que decide quem chegou primeiro.
        """
        customer_key = payload["customer_key"]

        customer = self.customer_repo.get_by_key(customer_key)
        if not customer:
            raise NotFoundCustomer(customer_key)

        try:
            account = self.account_repo.create(customer.id)
            self.session.commit()
            return account, False
        except IntegrityError as erro:
            self.session.rollback()

            # Perdeu a corrida pelo indice, ou e um pedido repetido: a
            # conta que ja existe e a resposta certa, com 200.
            account = self.account_repo.get_open_by_customer_id(customer.id)
            if not account:
                # A violacao nao foi a do indice parcial: foi outra
                # coisa, e esconde-la viraria um 500 sem explicacao.
                raise erro
            return account, True

    def get_by_key(self, account_key: str, caller):
        """A conta, se ela existe E se e de quem esta pedindo (R8).

        O caller nao tem valor padrao de proposito. Rota nova que
        esqueca de passar quem esta pedindo quebra na hora, em vez de
        nascer aberta.
        """
        account = self.account_repo.get_by_key(account_key)
        if not account:
            raise NotFoundAccount(account_key)

        self._require_owner(account, account_key, caller)
        return account

    def _require_owner(self, account, account_key: str, caller) -> None:
        """Conta que nao e sua responde 404, nao 403.

        A MDN diz a frase: o servidor pode responder 404 em vez de 403
        para esconder a existencia do recurso de quem nao tem direito a
        ele. Um 403 aqui confirmaria que aquela conta existe, e e
        justamente isso que a R8 manda nao contar.

        A comparacao vai de quem pede para a conta, e nao o contrario:
        troca-se o sub da credencial pelo id interno do cliente e
        compara-se com o account.customer_id. Assim nao e preciso ler a
        tabela customer a partir da conta, e a conta continua sem
        depender do modelo de cliente para decidir.
        """
        if caller.is_operator:
            return

        customer = self.customer_repo.get_by_key(caller.subject)
        if customer is None or account.customer_id != customer.id:
            raise NotFoundAccount(account_key)

    def change_status(self, account_key: str, payload: dict, caller):
        """Bloqueia, desbloqueia ou encerra. Só operador.

        A ordem dos passos importa:

        1. O escopo é conferido antes de tudo: é a recusa mais barata, e
           não precisa nem saber se a conta existe.
        2. A conta é lida JÁ TRAVADA. Encerrar decide em cima do saldo,
           e sem a trava uma transferência simultânea mudaria o saldo
           entre a conferência e a escrita.
        3. Pedir o estado que a conta já tem sai aqui, com 200 e sem
           gravar evento: PATCH é idempotente por definição no HTTP, e
           repetir o pedido não pode inflar o histórico.
        4. A transição é conferida depois da trava, com o estado de
           agora.
        5. O commit é a última linha, e é o que libera a trava.
        """
        caller.require_operator()

        novo_status = payload["status"]

        account = self.account_repo.get_by_key_for_update(account_key)
        if not account:
            raise NotFoundAccount(account_key)

        atual = account.status.enumerator
        if atual == novo_status:
            return account

        self._check_transition(account, atual, novo_status)

        self.account_repo.change_status(account, novo_status, payload["reason"])
        self.session.commit()
        return account

    def _check_transition(self, account, atual: str, novo: str) -> None:
        """As duas únicas regras de transição que existem.

        CLOSED é terminal: conta encerrada que reabre apagaria a
        história. Para ter conta de novo, o cliente abre uma nova, e o
        índice único parcial deixa porque ele olha o closed_at.

        E encerrar exige saldo zero: o que sobrou é do cliente, e
        encerrar com saldo sumiria com o dinheiro dele.
        """
        if atual == AccountStatus.CLOSED:
            raise InvalidStateTransition(atual, novo)

        if novo == AccountStatus.CLOSED and account.balance:
            raise AccountHasBalance(account.account_key.strip(), account.balance)

    def statement(self, account_key: str, query_params: dict, caller) -> tuple:
        """Uma pagina do extrato, e o cursor da proxima.

        A conta e conferida antes de tudo: extrato de conta que nao
        existe e 404, e nao uma lista vazia, que esconderia o erro.
        """
        account = self.get_by_key(account_key, caller)

        limit = int(query_params.get("limit", STATEMENT_DEFAULT_LIMIT))

        before_sequence = None
        if query_params.get("cursor"):
            before_sequence = statement_cursor.decode(query_params["cursor"], account_key)

        linhas, tem_proxima = self.account_repo.get_statement_page(
            account.id, limit, before_sequence
        )

        next_cursor = None
        if tem_proxima and linhas:
            next_cursor = statement_cursor.encode(account_key, linhas[-1].sequence)

        return linhas, next_cursor
