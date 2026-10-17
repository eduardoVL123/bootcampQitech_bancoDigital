from sqlalchemy import BigInteger, Boolean, Column, DateTime, ForeignKey, SmallInteger, String, Text, func

from models.base import Base


class PixRuleResult(Base):
    __tablename__ = "pix_rule_result"

    id = Column(BigInteger, primary_key=True)
    analysis_id = Column(BigInteger, ForeignKey("pix_analysis.id"), nullable=False)
    rule = Column(String(40), nullable=False)
    evaluation = Column(String(15), nullable=False)
    axis = Column(String(15))
    family = Column(String(30))
    raw_points = Column(SmallInteger, nullable=False)
    effective_points = Column(SmallInteger, nullable=False)
    hard_block = Column(Boolean, nullable=False)
    authentication_floor = Column(String(20), nullable=False)
    detail = Column(Text, nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
