import requests

from connectors.rest_connector import RestConnector
from constants import INTERNAL_TOKEN, SERVICE_TOKEN, WEBHOOK_API_URL, WEBHOOK_TIMEOUT_SECONDS


class WebhookConnector(RestConnector):
    """A webhook-api, pela rota interna POST /internal/event (RFC 05, Eventos).

    Se o contrato com a webhook-api mudar para a tabela compartilhada da
    RFC 06, é aqui, e no controller que chama, que a entrega muda."""

    def __init__(self) -> None:
        super().__init__(__name__, WEBHOOK_API_URL, WEBHOOK_TIMEOUT_SECONDS, INTERNAL_TOKEN)

    def send_event(self, envelope: dict) -> bool:
        """Entrega o evento e diz se a webhook-api confirmou: 202 recebido, ou
        200 já recebido. Qualquer outra resposta, timeout ou conexão recusada é falha."""
        try:
            response = self.send("/internal/event", "POST", envelope, {"SERVICE-TOKEN": SERVICE_TOKEN})
        except requests.exceptions.RequestException as error:
            self.logger.warning(f"webhook-api sem resposta ({type(error).__name__})")
            return False

        if response.status not in (200, 202):
            self.logger.warning(f"webhook-api respondeu {response.status}")
            return False

        return True
