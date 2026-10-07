from sqlalchemy import BigInteger, Column, DateTime, String, func

from models.base import Base


class TransactionStatus(Base):
    __tablename__ = "transaction_status"

    id = Column(BigInteger, primary_key=True)
    enumerator = Column(String(20), nullable=False, unique=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())

    PENDING = "PENDING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
