from sqlalchemy import BigInteger, Column, DateTime, ForeignKey, func
from sqlalchemy.orm import relationship

from models.base import Base
from models.transaction_status import TransactionStatus


class TransactionStatusEvent(Base):
    """O historico da transacao: PENDING, depois COMPLETED ou FAILED.

    A transacao tem status mutavel, por causa do protocolo de gravar
    PENDING antes de mexer no dinheiro. Nada e apagado: a trilha fica
    aqui, e e isso que cumpre a R4 sem append-only na transacao.
    """

    __tablename__ = "transaction_status_event"

    id = Column(BigInteger, primary_key=True)
    transaction_id = Column(BigInteger, ForeignKey("transaction.id"), nullable=False)
    status_id = Column(BigInteger, ForeignKey(TransactionStatus.id), nullable=False)
    event_datetime = Column(DateTime(timezone=True), nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())

    transaction = relationship("Transaction", back_populates="status_events")
    status = relationship("TransactionStatus", foreign_keys=[status_id], lazy="selectin")
