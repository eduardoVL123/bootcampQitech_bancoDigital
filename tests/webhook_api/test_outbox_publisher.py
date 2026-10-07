import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from tests.utils.db_utils import DbUtils
from webhook_api.src.outbox_publisher import publish_webhook
from webhook_api.src.models.webhook_outbox import WebhookOutbox

@pytest.fixture(scope="function")
def db_session():
    DbUtils.rollback()
    engine = create_engine(DbUtils.database_url())
    SessionLocal = sessionmaker(bind=engine)
    session = SessionLocal()
    yield session
    session.rollback()
    session.close()

class TestOutboxPublisher:
    
    def test_deve_inserir_evento_na_tabela_outbox_corretamente(self, db_session):
        # Act: Publica um evento simulando uma outra API
        publish_webhook(
            db_session=db_session,
            target_url="https://futuro.mock.com",
            event_type="account.created",
            payload={"account_key": "abc-123", "status": "ACTIVE"},
            secret_key="my-secret"
        )
        # O commit ocorreria na API original, mas simulamos aqui
        db_session.commit()
        
        # Assert: Verificamos se foi inserido com os dados corretos no banco
        evento = db_session.query(WebhookOutbox).first()
        
        assert evento is not None
        assert evento.target_url == "https://futuro.mock.com"
        assert evento.event_type == "account.created"
        assert evento.payload["account_key"] == "abc-123"
        assert evento.secret_key == "my-secret"
        assert evento.status == "PENDING"
        assert evento.retries == 0
