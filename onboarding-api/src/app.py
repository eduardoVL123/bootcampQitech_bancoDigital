from fastapi import FastAPI

from constants import check_variables
from errors import register_error_handlers
from errors.base_error import error_verification
from middlewares import (
    register_internal_token_middleware,
    register_request_context_middleware,
    register_request_logger_middleware,
    register_session_manager_middleware,
)
from resources import ComplianceResource, CustomerResource, HealthCheckResource, OnboardingResource
from utils.logger import setup_logging


def create_app() -> FastAPI:
    """Monta a onboarding-api: middlewares, rotas e tratamento de erro.

    A explicação completa de cada peça está no src/app.py da API base, na
    raiz do repositório. Aqui fica só o que é desta API.
    """
    application = FastAPI(
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )

    # O último registrado é o primeiro a rodar. Lendo de baixo para cima:
    # identificador da requisição, log, INTERNAL-TOKEN e sessão de banco.
    register_session_manager_middleware(application)
    register_internal_token_middleware(application)
    register_request_logger_middleware(application)
    register_request_context_middleware(application)

    # A lista completa do que esta API atende (RFC 05, Rotas).
    health_check_resource = HealthCheckResource()
    onboarding_resource = OnboardingResource()
    customer_resource = CustomerResource()
    compliance_resource = ComplianceResource()

    application.add_api_route("/", health_check_resource.on_get_home, methods=["GET"])
    application.add_api_route("/health_check", health_check_resource.on_get_health_check, methods=["GET"])

    application.add_api_route("/onboarding", onboarding_resource.on_post, methods=["POST"])
    application.add_api_route("/onboarding/{onboarding_key}", onboarding_resource.on_get_by_key, methods=["GET"])
    application.add_api_route(
        "/onboarding/{onboarding_key}/document", onboarding_resource.on_put_document, methods=["PUT"]
    )
    application.add_api_route(
        "/internal/onboarding/{onboarding_key}/document/{side}/url", onboarding_resource.on_get_document_url, methods=["GET"]
    )

    application.add_api_route("/customer/{customer_key}", customer_resource.on_get_by_key, methods=["GET"])

    # Só de compliance: a fila e a decisão (F8), e a retentativa em lote, quando o birô volta (F7).
    application.add_api_route("/onboardings", compliance_resource.on_get_queue, methods=["GET"])
    application.add_api_route(
        "/onboarding/{onboarding_key}/decision", compliance_resource.on_put_decision, methods=["PUT"]
    )
    application.add_api_route("/admin/onboardings/retry", compliance_resource.on_post_retry, methods=["POST"])

    register_error_handlers(application)

    return application


def main() -> FastAPI:
    # Não sobe com configuração faltando, nem com dois erros usando o mesmo código.
    check_variables()
    error_verification()
    setup_logging()

    return create_app()


app = main()
