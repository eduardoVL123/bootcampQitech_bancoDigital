from datetime import datetime, timezone
from uuid import uuid4

from database import Context
from models import (
    Account,
    AccountStatus,
    AccountStatusEvent,
    AccountStatusReason,
    LedgerEntry,
)


class AccountRepository:
    """A unica camada que fala com o banco sobre conta.

    Nenhuma regra de negocio mora aqui: busca, grava e trava. Quem
    decide o que fazer com isso e o controller.
    """

    def __init__(self, context: Context) -> None:
        self.session = context.db_session

    def get_status(self, enumerator: str) -> AccountStatus:
        return self.session.query(AccountStatus).filter(
            AccountStatus.enumerator == enumerator
        ).one()

    def get_by_key(self, account_key: str) -> Account:
        return self.session.query(Account).filter(
            Account.account_key == account_key
        ).first()

    def get_open_by_customer_id(self, customer_id: int) -> Account:
        """A conta nao encerrada deste cliente, se existir.

        E a mesma condicao do indice parcial account_one_open_per_customer:
        closed_at nulo. Se um dia a condicao do indice mudar, esta tem
        de mudar junto.
        """
        return self.session.query(Account).filter(
            Account.customer_id == customer_id,
            Account.closed_at.is_(None),
        ).first()

    def create(self, customer_id: int) -> Account:
        """Grava a conta e o evento de estado, sem commit.

        Quem fecha a transacao e o controller, que e o unico dono do
        commit. O flush manda o INSERT agora para que a violacao do
        indice unico aconteca aqui, e nao so no commit: e assim que o
        controller consegue tratar o pedido repetido.
        """
        ativa = self.get_status(AccountStatus.ACTIVE)

        account = Account()
        account.account_key = str(uuid4())
        account.customer_id = customer_id
        account.status_id = ativa.id
        account.balance = 0
        account.last_sequence = 0

        self.session.add(account)
        self.session.flush()

        self.session.add(
            AccountStatusEvent(
                account_id=account.id,
                status_id=ativa.id,
                event_datetime=datetime.now(timezone.utc),
            )
        )
        self.session.flush()

        return account

    def get_statement_page(self, account_id: int, limit: int, before_sequence: int = None) -> tuple:
        """Uma pagina do livro desta conta, do mais novo para o mais velho.

        Pede limit + 1 linhas de proposito: a linha a mais nao vai na
        resposta, ela so responde "existe proxima pagina?". Sem ela
        seria preciso um COUNT sobre o livro inteiro a cada pagina.

        Nao pede trava: um GET nao espera ninguem. O livro e append-only,
        entao as linhas que esta consulta ve nunca mudam depois.
        """
        consulta = self.session.query(LedgerEntry).filter(
            LedgerEntry.account_id == account_id,
            LedgerEntry.sequence.isnot(None),
        )

        if before_sequence is not None:
            consulta = consulta.filter(LedgerEntry.sequence < before_sequence)

        linhas = consulta.order_by(LedgerEntry.sequence.desc()).limit(limit + 1).all()

        tem_proxima = len(linhas) > limit
        return linhas[:limit], tem_proxima

    def get_by_key_for_update(self, account_key: str) -> Account:
        """A conta travada, para decidir estado em cima do saldo de agora.

        Sem a trava, encerrar e transferir ao mesmo tempo passariam as
        duas: a conferencia de saldo zero leria um saldo que a
        transferencia esta prestes a mudar. O populate_existing garante
        que a leitura vem do banco, e nao do identity map.
        """
        return (
            self.session.query(Account)
            .filter(Account.account_key == account_key)
            .with_for_update()
            .populate_existing()
            .first()
        )

    def get_reason(self, enumerator: str) -> AccountStatusReason:
        return self.session.query(AccountStatusReason).filter(
            AccountStatusReason.enumerator == enumerator
        ).one()

    def change_status(self, account: Account, status_enumerator: str, reason_enumerator: str):
        """Muda o estado e grava o evento, na mesma transacao. Sem commit.

        Encerrar preenche closed_at, que e a coluna que o indice
        account_one_open_per_customer olha. Sem ela, o cliente que
        encerrou nunca mais abriria conta.
        """
        novo = self.get_status(status_enumerator)
        agora = datetime.now(timezone.utc)

        account.status_id = novo.id
        account.updated_at = agora
        if status_enumerator == AccountStatus.CLOSED:
            account.closed_at = agora

        self.session.add(
            AccountStatusEvent(
                account_id=account.id,
                status_id=novo.id,
                reason_id=self.get_reason(reason_enumerator).id,
                event_datetime=agora,
            )
        )
        self.session.flush()
        return account
