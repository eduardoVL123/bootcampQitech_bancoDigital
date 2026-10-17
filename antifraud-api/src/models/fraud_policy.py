from sqlalchemy import Column, DateTime, Integer, func
from sqlalchemy.dialects.postgresql import JSONB

from models.base import Base


class FraudPolicy(Base):
    __tablename__ = "fraud_policy"

    id = Column(Integer, primary_key=True)
    version = Column(Integer, nullable=False, unique=True)
    parameters = Column(JSONB, nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
