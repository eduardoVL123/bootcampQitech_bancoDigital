from sqlalchemy import BigInteger, Column, DateTime, String, func

from models.base import Base


class TransactionType(Base):
    __tablename__ = "transaction_type"

    id = Column(BigInteger, primary_key=True)
    enumerator = Column(String(20), nullable=False, unique=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())

    DEPOSIT = "DEPOSIT"
    WITHDRAWAL = "WITHDRAWAL"
    TRANSFER = "TRANSFER"
