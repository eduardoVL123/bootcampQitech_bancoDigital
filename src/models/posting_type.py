from sqlalchemy import BigInteger, Column, DateTime, String, func

from models.base import Base


class PostingType(Base):
    """O que originou um conjunto de lancamentos."""

    __tablename__ = "posting_type"

    id = Column(BigInteger, primary_key=True)
    enumerator = Column(String(30), nullable=False, unique=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())

    DEPOSIT = "DEPOSIT"
    WITHDRAWAL = "WITHDRAWAL"
    TRANSFER = "TRANSFER"
    FEE_APPROPRIATION = "FEE_APPROPRIATION"
