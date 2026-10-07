from typing import Any

from fastapi import Body, Request
from fastapi import status as http_status
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse

from controllers.compliance_controller import ComplianceController
from utils.credential import read_compliance_credential
from utils.idempotency_key import read_idempotency_key
from utils.schema_handler import check_against_schema


class ComplianceResource:
    """As rotas de compliance (RFC 05). Só passa a credencial com escopo compliance."""

    def on_post_retry(self, request: Request, payload: Any = Body(None)) -> JSONResponse:
        # Primeiro quem pede, depois o pedido: o cliente que tenta esta rota
        # recebe 403, qualquer que seja o corpo.
        read_compliance_credential(request)

        # A chave só é conferida (decisão D7): quem guarda e repete a resposta é o gateway.
        read_idempotency_key(request)

        # Sem corpo vale o mesmo que um corpo vazio: todas as aberturas paradas por birô fora.
        if payload is None:
            payload = {}
        check_against_schema(payload, "post_onboardings_retry.json")

        controller = ComplianceController()
        result = controller.requeue_bureau_unavailable(payload.get("onboarding_keys"))

        return JSONResponse(content=jsonable_encoder(result), status_code=http_status.HTTP_202_ACCEPTED)
