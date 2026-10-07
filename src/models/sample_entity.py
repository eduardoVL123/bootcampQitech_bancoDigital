from sqlalchemy import CHAR, Column, Date, DateTime, ForeignKey, Integer, String, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import relationship
from models.base import Base
from models import SampleEntityStatus


class SampleEntity(Base):
    __tablename__ = "sample_entity"

    id = Column(Integer, primary_key=True)
    sample_entity_key = Column(CHAR(36), nullable=False)
    sample_entity_data = Column(JSONB, nullable=False)
    name = Column(String(255), nullable=False)
    email = Column(String(255), nullable=False)
    document_number = Column(CHAR(14), nullable=False)
    birthdate = Column(Date, nullable=False)
    counter = Column(Integer, nullable=False)
    status_id = Column(Integer, ForeignKey(SampleEntityStatus.id), nullable=False)
    created_at = Column(DateTime, nullable=False, server_default=func.now())

    __table_args__ = (
        UniqueConstraint("sample_entity_key"),
        UniqueConstraint("document_number"),
        UniqueConstraint("email"),
    )

    status = relationship("SampleEntityStatus", foreign_keys=[status_id], lazy="selectin")

    status_events = relationship(
        "SampleEntityStatusEvent",
        back_populates="sample_entity",
        order_by="asc(SampleEntityStatusEvent.event_datetime)",
    )
