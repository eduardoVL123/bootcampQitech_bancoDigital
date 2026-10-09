from os import environ

from tests.utils.credential import token_de_operador
from tests.utils.donos import (
    credencial_da_conta,
    credencial_da_transacao,
    registra_conta,
    registra_transacao,
)
from tests.utils.requisition import ClientRequisition, BaseConnectorResponse


INTERNAL_TOKEN = environ.get("INTERNAL_TOKEN", "default_token")


def _headers_com_credencial(credential: str) -> dict:
    return {"INTERNAL-TOKEN": INTERNAL_TOKEN, "Authorization": f"Bearer {credential}"}


class RequestGenerator:
    @staticmethod
    def POST_customer(customer_payload: dict) -> BaseConnectorResponse:
        response = ClientRequisition.send(
            "POST",
            "/internal/customer",
            payload=customer_payload,
            headers={"INTERNAL-TOKEN": INTERNAL_TOKEN},
        )
        return response.response_status, response.response_json

    @staticmethod
    def GET_customer(customer_key: str) -> BaseConnectorResponse:
        response = ClientRequisition.send(
            "GET",
            f"/customer/{customer_key}",
            headers={"INTERNAL-TOKEN": INTERNAL_TOKEN},
        )
        return response.response_status, response.response_json

    @staticmethod
    def POST_customer_document(customer_key: str, document_payload: dict) -> BaseConnectorResponse:
        response = ClientRequisition.send(
            "POST",
            f"/internal/customer/{customer_key}/document",
            payload=document_payload,
            headers={"INTERNAL-TOKEN": INTERNAL_TOKEN},
        )
        return response.response_status, response.response_json

    @staticmethod
    def POST_account(payload: dict) -> BaseConnectorResponse:
        response = ClientRequisition.send(
            "POST",
            "/internal/account",
            payload=payload,
            headers={"INTERNAL-TOKEN": INTERNAL_TOKEN},
        )
        corpo = response.response_json
        if isinstance(corpo, dict) and corpo.get("account_key"):
            registra_conta(corpo["account_key"], payload.get("customer_key"))
        return response.response_status, corpo

    @staticmethod
    def GET_account(account_key: str, credential: str = None) -> BaseConnectorResponse:
        response = ClientRequisition.send(
            "GET",
            f"/account/{account_key}",
            headers=_headers_com_credencial(credential or credencial_da_conta(account_key)),
        )
        return response.response_status, response.response_json

    @staticmethod
    def GET_account_sem_credencial(account_key: str) -> BaseConnectorResponse:
        """Sem Authorization de proposito: e o teste F7-04."""
        response = ClientRequisition.send(
            "GET",
            f"/account/{account_key}",
            headers={"INTERNAL-TOKEN": INTERNAL_TOKEN},
        )
        return response.response_status, response.response_json

    @staticmethod
    def POST_account_sem_token(payload: dict) -> BaseConnectorResponse:
        """Sem o INTERNAL-TOKEN de proposito: e o teste F1-11."""
        response = ClientRequisition.send("POST", "/internal/account", payload=payload)
        return response.response_status, response.response_json

    @staticmethod
    def POST_posting(payload: dict) -> BaseConnectorResponse:
        response = ClientRequisition.send(
            "POST",
            "/internal/posting",
            payload=payload,
            headers={"INTERNAL-TOKEN": INTERNAL_TOKEN},
        )
        return response.response_status, response.response_json

    @staticmethod
    def GET_reconciliation() -> BaseConnectorResponse:
        response = ClientRequisition.send(
            "GET",
            "/internal/reconciliation",
            headers={"INTERNAL-TOKEN": INTERNAL_TOKEN},
        )
        return response.response_status, response.response_json

    @staticmethod
    def POST_transaction(
        payload: dict, idempotency_key: str = None, credential: str = None
    ) -> BaseConnectorResponse:
        """A credencial padrao e a de quem a operacao exige.

        Transferencia sai da conta de origem, entao o padrao e o
        titular dela. Deposito e operacao de operador, entao o padrao e
        a credencial de operador.
        """
        if credential is None:
            if payload.get("origin_account_key"):
                credential = credencial_da_conta(payload["origin_account_key"])
            else:
                credential = token_de_operador()

        headers = _headers_com_credencial(credential)
        if idempotency_key is not None:
            headers["Idempotency-Key"] = idempotency_key

        response = ClientRequisition.send("POST", "/transaction", payload=payload, headers=headers)
        corpo = response.response_json
        if isinstance(corpo, dict) and corpo.get("transaction_key"):
            registra_transacao(
                corpo["transaction_key"],
                payload.get("origin_account_key") or payload.get("destination_account_key"),
            )
        return response.response_status, corpo

    @staticmethod
    def POST_transaction_sem_credencial(
        payload: dict, idempotency_key: str = None
    ) -> BaseConnectorResponse:
        headers = {"INTERNAL-TOKEN": INTERNAL_TOKEN}
        if idempotency_key is not None:
            headers["Idempotency-Key"] = idempotency_key
        response = ClientRequisition.send("POST", "/transaction", payload=payload, headers=headers)
        return response.response_status, response.response_json

    @staticmethod
    def GET_transaction(transaction_key: str, credential: str = None) -> BaseConnectorResponse:
        response = ClientRequisition.send(
            "GET",
            f"/transaction/{transaction_key}",
            headers=_headers_com_credencial(
                credential or credencial_da_transacao(transaction_key)
            ),
        )
        return response.response_status, response.response_json

    @staticmethod
    def POST_fee_policy(payload: dict) -> BaseConnectorResponse:
        response = ClientRequisition.send(
            "POST",
            "/internal/fee_policy",
            payload=payload,
            headers={"INTERNAL-TOKEN": INTERNAL_TOKEN},
        )
        return response.response_status, response.response_json

    @staticmethod
    def GET_statement(
        account_key: str, params: dict = None, credential: str = None
    ) -> BaseConnectorResponse:
        response = ClientRequisition.send(
            "GET",
            f"/account/{account_key}/statement",
            headers=_headers_com_credencial(credential or credencial_da_conta(account_key)),
            query_params=params,
        )
        return response.response_status, response.response_json
