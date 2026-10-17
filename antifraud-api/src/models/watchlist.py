from sqlalchemy import BigInteger, Column, DateTime, String, func

from models.base import Base


class Watchlist(Base):
    __tablename__ = "watchlist"

    id = Column(BigInteger, primary_key=True)
    kind = Column(String(10), nullable=False)
    value = Column(String(64), nullable=False)
    report_type = Column(String(12), nullable=False)
    creator = Column(String(10), nullable=False)
    evidence_id = Column(String(80), nullable=False, unique=True)
    available_from = Column(DateTime(timezone=True), nullable=False)
    expires_at = Column(DateTime(timezone=True), nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
