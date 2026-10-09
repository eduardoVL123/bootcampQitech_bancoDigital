from sqlalchemy import BigInteger, Column, DateTime, ForeignKey, String, func
from sqlalchemy.orm import relationship

from models.base import Base
from models.onboarding import Onboarding
from models.onboarding_status import OnboardingStatus


class OnboardingStatusEvent(Base):
    """O histórico da abertura: cada mudança de etapa grava uma linha, no
    mesmo COMMIT da mudança. Nada aqui é apagado nem editado (R4)."""

    __tablename__ = "onboarding_status_event"

    id = Column(BigInteger, primary_key=True)
    onboarding_id = Column(BigInteger, ForeignKey(Onboarding.id), nullable=False)
    status_id = Column(BigInteger, ForeignKey(OnboardingStatus.id), nullable=False)
    reason_code = Column(String(40))
    actor = Column(String(20), nullable=False)
    justification = Column(String(500))
    # Quem de compliance mudou a etapa: o sub da credencial (decisão D31).
    decided_by = Column(String(100))
    event_datetime = Column(DateTime(timezone=True), nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())

    onboarding = relationship("Onboarding", foreign_keys=[onboarding_id], back_populates="status_events")
    status = relationship("OnboardingStatus", foreign_keys=[status_id], lazy="selectin")

    API = "api"
    WORKER = "worker"
    COMPLIANCE = "compliance"
