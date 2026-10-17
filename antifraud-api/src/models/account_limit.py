from sqlalchemy import BigInteger, Column, DateTime, ForeignKey, String, func

from models.base import Base


class AccountLimit(Base):
    __tablename__ = "account_limit"

    id = Column(BigInteger, primary_key=True)
    account_id = Column(BigInteger, ForeignKey("pix_account.id"), nullable=False)
    amount = Column(BigInteger, nullable=False)
    change_type = Column(String(10), nullable=False)
    requested_at = Column(DateTime(timezone=True), nullable=False)
    effective_from = Column(DateTime(timezone=True), nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
