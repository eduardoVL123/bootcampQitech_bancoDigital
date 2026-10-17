from sqlalchemy import Column, DateTime, Integer, Numeric, String, func
from sqlalchemy.dialects.postgresql import CIDR

from models.base import Base


class IpRangeLocation(Base):
    __tablename__ = "ip_range_location"

    id = Column(Integer, primary_key=True)
    network = Column(CIDR, nullable=False, unique=True)
    latitude = Column(Numeric(9, 6), nullable=False)
    longitude = Column(Numeric(9, 6), nullable=False)
    country = Column(String(2), nullable=False)
    source = Column(String(10), nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
