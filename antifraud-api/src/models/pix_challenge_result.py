from sqlalchemy import BigInteger, Column, DateTime, ForeignKey, String, func

from models.base import Base


class PixChallengeResult(Base):
    __tablename__ = "pix_challenge_result"

    id = Column(BigInteger, primary_key=True)
    analysis_id = Column(BigInteger, ForeignKey("pix_analysis.id"), nullable=False, unique=True)
    result = Column(String(25), nullable=False)
    event_date = Column(DateTime(timezone=True), nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
