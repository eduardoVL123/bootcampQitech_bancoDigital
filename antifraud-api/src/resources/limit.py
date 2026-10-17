from fastapi import status as http_status
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse

from controllers.limit_controller import LimitController
from utils.schema_handler import SchemaHandler


class LimitResource:
    @SchemaHandler.validate("put_account_limit.json")
    def on_put(self, payload: dict) -> JSONResponse:
        limite = LimitController().change(payload)
        corpo = {
            "amount": limite.amount,
            "change_type": limite.change_type,
            "requested_at": limite.requested_at.isoformat(),
            "effective_from": limite.effective_from.isoformat(),
        }
        return JSONResponse(content=jsonable_encoder(corpo), status_code=http_status.HTTP_200_OK)
