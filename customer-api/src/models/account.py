from sqlalchemy import BigInteger, CHAR, Column, DateTime, ForeignKey, String, UniqueConstraint, func
from sqlalchemy.orm import relationship

from models.account_status import AccountStatus
from models.base import Base
from models.customer import Customer


class Account(Base):
    """A conta. De cliente ou tecnica do banco, nunca as duas.

    Conta de cliente tem `customer_id`, `balance` e `last_sequence`.
    Conta tecnica tem `code` e os outros tres nulos, de proposito: sem
    linha de saldo nao ha o que travar, e a conta de tarifa deixa de
    serializar toda transferencia do sistema. O saldo dela sai da soma
    do livro, e ninguem consulta esse saldo em tempo real.

    O `balance` e um atalho de leitura. A verdade historica e o
    `ledger_entry`, e os dois sao escritos no mesmo commit.
    """

    __tablename__ = "account"

    id = Column(BigInteger, primary_key=True)
    account_key = Column(CHAR(36), nullable=False, unique=True)
    customer_id = Column(BigInteger, ForeignKey(Customer.id), nullable=True)
    code = Column(String(30), nullable=True, unique=True)
    status_id = Column(BigInteger, ForeignKey(AccountStatus.id), nullable=False)
    balance = Column(BigInteger, nullable=True)
    last_sequence = Column(BigInteger, nullable=False, server_default="0")
    closed_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at = Column(DateTime(timezone=True), nullable=True, onupdate=func.now())

    __table_args__ = (
        UniqueConstraint("account_key"),
        UniqueConstraint("code"),
    )

    status = relationship("AccountStatus", foreign_keys=[status_id], lazy="selectin")
    customer = relationship("Customer", foreign_keys=[customer_id], lazy="selectin")

    status_events = relationship(
        "AccountStatusEvent",
        back_populates="account",
        order_by="AccountStatusEvent.id",
        lazy="selectin",
    )

    FEE_HOLD = "FEE_HOLD"
    FEE_REVENUE = "FEE_REVENUE"
    SETTLEMENT = "SETTLEMENT"
