from sqlalchemy import BigInteger, Column, DateTime, ForeignKey, String, UniqueConstraint, func
from sqlalchemy.orm import relationship

from models.base import Base
from models.onboarding import Onboarding


class OnboardingDocument(Base):
    """Uma imagem do RG da abertura (decisão D21). A foto mora no bucket; aqui
    fica só o caminho dela, o lado, o tipo e o tamanho."""

    __tablename__ = "onboarding_document"

    id = Column(BigInteger, primary_key=True)
    onboarding_id = Column(BigInteger, ForeignKey(Onboarding.id), nullable=False)
    document_type = Column(String(20), nullable=False)
    side = Column(String(10), nullable=False)
    object_key = Column(String(255), nullable=False)
    content_type = Column(String(50), nullable=False)
    size_bytes = Column(BigInteger, nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())

    __table_args__ = (
        UniqueConstraint("onboarding_id", "side", name="onboarding_document_onboarding_id_side_key"),
        UniqueConstraint("object_key", name="onboarding_document_object_key_key"),
    )

    onboarding = relationship("Onboarding", foreign_keys=[onboarding_id], back_populates="documents")

    RG = "RG"

    FRONT = "FRONT"
    BACK = "BACK"
    BOTH = "BOTH"

    # Os lados do RG que cada imagem mostra: a BOTH mostra os dois.
    SIDES_SHOWN = {
        FRONT: frozenset({FRONT}),
        BACK: frozenset({BACK}),
        BOTH: frozenset({FRONT, BACK}),
    }

    COMPLETE_RG = frozenset({FRONT, BACK})

    @staticmethod
    def sides_shown(sides) -> frozenset:
        """Os lados do RG que um conjunto de imagens mostra."""
        shown = frozenset()
        for side in sides:
            shown = shown | OnboardingDocument.SIDES_SHOWN[side]
        return shown
