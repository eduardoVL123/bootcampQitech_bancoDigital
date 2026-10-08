from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from errors.base_error import (
    QIException,
    InternalError,
    InvalidParameter,
    InvalidSchema,
    MethodNotAllowed,
    NotFoundResource,
)
from utils.logger import get_logger
from utils.request_context import get_request_id


logger = get_logger(__name__)


def qi_exception_to_response(exception: QIException) -> JSONResponse:
    """Traduz um erro nosso para a resposta JSON que o cliente recebe.

    Este é o único lugar do projeto que sabe como um erro vira HTTP.
    Trocar de framework significa reescrever esta função — e mais nada.
    """
    body = {
        "code": exception.code,
        "title": exception.title,
        "description": exception.description,
        "translation": exception.translation,
        # O protocolo do atendimento: o mesmo valor do cabeçalho X-Request-ID.
        "request_id": get_request_id(),
        "errors": exception.errors,
    }
    return JSONResponse(status_code=exception.http_status, content=body, headers=exception.headers)


def describe_validation_error(error: dict) -> str:
    location = []
    for part in error.get("loc", []):
        if part not in ("body", "query"):
            location.append(str(part))

    message = error.get("msg", "invalid value")

    if location:
        return f"{message} in {'.'.join(location)}"

    return message


def register_error_handlers(application: FastAPI) -> None:
    """Ensina a aplicação a responder cada tipo de erro."""

    @application.exception_handler(QIException)
    def handle_qi_exception(request: Request, exception: QIException) -> JSONResponse:
        return qi_exception_to_response(exception)

    @application.exception_handler(StarletteHTTPException)
    def handle_http_exception(request: Request, exception: StarletteHTTPException) -> JSONResponse:
        if exception.status_code == 404:
            return qi_exception_to_response(NotFoundResource())

        if exception.status_code == 405:
            return qi_exception_to_response(MethodNotAllowed())

        logger.error(f"HTTP {exception.status_code} em {request.url.path}: {exception.detail}")
        return qi_exception_to_response(InternalError())

    @application.exception_handler(RequestValidationError)
    def handle_validation_error(request: Request, exception: RequestValidationError) -> JSONResponse:
        errors = exception.errors()

        if errors:
            first_error = errors[0]
        else:
            first_error = {}

        description = describe_validation_error(first_error)
        origin = first_error.get("loc", [""])[0]

        # Este ramo NAO e alcancado hoje, e vale saber por que — e a
        # unica pista de que existem duas validacoes neste projeto, nao
        # uma.
        #
        # Quem julga a query string aqui e o JSON Schema, antes do
        # FastAPI (veja utils/schema_handler.py). Um ?page=-3 morre la,
        # com 400 ONB000001 — nunca chega a virar RequestValidationError.
        # E os parametros de endereco sao todos `str`, que nao tem como
        # falhar validacao.
        #
        # O ramo fica de pe para o dia em que alguma rota declarar um
        # parametro tipado (page: int) e passar a depender do FastAPI
        # para isso. O ONB000010 que o cliente ve hoje vem de outro
        # lugar: do controller, quando birthdate_from > birthdate_to.
        if origin in ("query", "path"):
            return qi_exception_to_response(InvalidParameter(description))

        # Corpo que nem é um objeto JSON (texto solto, lista, vazio).
        body_error = {"field": "body", "rule": "format", "message": "O corpo precisa ser um objeto JSON."}
        return qi_exception_to_response(InvalidSchema(description, [body_error]))

    @application.exception_handler(Exception)
    def handle_unexpected_error(request: Request, exception: Exception) -> JSONResponse:
        # Esta função roda numa thread do FastAPI, fora do "except": o
        # logger.exception não veria o erro e escreveria "NoneType: None".
        # Quem tira do traceback o que for pessoal é o formatador do log.
        logger.error(f"Erro inesperado em {request.method} {request.url.path}", exc_info=exception)
        return qi_exception_to_response(InternalError())
