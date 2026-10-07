from sqlalchemy import BigInteger, Column, DateTime, ForeignKey, func
from sqlalchemy.orm import relationship

from models.account_status import AccountStatus
from models.account_status_reason import AccountStatusReason
from models.base import Base


class AccountStatusEvent(Base):
    """O historico de estados da conta. So recebe INSERT.

    Gravado na mesma transacao da mudanca de estado: se o estado mudou,
    o evento existe. O `reason_id` e nulo na abertura, porque abrir
    conta nao tem motivo a registrar.
    """

    __tablename__ = "account_status_event"

    id = Column(BigInteger, primary_key=True)
    account_id = Column(BigInteger, ForeignKey("account.id"), nullable=False)
    status_id = Column(BigInteger, ForeignKey(AccountStatus.id), nullable=False)
    reason_id = Column(BigInteger, ForeignKey(AccountStatusReason.id), nullable=True)
    event_datetime = Column(DateTime(timezone=True), nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())

    account = relationship("Account", back_populates="status_events")
    status = relationship("AccountStatus", foreign_keys=[status_id], lazy="selectin")
    reason = relationship("AccountStatusReason", foreign_keys=[reason_id], lazy="selectin")
