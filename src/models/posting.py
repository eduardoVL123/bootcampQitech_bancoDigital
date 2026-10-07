from sqlalchemy import BigInteger, CHAR, Column, DateTime, ForeignKey, UniqueConstraint, func
from sqlalchemy.orm import relationship

from models.base import Base
from models.posting_type import PostingType
from models.transaction import Transaction


class Posting(Base):
    """Um conjunto de lancamentos que SOMA ZERO, aplicado num commit so.

    Append-only: ha uma trigger no banco recusando UPDATE e DELETE.

    O UNIQUE em `transaction_id` e o que garante que uma transacao gera
    no maximo um conjunto de lancamentos. Nao e checagem no controller:
    entre o SELECT e o INSERT cabe outra requisicao, e o indice nao
    deixa passar.
    """

    __tablename__ = "posting"

    id = Column(BigInteger, primary_key=True)
    posting_key = Column(CHAR(36), nullable=False, unique=True)
    type_id = Column(BigInteger, ForeignKey(PostingType.id), nullable=False)
    transaction_id = Column(BigInteger, ForeignKey(Transaction.id), nullable=False, unique=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())

    __table_args__ = (
        UniqueConstraint("posting_key"),
        UniqueConstraint("transaction_id"),
    )

    type = relationship("PostingType", foreign_keys=[type_id], lazy="selectin")
    transaction = relationship("Transaction", foreign_keys=[transaction_id], lazy="selectin")

    entries = relationship(
        "LedgerEntry",
        back_populates="posting",
        order_by="LedgerEntry.id",
        lazy="selectin",
    )
