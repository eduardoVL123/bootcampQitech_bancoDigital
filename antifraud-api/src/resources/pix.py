from fastapi import status as http_status
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse

from controllers import PixController
from dtos import PixDTO
from utils.schema_handler import SchemaHandler


class PixResource:
    @SchemaHandler.validate("post_pix_transaction.json")
    def on_post(self, payload: dict) -> JSONResponse:
        analysis, ja_existia = PixController().analyze(payload)
        status_code = http_status.HTTP_200_OK if ja_existia else http_status.HTTP_201_CREATED
        return JSONResponse(content=jsonable_encoder(PixDTO.analysis(analysis)), status_code=status_code)

    def on_get_by_id(self, pix_id: str) -> JSONResponse:
        analysis = PixController().get(pix_id)
        return JSONResponse(content=jsonable_encoder(PixDTO.analysis(analysis)), status_code=http_status.HTTP_200_OK)
