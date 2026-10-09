from sqlalchemy import BigInteger, CHAR, Column, DateTime, Integer, String, func
from sqlalchemy.dialects.postgresql import JSONB

from webhook_api.src.models.base import Base


class WebhookOutbox(Base):
    """A caixa de saida de eventos. Espelho da tabela webhook_outbox.

    O segredo do parceiro nao esta aqui de proposito: ele e
    configuracao, vem do ambiente, e nao se guarda copia dele em cada
    linha de uma fila.
    """

    __tablename__ = "webhook_outbox"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    event_id = Column(CHAR(36), nullable=False, unique=True)
    target_url = Column(String(500), nullable=False)
    event_type = Column(String(100), nullable=False)
    payload = Column(JSONB, nullable=False)
    status = Column(String(30), nullable=False, default="PENDING")
    retries = Column(Integer, nullable=False, default=0)
    next_attempt_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    last_error = Column(String(255), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at = Column(DateTime(timezone=True), nullable=True, onupdate=func.now())
