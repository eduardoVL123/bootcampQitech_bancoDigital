from sqlalchemy import Column, DateTime, SmallInteger, String, func

from models.base import Base


class PixStatus(Base):
    __tablename__ = "pix_status"

    APPROVED = "APPROVED"
    TWO_FACTOR_REQUIRED = "TWO_FACTOR_REQUIRED"
    REJECTED = "REJECTED"

    id = Column(SmallInteger, primary_key=True)
    enumerator = Column(String(30), nullable=False, unique=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
