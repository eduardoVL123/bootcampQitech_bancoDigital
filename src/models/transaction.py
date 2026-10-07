from sqlalchemy import BigInteger, CHAR, Column, DateTime, ForeignKey, String, UniqueConstraint, func
from sqlalchemy.orm import relationship

from models.account import Account
from models.base import Base
from models.fee_policy import FeePolicy
from models.transaction_status import TransactionStatus
from models.transaction_type import TransactionType


class Transaction(Base):
    """O cabecalho: o que foi PEDIDO. O que ACONTECEU esta no livro.

    O `idempotency_key` e unico: e ele que impede o clique duplo virar
    duas transferencias. O `request_hash` guarda o SHA-256 do pedido, e
    nao o pedido: mesma chave com outro hash e conflito, e nenhum dado
    pessoal fica guardado aqui.

    O `fee_amount` e copiado da politica no momento da operacao e nunca
    recalculado depois.
    """

    __tablename__ = "transaction"

    id = Column(BigInteger, primary_key=True)
    transaction_key = Column(CHAR(36), nullable=False, unique=True)
    idempotency_key = Column(String(64), nullable=False, unique=True)
    request_hash = Column(CHAR(64), nullable=False)
    type_id = Column(BigInteger, ForeignKey(TransactionType.id), nullable=False)
    status_id = Column(BigInteger, ForeignKey(TransactionStatus.id), nullable=False)
    fee_policy_id = Column(BigInteger, ForeignKey(FeePolicy.id), nullable=True)
    origin_account_id = Column(BigInteger, ForeignKey(Account.id), nullable=True)
    destination_account_id = Column(BigInteger, ForeignKey(Account.id), nullable=True)
    amount = Column(BigInteger, nullable=False)
    fee_amount = Column(BigInteger, nullable=False, server_default="0")
    failure_code = Column(String(9), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at = Column(DateTime(timezone=True), nullable=True, onupdate=func.now())

    __table_args__ = (
        UniqueConstraint("transaction_key"),
        UniqueConstraint("idempotency_key"),
    )

    type = relationship("TransactionType", foreign_keys=[type_id], lazy="selectin")
    status = relationship("TransactionStatus", foreign_keys=[status_id], lazy="selectin")
    fee_policy = relationship("FeePolicy", foreign_keys=[fee_policy_id], lazy="selectin")
    origin_account = relationship("Account", foreign_keys=[origin_account_id], lazy="selectin")
    destination_account = relationship("Account", foreign_keys=[destination_account_id], lazy="selectin")

    status_events = relationship(
        "TransactionStatusEvent",
        back_populates="transaction",
        order_by="TransactionStatusEvent.id",
        lazy="selectin",
    )
