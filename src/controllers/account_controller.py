from sqlalchemy.exc import IntegrityError

from controllers.base_controller import BaseController
from errors import NotFoundAccount, NotFoundCustomer
from repositories import AccountRepository, CustomerRepository


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
