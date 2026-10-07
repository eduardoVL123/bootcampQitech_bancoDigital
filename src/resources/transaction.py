from fastapi import Request
from fastapi import status as http_status
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse

from controllers import TransactionController
from dtos import FeePolicyDTO, TransactionDTO
from utils.schema_handler import SchemaHandler


class TransactionResource:
    @SchemaHandler.validate("post_transaction.json")
    def on_post_create(self, request: Request, payload: dict) -> JSONResponse:
        # A chave vem no cabecalho, e nao no corpo: e onde o cliente de
        # qualquer API espera encontrar, e o gateway e o log a enxergam
        # sem abrir o corpo.
        idempotency_key = request.headers.get("Idempotency-Key")

        controller = TransactionController()
        transaction, ja_existia = controller.create(idempotency_key, payload)

        codigo = http_status.HTTP_200_OK if ja_existia else http_status.HTTP_201_CREATED

        return JSONResponse(
            content=jsonable_encoder(TransactionDTO.response(transaction)),
            status_code=codigo,
        )

    def on_get_by_key(self, transaction_key: str) -> JSONResponse:
        controller = TransactionController()
        transaction = controller.get_by_key(transaction_key)

        return JSONResponse(
            content=jsonable_encoder(TransactionDTO.response(transaction)),
            status_code=http_status.HTTP_200_OK,
        )

    @SchemaHandler.validate("post_fee_policy.json")
    def on_post_fee_policy(self, payload: dict) -> JSONResponse:
        controller = TransactionController()
        politica = controller.create_fee_policy(payload)

        return JSONResponse(
            content=jsonable_encoder(FeePolicyDTO.response(politica)),
            status_code=http_status.HTTP_201_CREATED,
        )
