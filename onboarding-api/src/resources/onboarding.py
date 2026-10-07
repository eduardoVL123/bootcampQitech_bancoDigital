from fastapi import Request
from fastapi import status as http_status
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse

from controllers.onboarding_controller import OnboardingController
from utils.credential import read_credential
from utils.idempotency_key import read_idempotency_key
from utils.request_origin import read_fault_injection, read_origin_ip
from utils.schema_handler import SchemaHandler


class OnboardingResource:
    """As rotas da abertura de conta (RFC 05). Recebe HTTP e devolve o status; a regra fica no controller."""

    @SchemaHandler.validate("post_onboarding.json")
    def on_post(self, request: Request, payload: dict) -> JSONResponse:
        idempotency_key = read_idempotency_key(request)

        controller = OnboardingController(read_fault_injection(request))
        onboarding, created = controller.start(payload, idempotency_key, read_origin_ip(request))

        # 201 para a abertura nova; 200 quando a chave já tinha sido usada.
        if created:
            status_code = http_status.HTTP_201_CREATED
        else:
            status_code = http_status.HTTP_200_OK

        return JSONResponse(content=jsonable_encoder(onboarding), status_code=status_code)

    def on_get_by_key(self, request: Request, onboarding_key: str) -> JSONResponse:
        credential = read_credential(request)

        controller = OnboardingController()
        onboarding = controller.get(onboarding_key, credential)

        return JSONResponse(content=jsonable_encoder(onboarding), status_code=http_status.HTTP_200_OK)
