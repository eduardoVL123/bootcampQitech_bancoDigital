from sqlalchemy import BigInteger, Column, DateTime, String, UniqueConstraint, func

from models.base import Base


class OnboardingStatus(Base):
    """As etapas da abertura (RFC 05, ciclo de vida). Buscadas sempre pelo
    `enumerator`, nunca pelo `id`."""

    __tablename__ = "onboarding_status"

    id = Column(BigInteger, primary_key=True)
    enumerator = Column(String(20), nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())

    __table_args__ = (UniqueConstraint("enumerator", name="uq_onboarding_status_enumerator"),)

    DRAFT = "DRAFT"
    PENDING_KYC = "PENDING_KYC"
    ANALYSIS = "ANALYSIS"
    MANUAL_REVIEW = "MANUAL_REVIEW"
    APPROVED = "APPROVED"
    ACTIVE = "ACTIVE"
    REJECTED = "REJECTED"
    EXPIRED = "EXPIRED"
