from sqlalchemy import BigInteger, Column, DateTime, String, UniqueConstraint, func

from models.base import Base


class PixAccount(Base):
    __tablename__ = "pix_account"
    __table_args__ = (UniqueConstraint("participant", "branch", "account_number", name="pix_account_unique"),)

    id = Column(BigInteger, primary_key=True)
    participant = Column(String(8), nullable=False)
    branch = Column(String(4), nullable=False)
    account_number = Column(String(20), nullable=False)
    opening_date = Column(DateTime(timezone=True), nullable=False)
    owner_document = Column(String(14), nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
