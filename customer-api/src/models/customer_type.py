from sqlalchemy import BigInteger, Column, DateTime, String, func
from models.base import Base


class CustomerType(Base):
    __tablename__ = "customer_type"

    id = Column(BigInteger, primary_key=True)
    enumerator = Column(String(2), nullable=False, unique=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())

    PF = "PF"
    PJ = "PJ"
