from sqlalchemy import Boolean, Column, DateTime, Integer, String
from sqlalchemy.dialects.postgresql import JSONB

from models.base import Base


class ReputationFixture(Base):
    __tablename__ = "reputation_fixture"

    id = Column(Integer, primary_key=True)
    document = Column(String(14), nullable=False)
    scope = Column(String(10), nullable=False)
    statistics = Column(JSONB, nullable=False)
    entity_role = Column(String(30), nullable=False)
    evidence_id = Column(String(40), nullable=False, unique=True)
    available_from = Column(DateTime(timezone=True), nullable=False)
    expires_at = Column(DateTime(timezone=True), nullable=False)
    fixture_version = Column(String(30), nullable=False)
    is_mock = Column(Boolean, nullable=False)
