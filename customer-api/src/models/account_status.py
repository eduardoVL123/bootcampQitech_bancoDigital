from sqlalchemy import BigInteger, Column, DateTime, String, func

from models.base import Base


class AccountStatus(Base):
    """Os estados possiveis de uma conta. Tabela de lookup, como a do base.

    O estado nao e texto solto na conta: e uma linha aqui, e a conta
    aponta para ela. Assim nao existe conta com estado escrito errado.
    """

    __tablename__ = "account_status"

    id = Column(BigInteger, primary_key=True)
    enumerator = Column(String(20), nullable=False, unique=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())

    ACTIVE = "ACTIVE"
    BLOCKED = "BLOCKED"
    CLOSED = "CLOSED"
