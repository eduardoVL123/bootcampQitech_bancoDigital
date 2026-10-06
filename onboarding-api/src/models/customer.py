from sqlalchemy import CHAR, BigInteger, Column, Date, DateTime, ForeignKey, String, UniqueConstraint, func
from sqlalchemy.orm import relationship

from models.base import Base
from models.customer_type import CustomerType


class Customer(Base):
    """O cliente, na tabela que o grupo definiu no database.sql (seção 1).
    Renda, ocupação e PEP não ficam aqui: são da abertura (models/onboarding.py)."""

    __tablename__ = "customer"

    id = Column(BigInteger, primary_key=True)
    customer_key = Column(CHAR(36), nullable=False)
    # Recebe a X-Idempotency-Key do pedido de abertura.
    request_key = Column(CHAR(36), nullable=False)
    type_id = Column(BigInteger, ForeignKey(CustomerType.id), nullable=False)
    name = Column(String(255), nullable=False)
    document_number = Column(String(18), nullable=False)
    birth_date = Column(Date)
    opening_date = Column(Date)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at = Column(DateTime(timezone=True))

    # Os nomes que o PostgreSQL dá aos UNIQUE sem nome do database.sql.
    __table_args__ = (
        UniqueConstraint("customer_key", name="customer_customer_key_key"),
        UniqueConstraint("request_key", name="customer_request_key_key"),
        UniqueConstraint("document_number", name="customer_document_number_key"),
    )

    type = relationship("CustomerType", foreign_keys=[type_id], lazy="selectin")
