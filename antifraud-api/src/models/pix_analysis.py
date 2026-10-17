from sqlalchemy import BigInteger, Column, DateTime, ForeignKey, Integer, Numeric, SmallInteger, String, func
from sqlalchemy.dialects.postgresql import CIDR, INET, JSONB
from sqlalchemy.orm import relationship

from models.base import Base
from models.pix_status import PixStatus


class PixAnalysis(Base):
    __tablename__ = "pix_analysis"

    id = Column(BigInteger, primary_key=True)
    analysis_key = Column(String(36), nullable=False, unique=True)
    pix_id = Column(String(64), nullable=False, unique=True)
    request_hash = Column(String(64), nullable=False)
    status_id = Column(SmallInteger, ForeignKey(PixStatus.id), nullable=False)
    risk_score = Column(SmallInteger, nullable=False)
    authentication_level = Column(String(20), nullable=False)
    scenario = Column(String(40), nullable=False)
    reason = Column(String(40), nullable=False)
    source_account_id = Column(BigInteger, ForeignKey("pix_account.id"), nullable=False)
    destination_account_id = Column(BigInteger, ForeignKey("pix_account.id"), nullable=False)
    source_document = Column(String(14), nullable=False)
    destination_document = Column(String(14), nullable=False)
    amount = Column(BigInteger, nullable=False)
    transaction_date = Column(DateTime(timezone=True), nullable=False)
    device_id = Column(String(64), nullable=False)
    channel = Column(String(10), nullable=False)
    ip = Column(INET, nullable=False)
    ip_network = Column(CIDR, nullable=False)
    latitude = Column(Numeric(9, 6))
    longitude = Column(Numeric(9, 6))
    ip_latitude = Column(Numeric(9, 6))
    ip_longitude = Column(Numeric(9, 6))
    ip_location_source = Column(String(10), nullable=False)
    policy_id = Column(Integer, ForeignKey("fraud_policy.id"), nullable=False)
    metadata_ = Column("metadata", JSONB, nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())

    status = relationship(PixStatus, lazy="joined")
