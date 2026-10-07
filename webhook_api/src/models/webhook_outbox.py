from sqlalchemy import Column, BigInteger, String, Integer, DateTime, func
from sqlalchemy.dialects.postgresql import JSONB
from webhook_api.src.models.base import Base

class WebhookOutbox(Base):
    __tablename__ = "webhook_outbox"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    target_url = Column(String(500), nullable=False)
    event_type = Column(String(100), nullable=False)
    payload = Column(JSONB, nullable=False)
    status = Column(String(30), nullable=False, default='PENDING')
    secret_key = Column(String(255), nullable=True)
    retries = Column(Integer, nullable=False, default=0)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at = Column(DateTime(timezone=True), nullable=True, onupdate=func.now())
