import requests
import hmac
import hashlib
import json
import logging
from typing import List

from webhook_api.src.models.webhook_outbox import WebhookOutbox

logger = logging.getLogger(__name__)

MAX_RETRIES = 5

def process_outbox_events(db_session):
    """
    Processa os eventos pendentes no outbox enviando-os para os webhooks de destino.
    Implementa retentativas com recuo (na vida real, o tempo seria gerenciado pelo Redis)
    e geração de assinatura HMAC para segurança.
    """
    # Busca os eventos pendentes
    events_to_process: List[WebhookOutbox] = db_session.query(WebhookOutbox).filter(
        WebhookOutbox.status.in_(["PENDING", "QUEUED_FOR_RETRY"])
    ).all()

    for event in events_to_process:
        headers = {"Content-Type": "application/json"}
        payload_str = json.dumps(event.payload, separators=(',', ':'))

        # Se tiver secret_key, geramos a assinatura matemática para garantir autenticidade
        if event.secret_key:
            signature = hmac.new(
                event.secret_key.encode('utf-8'),
                payload_str.encode('utf-8'),
                hashlib.sha256
            ).hexdigest()
            headers["X-Banco-Signature"] = signature

        try:
            # Enviamos pela rede!
            response = requests.post(
                event.target_url,
                json=event.payload,
                headers=headers,
                timeout=10
            )

            if response.status_code == 200:
                event.status = "DELIVERED"
            else:
                _handle_failure(event)
                
        except requests.exceptions.RequestException as e:
            logger.error(f"Erro ao entregar webhook ID {event.id}: {str(e)}")
            _handle_failure(event)

    # Commita as mudanças no final
    db_session.commit()

def _handle_failure(event: WebhookOutbox):
    """Lida com a falha de entrega aplicando política de retentativa"""
    event.retries += 1
    if event.retries >= MAX_RETRIES:
        event.status = "FAILED"
    else:
        event.status = "QUEUED_FOR_RETRY"
