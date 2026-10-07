from sqlalchemy import BigInteger, Column, DateTime, ForeignKey, String, UniqueConstraint, func
from sqlalchemy.orm import relationship
from models.base import Base


class CustomerDocument(Base):
    __tablename__ = "customer_document"

    id = Column(BigInteger, primary_key=True)
    customer_id = Column(BigInteger, ForeignKey("customer.id"), nullable=False)
    document_type = Column(String(20), nullable=False)
    side = Column(String(10), nullable=True)
    object_key = Column(String(255), nullable=False)
    content_type = Column(String(50), nullable=False)
    size_bytes = Column(BigInteger, nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())

    __table_args__ = (
        UniqueConstraint("customer_id", "document_type", "side", name="uq_customer_document_side"),
    )

    customer = relationship("Customer", back_populates="documents")
