import pytest
from unittest.mock import patch, MagicMock

# ==============================================================================
# FASE RED DO TDD (Test-Driven Development)
# ==============================================================================
# IMPORTANTE: Neste exato momento, não existe a pasta 'webhook_api' nem a
# tabela 'webhook_outbox' no banco de dados.
# Este teste falhará com ImportError, e isso é o esperado.
# O objetivo de escrevê-lo antes do código é nos dar uma âncora:
# Só terminaremos de desenvolver a Webhook API quando todos estes testes passarem.
# ==============================================================================

try:
    from webhook_api.src.worker import process_outbox_events
    from webhook_api.src.models.webhook_outbox import WebhookOutbox
except ImportError:
    # Capturamos o erro apenas para que o pytest consiga carregar o arquivo e
    # mostrar os testes na tela (mesmo que quebrem na execução).
    process_outbox_events = None
    WebhookOutbox = None

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from tests.utils.db_utils import DbUtils

@pytest.fixture(scope="function")
def db_session():
    DbUtils.rollback()
    engine = create_engine(DbUtils.database_url())
    SessionLocal = sessionmaker(bind=engine)
    session = SessionLocal()
    yield session
    session.rollback()
    session.close()


class TestWebhookOutboxDelivery:
    
    @patch("webhook_api.src.worker.requests.post")
    def test_cenario_a_caminho_feliz(self, mock_post, db_session):
        """Cenário 2.1 A: Envio com sucesso de primeira."""
        if not WebhookOutbox:
            pytest.fail("Implementação da Webhook API ainda não existe.")

        # 1. Arrange (Preparação)
        # Inserimos um evento no outbox como PENDING
        evento = WebhookOutbox(
            target_url="https://parceiro.mock.com/webhook",
            event_type="transaction.success",
            payload={"transaction_id": 123, "amount": 1000},
            status="PENDING",
            retries=0
        )
        db_session.add(evento)
        db_session.commit()

        # O servidor do parceiro vai retornar 200 OK
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_post.return_value = mock_response

        # 2. Act (Ação)
        # Rodamos o worker que varre a tabela webhook_outbox e envia pra internet
        process_outbox_events(db_session)

        # 3. Assert (Verificação)
        # O post foi chamado com a URL certa
        mock_post.assert_called_once_with(
            "https://parceiro.mock.com/webhook",
            json={"transaction_id": 123, "amount": 1000},
            headers=mock_post.call_args[1].get('headers'), # Pegamos os headers enviados
            timeout=10
        )
        
        # O status no banco de dados mudou para DELIVERED
        db_session.refresh(evento)
        assert evento.status == "DELIVERED"
        assert evento.retries == 0


    @patch("webhook_api.src.worker.requests.post")
    def test_cenario_a_assinatura_hmac(self, mock_post, db_session):
        """Cenário 2.2 A: Segurança Criptográfica (Assinatura HMAC)"""
        if not WebhookOutbox:
            pytest.fail("Implementação da Webhook API ainda não existe.")

        # 1. Arrange
        evento = WebhookOutbox(
            target_url="https://parceiro.mock.com/webhook",
            event_type="account.approved",
            payload={"account_id": 99},
            status="PENDING",
            secret_key="secret-do-parceiro-aqui" # Chave secreta de teste
        )
        db_session.add(evento)
        db_session.commit()

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_post.return_value = mock_response

        # 2. Act
        process_outbox_events(db_session)

        # 3. Assert
        # Precisamos garantir que o cabeçalho X-Banco-Signature está presente e foi
        # calculado corretamente pelo nosso worker!
        headers_enviados = mock_post.call_args[1].get('headers')
        assert "X-Banco-Signature" in headers_enviados
        
        # Como o teste é blackbox (sabemos a chave e o payload), nós mesmos
        # geramos o HMAC esperado aqui e comparamos com o que o worker enviou.
        import hmac
        import hashlib
        import json
        
        payload_str = json.dumps({"account_id": 99}, separators=(',', ':'))
        assinatura_esperada = hmac.new(
            "secret-do-parceiro-aqui".encode('utf-8'),
            payload_str.encode('utf-8'),
            hashlib.sha256
        ).hexdigest()

        assert headers_enviados["X-Banco-Signature"] == assinatura_esperada


class TestWebhookOutboxRetries:
    
    @patch("webhook_api.src.worker.requests.post")
    def test_cenario_a_retentativa_com_sucesso(self, mock_post, db_session):
        """Cenário 2.3 A: O servidor do cliente cai temporariamente (Exponential Backoff)."""
        if not WebhookOutbox:
            pytest.fail("Implementação da Webhook API ainda não existe.")

        # 1. Arrange
        evento = WebhookOutbox(
            target_url="https://parceiro.mock.com/webhook",
            event_type="transaction.success",
            payload={"id": 1},
            status="PENDING",
            retries=0
        )
        db_session.add(evento)
        db_session.commit()

        # O servidor retorna erro 500
        mock_response_500 = MagicMock()
        mock_response_500.status_code = 500
        mock_post.return_value = mock_response_500

        # 2. Act - Primeira Tentativa (Falha)
        process_outbox_events(db_session)

        # 3. Assert - Retries aumentou
        db_session.refresh(evento)
        assert evento.status == "QUEUED_FOR_RETRY"
        assert evento.retries == 1

        # 4. Act - O tempo passa e o servidor do parceiro volta (Mock retorna 200)
        mock_response_200 = MagicMock()
        mock_response_200.status_code = 200
        mock_post.return_value = mock_response_200
        
        # Executamos o worker de novo, simulando a próxima varredura/tentativa
        process_outbox_events(db_session)
        
        # 5. Assert - Webhook entregue na segunda tentativa
        db_session.refresh(evento)
        assert evento.status == "DELIVERED"
        assert mock_post.call_count == 2
        
    @patch("webhook_api.src.worker.requests.post")
    def test_cenario_b_max_retries_excedido(self, mock_post, db_session):
        """Cenário 2.3 B: O cliente desapareceu (Max Retries Excedido)."""
        if not WebhookOutbox:
            pytest.fail("Implementação da Webhook API ainda não existe.")

        evento = WebhookOutbox(
            target_url="https://parceiro.mock.com/webhook",
            event_type="transaction.failed",
            payload={},
            status="QUEUED_FOR_RETRY",
            retries=4 # Supondo que o limite sejam 5 tentativas (vai tentar a 5ª agora)
        )
        db_session.add(evento)
        db_session.commit()

        # O servidor retorna erro 500 para sempre
        mock_response_500 = MagicMock()
        mock_response_500.status_code = 500
        mock_post.return_value = mock_response_500

        # Act - 5ª (Última) Tentativa
        process_outbox_events(db_session)

        # Assert - O evento deve ser dado como perdido
        db_session.refresh(evento)
        assert evento.status == "FAILED" # Ou Dead Letter Queue
        assert evento.retries == 5
