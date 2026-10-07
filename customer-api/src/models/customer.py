from sqlalchemy import CHAR, BigInteger, Column, Date, DateTime, ForeignKey, String, UniqueConstraint, func
from sqlalchemy.orm import relationship
from models.base import Base
from models.customer_type import CustomerType


class Customer(Base):
    __tablename__ = "customer"

    id = Column(BigInteger, primary_key=True)
    customer_key = Column(CHAR(36), nullable=False, unique=True)
    request_key = Column(CHAR(36), nullable=False, unique=True)
    type_id = Column(BigInteger, ForeignKey(CustomerType.id), nullable=False)
    name = Column(String(255), nullable=False)
    document_number = Column(String(18), nullable=False, unique=True)
    birth_date = Column(Date, nullable=True)
    opening_date = Column(Date, nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at = Column(DateTime(timezone=True), nullable=True, onupdate=func.now())

    customer_type = relationship("CustomerType", lazy="selectin")
    documents = relationship("CustomerDocument", back_populates="customer", cascade="all, delete-orphan")
