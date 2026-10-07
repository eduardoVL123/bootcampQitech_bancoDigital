from sqlalchemy import BigInteger, Column, DateTime, String, func

from models.base import Base


class AccountStatusReason(Base):
    """Por que a conta mudou de estado. So o historico usa.

    Bloqueio e atributo do estado, e nao entidade separada: o motivo
    fica aqui e e gravado junto no evento.
    """

    __tablename__ = "account_status_reason"

    id = Column(BigInteger, primary_key=True)
    enumerator = Column(String(30), nullable=False, unique=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())

    OPERATOR = "OPERATOR"
    SUSPICIOUS_ACTIVITY = "SUSPICIOUS_ACTIVITY"
