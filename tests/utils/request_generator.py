from os import environ

from tests.utils.requisition import ClientRequisition, BaseConnectorResponse


INTERNAL_TOKEN = environ.get("INTERNAL_TOKEN", "default_token")


class RequestGenerator:
    @staticmethod
    def POST_sample_entity(sample_entity_payload: dict) -> BaseConnectorResponse:
        response = ClientRequisition.send(
            "POST",
            "/sample_entity",
            payload=sample_entity_payload,
            headers={"INTERNAL-TOKEN": INTERNAL_TOKEN},
        )

        return response.response_status, response.response_json

    @staticmethod
    def GET_sample_entity(sample_entity_key: str) -> BaseConnectorResponse:
        response = ClientRequisition.send(
            "GET",
            f"/sample_entity/{sample_entity_key}",
            headers={"INTERNAL-TOKEN": INTERNAL_TOKEN},
        )
        return response.response_status, response.response_json

    @staticmethod
    def PUT_sample_entity(sample_entity_key: str, update_payload: dict) -> BaseConnectorResponse:
        response = ClientRequisition.send(
            "PUT",
            f"/sample_entity/{sample_entity_key}",
            payload=update_payload,
            headers={"INTERNAL-TOKEN": INTERNAL_TOKEN},
        )
        return response.response_status, response.response_json

    @staticmethod
    def PUT_webhook_sample_entity(sample_entity_key: str) -> BaseConnectorResponse:
        response = ClientRequisition.send(
            "PUT",
            f"/webhook/sample_entity/{sample_entity_key}/increment_counter",
            headers={"INTERNAL-TOKEN": INTERNAL_TOKEN},
        )
        return response.response_status, response.response_json

    @staticmethod
    def GET_sample_entities(params: dict = None) -> BaseConnectorResponse:
        response = ClientRequisition.send(
            "GET", "/sample_entities", headers={"INTERNAL-TOKEN": INTERNAL_TOKEN}, query_params=params
        )
        return response.response_status, response.response_json

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
        return response.response_status, response.response_json

    @staticmethod
    def GET_account(account_key: str) -> BaseConnectorResponse:
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
    def POST_transaction(payload: dict, idempotency_key: str = None) -> BaseConnectorResponse:
        headers = {"INTERNAL-TOKEN": INTERNAL_TOKEN}
        if idempotency_key is not None:
            headers["Idempotency-Key"] = idempotency_key

        response = ClientRequisition.send("POST", "/transaction", payload=payload, headers=headers)
        return response.response_status, response.response_json

    @staticmethod
    def GET_transaction(transaction_key: str) -> BaseConnectorResponse:
        response = ClientRequisition.send(
            "GET",
            f"/transaction/{transaction_key}",
            headers={"INTERNAL-TOKEN": INTERNAL_TOKEN},
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
