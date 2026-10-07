from datetime import datetime, timezone
from uuid import uuid4

from database import Context
from models import FeePolicy, Transaction, TransactionStatus, TransactionStatusEvent, TransactionType


class TransactionRepository:
    def __init__(self, context: Context) -> None:
        self.session = context.db_session

    def get_type(self, enumerator: str) -> TransactionType:
        return self.session.query(TransactionType).filter(
            TransactionType.enumerator == enumerator
        ).one()

    def get_status(self, enumerator: str) -> TransactionStatus:
        return self.session.query(TransactionStatus).filter(
            TransactionStatus.enumerator == enumerator
        ).one()

    def get_by_idempotency_key(self, idempotency_key: str) -> Transaction:
        return self.session.query(Transaction).filter(
            Transaction.idempotency_key == idempotency_key
        ).first()

    def get_by_key(self, transaction_key: str) -> Transaction:
        return self.session.query(Transaction).filter(
            Transaction.transaction_key == transaction_key
        ).first()

    def get_current_fee_policy(self) -> FeePolicy:
        """A politica vigente e a mais recente que ja entrou em vigor."""
        return (
            self.session.query(FeePolicy)
            .filter(FeePolicy.valid_from <= datetime.now(timezone.utc))
            .order_by(FeePolicy.valid_from.desc(), FeePolicy.id.desc())
            .first()
        )

    def create_fee_policy(self, transfer_fee_cents: int) -> FeePolicy:
        """Tarifa nao se edita: cria-se outra.

        A trigger fee_policy_is_append_only recusa UPDATE nesta tabela.
        E o que faz a tarifa de ontem sobreviver a mudanca de hoje.
        """
        politica = FeePolicy()
        politica.fee_policy_key = str(uuid4())
        politica.transfer_fee_cents = transfer_fee_cents
        politica.valid_from = datetime.now(timezone.utc)

        self.session.add(politica)
        self.session.flush()
        return politica

    def create(self, dados: dict) -> Transaction:
        """Grava o cabecalho como PENDING e o evento, sem commit.

        O flush manda o INSERT agora para que a violacao do
        UNIQUE(idempotency_key) aconteca aqui: e assim que o controller
        reconhece o pedido repetido.
        """
        pendente = self.get_status(TransactionStatus.PENDING)

        transaction = Transaction()
        transaction.transaction_key = str(uuid4())
        transaction.idempotency_key = dados["idempotency_key"]
        transaction.request_hash = dados["request_hash"]
        transaction.type_id = self.get_type(dados["type"]).id
        transaction.status_id = pendente.id
        transaction.fee_policy_id = dados.get("fee_policy_id")
        transaction.origin_account_id = dados.get("origin_account_id")
        transaction.destination_account_id = dados.get("destination_account_id")
        transaction.amount = dados["amount"]
        transaction.fee_amount = dados["fee_amount"]

        self.session.add(transaction)
        self.session.flush()

        self._add_event(transaction, pendente.id)
        return transaction

    def mark_completed(self, transaction: Transaction) -> None:
        concluida = self.get_status(TransactionStatus.COMPLETED)
        transaction.status_id = concluida.id
        transaction.updated_at = datetime.now(timezone.utc)
        self._add_event(transaction, concluida.id)

    def _add_event(self, transaction: Transaction, status_id: int) -> None:
        self.session.add(
            TransactionStatusEvent(
                transaction_id=transaction.id,
                status_id=status_id,
                event_datetime=datetime.now(timezone.utc),
            )
        )
        self.session.flush()
