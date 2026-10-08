from sqlalchemy import CHAR, BigInteger, Column, DateTime, ForeignKey, Integer, String, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import relationship

from models.base import Base
from models.onboarding import Onboarding


class OnboardingOutbox(Base):
    """Um evento para a webhook-api, gravado no mesmo COMMIT da mudança de
    etapa (regra 12; RFC 05, Diagrama C). Nada aqui é dado pessoal."""

    __tablename__ = "onboarding_outbox"

    id = Column(BigInteger, primary_key=True)
    event_id = Column(CHAR(36), nullable=False)
    onboarding_id = Column(BigInteger, ForeignKey(Onboarding.id), nullable=False)
    event_type = Column(String(40), nullable=False)
    payload = Column(JSONB, nullable=False)
    occurred_at = Column(DateTime(timezone=True), nullable=False)
    status = Column(String(10), nullable=False)
    attempts = Column(Integer, nullable=False, default=0)
    # A próxima tentativa, ou o fim da posse de quem está entregando.
    next_attempt_at = Column(DateTime(timezone=True))
    sent_at = Column(DateTime(timezone=True))
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())

    __table_args__ = (UniqueConstraint("event_id", name="onboarding_outbox_event_id_key"),)

    onboarding = relationship("Onboarding", foreign_keys=[onboarding_id])

    PENDING = "PENDING"
    SENT = "SENT"

    KYC_APPROVED = "account.kyc.approved"
    CREATED = "account.created"
    REJECTED = "account.rejected"
    KYC_MANUAL_REVIEW = "account.kyc.manual_review"
