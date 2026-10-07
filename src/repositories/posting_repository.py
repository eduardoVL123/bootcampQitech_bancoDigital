from datetime import datetime, timezone
from uuid import uuid4

from database import Context
from models import Account, LedgerEntry, Posting, PostingType


class PostingRepository:
    """Busca, trava e grava. Nao decide nada."""

    def __init__(self, context: Context) -> None:
        self.session = context.db_session

    def get_type(self, enumerator: str) -> PostingType:
        return self.session.query(PostingType).filter(
            PostingType.enumerator == enumerator
        ).one()

    def get_by_key(self, posting_key: str) -> Posting:
        return self.session.query(Posting).filter(
            Posting.posting_key == posting_key
        ).first()

    def get_accounts_for_update(self, account_ids: list) -> list:
        """Trava as contas, SEMPRE em ordem crescente de id.

        A ordem nao e detalhe: duas transferencias, uma de A para B e
        outra de B para A ao mesmo tempo, travariam cada uma a primeira
        conta e esperariam para sempre pela segunda. Pelo id, as duas
        pedem na mesma ordem e uma espera a outra terminar.

        O populate_existing tambem nao e detalhe: sem ele, se a conta
        tiver sido lida antes nesta mesma sessao, o identity map do
        SQLAlchemy devolve o objeto em cache, com o SALDO ANTIGO. A
        trava estaria certa no banco e a decisao sairia errada.
        """
        return (
            self.session.query(Account)
            .filter(Account.id.in_(account_ids))
            .order_by(Account.id)
            .with_for_update()
            .populate_existing()
            .all()
        )

    def get_account_by_key(self, account_key: str) -> Account:
        return self.session.query(Account).filter(
            Account.account_key == account_key
        ).first()

    def get_account_by_code(self, code: str) -> Account:
        return self.session.query(Account).filter(Account.code == code).first()

    def create_posting(self, posting_key: str, type_enumerator: str, transaction_id=None) -> Posting:
        posting = Posting()
        posting.posting_key = posting_key
        posting.type_id = self.get_type(type_enumerator).id
        posting.transaction_id = transaction_id

        self.session.add(posting)
        self.session.flush()
        return posting

    def add_entry(self, posting_id: int, account: Account, amount: int) -> LedgerEntry:
        """Um lancamento. Conta de cliente anda o saldo; conta tecnica nao.

        Conta tecnica tem balance nulo, entao nao ha linha de saldo para
        travar nem numero de ordem para gerar: o lancamento e um INSERT
        puro. E isso que impede a conta de tarifa de serializar toda
        transferencia do sistema.
        """
        entry = LedgerEntry()
        entry.entry_key = str(uuid4())
        entry.posting_id = posting_id
        entry.account_id = account.id
        entry.amount = amount

        if account.balance is not None:
            account.balance += amount
            account.last_sequence += 1
            account.updated_at = datetime.now(timezone.utc)
            entry.balance_after = account.balance
            entry.sequence = account.last_sequence

        self.session.add(entry)
        return entry

    def reconciliation(self) -> dict:
        """A soma de TODOS os lancamentos de TODAS as contas.

        Tem de dar zero. Nao e relatorio: e a verificacao de que nenhum
        centavo entrou ou saiu do sistema sem contrapartida.
        """
        from sqlalchemy import func

        total, quantidade = self.session.query(
            func.coalesce(func.sum(LedgerEntry.amount), 0),
            func.count(LedgerEntry.id),
        ).one()
        return {"total": int(total), "entry_count": int(quantidade)}
