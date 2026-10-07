from fastapi import Request
from fastapi import status as http_status
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse

from controllers import AccountController
from dtos import AccountDTO, StatementDTO
from utils.schema_handler import SchemaHandler


class AccountResource:
    """A porta HTTP da conta. Nenhum if de negocio mora aqui."""

    @SchemaHandler.validate("post_account.json")
    def on_post_open(self, payload: dict) -> JSONResponse:
        controller = AccountController()
        account, ja_existia = controller.open(payload)

        # 200 quando a conta ja existia, 201 quando nasceu agora. E o que
        # permite a onboarding-api repetir o pedido sem criar duas contas.
        codigo = http_status.HTTP_200_OK if ja_existia else http_status.HTTP_201_CREATED

        return JSONResponse(
            content=jsonable_encoder(AccountDTO.created_response(account)),
            status_code=codigo,
        )

    def on_get_by_key(self, account_key: str) -> JSONResponse:
        controller = AccountController()
        account = controller.get_by_key(account_key)

        return JSONResponse(
            content=jsonable_encoder(AccountDTO.full_response(account)),
            status_code=http_status.HTTP_200_OK,
        )

    @SchemaHandler.validate_query_params("get_statement.json")
    def on_get_statement(self, request: Request, account_key: str) -> JSONResponse:
        controller = AccountController()
        linhas, next_cursor = controller.statement(account_key, dict(request.query_params))

        return JSONResponse(
            content=jsonable_encoder(StatementDTO.page(linhas, next_cursor)),
            status_code=http_status.HTTP_200_OK,
        )
