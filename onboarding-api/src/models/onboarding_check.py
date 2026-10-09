from sqlalchemy import BigInteger, Column, DateTime, ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import relationship

from models.base import Base
from models.onboarding import Onboarding


class OnboardingCheck(Base):
    """O resultado de uma verificação da análise do KYC (RFC 05, Diagrama C).
    Guarda o resultado, o motivo e o protocolo do birô, nunca os dados consultados."""

    __tablename__ = "onboarding_check"

    id = Column(BigInteger, primary_key=True)
    onboarding_id = Column(BigInteger, ForeignKey(Onboarding.id), nullable=False)
    check_type = Column(String(10), nullable=False)
    result = Column(String(12), nullable=False)
    reason_code = Column(String(40))
    provider_reference = Column(String(64))
    consulted_at = Column(DateTime(timezone=True), nullable=False)

    __table_args__ = (UniqueConstraint("onboarding_id", "check_type", name="onboarding_check_onboarding_id_check_type_key"),)

    onboarding = relationship("Onboarding", foreign_keys=[onboarding_id], back_populates="checks")

    RECEITA = "RECEITA"
    SANCTIONS = "SANCTIONS"
    PEP = "PEP"
    PLD = "PLD"

    PASS = "PASS"
    FAIL = "FAIL"
    REVIEW = "REVIEW"
