from sqlalchemy import BigInteger, CHAR, Column, DateTime, UniqueConstraint, func

from models.base import Base


class FeePolicy(Base):
    """A tarifa vigente. Append-only: nao se edita, cria-se outra.

    A transacao guarda qual politica usou. E o que permite provar,
    depois de a tarifa mudar, por que aquela transferencia cobrou
    aquele valor.
    """

    __tablename__ = "fee_policy"

    id = Column(BigInteger, primary_key=True)
    fee_policy_key = Column(CHAR(36), nullable=False, unique=True)
    transfer_fee_cents = Column(BigInteger, nullable=False)
    valid_from = Column(DateTime(timezone=True), nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())

    __table_args__ = (UniqueConstraint("fee_policy_key"),)
