from sqlalchemy import CHAR, BigInteger, Boolean, Column, DateTime, ForeignKey, Integer, String, UniqueConstraint, func
from sqlalchemy.orm import relationship

from models.base import Base
from models.customer import Customer
from models.onboarding_status import OnboardingStatus


class Onboarding(Base):
    __tablename__ = "onboarding"

    id = Column(BigInteger, primary_key=True)
    onboarding_key = Column(CHAR(36), nullable=False)
    customer_id = Column(BigInteger, ForeignKey(Customer.id))
    idempotency_key = Column(String(64), nullable=False)
    request_hash = Column(CHAR(64), nullable=False)
    status_id = Column(BigInteger, ForeignKey(OnboardingStatus.id), nullable=False)
    # Dados do KYC e do PLD desta abertura. Nulos depois de vencer (LGPD).
    declared_monthly_income = Column(BigInteger)
    occupation = Column(String(100))
    pep_self_declared = Column(Boolean)
    account_key = Column(CHAR(36))
    risk_level = Column(String(6))
    reason_codes = Column(String(200))
    analysis_attempts = Column(Integer, nullable=False, default=0)
    next_attempt_at = Column(DateTime(timezone=True))
    lease_until = Column(DateTime(timezone=True))
    expires_at = Column(DateTime(timezone=True), nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at = Column(DateTime(timezone=True))

    __table_args__ = (
        UniqueConstraint("onboarding_key", name="onboarding_onboarding_key_key"),
        UniqueConstraint("customer_id", name="onboarding_customer_id_key"),
        UniqueConstraint("idempotency_key", name="onboarding_idempotency_key_key"),
    )

    customer = relationship("Customer", foreign_keys=[customer_id], lazy="selectin")
    status = relationship("OnboardingStatus", foreign_keys=[status_id], lazy="selectin")
    status_events = relationship(
        "OnboardingStatusEvent",
        back_populates="onboarding",
        order_by="asc(OnboardingStatusEvent.id)",
    )
    documents = relationship(
        "OnboardingDocument",
        back_populates="onboarding",
        order_by="asc(OnboardingDocument.id)",
    )
