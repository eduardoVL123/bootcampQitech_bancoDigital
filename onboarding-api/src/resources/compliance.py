from typing import Any

from fastapi import Body, Request
from fastapi import status as http_status
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse

from constants import QUEUE_DEFAULT_LIMIT, QUEUE_DEFAULT_PAGE
from controllers.compliance_controller import ComplianceController
from models import OnboardingStatus
from utils.credential import read_compliance_credential
from utils.idempotency_key import read_idempotency_key
from utils.schema_handler import SchemaCache, check_against_schema, query_params_to_dict


class ComplianceResource:
    """As rotas de compliance (RFC 05). Só passa a credencial com escopo compliance.

    Em todas, primeiro quem pede e depois o pedido: o cliente que tenta uma
    destas rotas recebe 403, qualquer que seja o corpo ou a query string.
    """

    def on_get_queue(self, request: Request) -> JSONResponse:
        read_compliance_credential(request)

        # O schema confere o formato: limit e page só com dígitos, e etapa e
        # motivo só os que existem. Por isso os int() abaixo não têm try.
        query = query_params_to_dict(request.query_params, SchemaCache.get_schema("get_onboardings.json"))
        check_against_schema(query, "get_onboardings.json")

        limit = int(query.get("limit", QUEUE_DEFAULT_LIMIT))
        page = int(query.get("page", QUEUE_DEFAULT_PAGE))
        status = query.get("status", OnboardingStatus.MANUAL_REVIEW)

        controller = ComplianceController()
        queue_page = controller.list_queue(status, query.get("reason_code"), limit, page * limit)

        # A paginação é assunto do endereço, e por isso quem monta o envelope é
        # o resource, como no molde da base (src/resources/sample_entity.py).
        page_envelope = {
            "data": queue_page["data"],
            "limit": limit,
            "page": page,
            "is_last_page": queue_page["is_last_page"],
        }

        return JSONResponse(content=jsonable_encoder(page_envelope), status_code=http_status.HTTP_200_OK)

    def on_put_decision(self, request: Request, onboarding_key: str, payload: Any = Body(None)) -> JSONResponse:
        credential = read_compliance_credential(request)

        # A chave só é conferida (decisão D7): quem guarda e repete a resposta é o gateway.
        read_idempotency_key(request)

        if payload is None:
            payload = {}
        check_against_schema(payload, "put_onboarding_decision.json")

        controller = ComplianceController()
        result, approved = controller.decide(onboarding_key, payload["decision"], payload["justification"], credential)

        # 202 na aprovação: o worker ainda vai abrir a conta. 200 na recusa: acabou.
        if approved:
            status_code = http_status.HTTP_202_ACCEPTED
        else:
            status_code = http_status.HTTP_200_OK

        return JSONResponse(content=jsonable_encoder(result), status_code=status_code)

    def on_post_retry(self, request: Request, payload: Any = Body(None)) -> JSONResponse:
        credential = read_compliance_credential(request)

        # A chave só é conferida (decisão D7): quem guarda e repete a resposta é o gateway.
        read_idempotency_key(request)

        # Sem corpo vale o mesmo que um corpo vazio: todas as aberturas paradas por birô fora.
        if payload is None:
            payload = {}
        check_against_schema(payload, "post_onboardings_retry.json")

        controller = ComplianceController()
        result = controller.requeue_bureau_unavailable(payload.get("onboarding_keys"), credential)

        return JSONResponse(content=jsonable_encoder(result), status_code=http_status.HTTP_202_ACCEPTED)
