from sqlalchemy import Boolean, Column, DateTime, Integer, String

from models.base import Base


class CompanyRegistryFixture(Base):
    __tablename__ = "company_registry_fixture"

    id = Column(Integer, primary_key=True)
    cnpj = Column(String(14), nullable=False)
    responsible_cpf = Column(String(11), nullable=False)
    evidence_id = Column(String(40), nullable=False, unique=True)
    available_from = Column(DateTime(timezone=True), nullable=False)
    expires_at = Column(DateTime(timezone=True), nullable=False)
    fixture_version = Column(String(30), nullable=False)
    is_mock = Column(Boolean, nullable=False)
