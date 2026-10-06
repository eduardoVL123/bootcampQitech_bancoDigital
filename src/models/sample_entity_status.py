from sqlalchemy import Column, Integer, String, DateTime, UniqueConstraint, func
from models.base import Base


class SampleEntityStatus(Base):
    __tablename__ = "sample_entity_status"

    id = Column(Integer, primary_key=True)
    enumerator = Column(String(50), nullable=False)
    created_at = Column(DateTime, nullable=False, server_default=func.now())

    __table_args__ = (UniqueConstraint("enumerator"),)

    CREATED = "created"
    PENDING = "pending"
    FAILED = "failed"
    SUCCESS = "success"
