import requests

from connectors.rest_connector import RestConnector
from constants import ACCOUNT_API_TIMEOUT_SECONDS, ACCOUNT_API_URL, INTERNAL_TOKEN, SERVICE_TOKEN


class AccountApiError(Exception):
    """A account-api não abriu nem devolveu a conta. A abertura espera em APPROVED."""


class AccountConnector(RestConnector):
    """A account-api, pela rota interna POST /internal/account (RFC 02)."""

    def __init__(self) -> None:
        super().__init__(__name__, ACCOUNT_API_URL, ACCOUNT_API_TIMEOUT_SECONDS, INTERNAL_TOKEN)

    def open_account(self, customer_key: str, customer_type: str, idempotency_key: str) -> str:
        """Pede a conta do cliente e devolve a account_key: 201 é conta nova, e
        200 é a que ele já tinha (uma conta por cliente). A onboarding_key vai
        como chave idempotente: repetir o pedido nunca abre duas contas."""
        headers = {"SERVICE-TOKEN": SERVICE_TOKEN, "X-Idempotency-Key": idempotency_key}
        payload = {"customer_key": customer_key, "type": customer_type}

        try:
            response = self.send("/internal/account", "POST", payload, headers)
        except requests.exceptions.RequestException as error:
            self.logger.warning(f"account-api sem resposta ({type(error).__name__})")
            raise AccountApiError() from error

        account_key = response.json.get("account_key") if isinstance(response.json, dict) else None
        if response.status not in (200, 201) or not account_key:
            self.logger.warning(f"account-api respondeu {response.status}")
            raise AccountApiError()

        return account_key
