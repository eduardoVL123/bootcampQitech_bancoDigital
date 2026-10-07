from sqlalchemy.exc import IntegrityError

from constants import STATEMENT_DEFAULT_LIMIT
from controllers.base_controller import BaseController
from errors import NotFoundAccount, NotFoundCustomer
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

    def get_by_key(self, account_key: str):
        account = self.account_repo.get_by_key(account_key)
        if not account:
            raise NotFoundAccount(account_key)
        return account

    def statement(self, account_key: str, query_params: dict) -> tuple:
        """Uma pagina do extrato, e o cursor da proxima.

        A conta e conferida antes de tudo: extrato de conta que nao
        existe e 404, e nao uma lista vazia, que esconderia o erro.
        """
        account = self.get_by_key(account_key)

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
