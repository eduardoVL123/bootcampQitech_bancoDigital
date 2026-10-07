from sqlalchemy import BigInteger, Column, DateTime, String, UniqueConstraint, func

from models.base import Base


class CustomerType(Base):
    __tablename__ = "customer_type"

    id = Column(BigInteger, primary_key=True)
    enumerator = Column(String(2), nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())

    __table_args__ = (UniqueConstraint("enumerator", name="uq_customer_type_enumerator"),)

    PF = "PF"
    PJ = "PJ"
