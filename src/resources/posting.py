from fastapi import status as http_status
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse

from controllers import PostingController
from dtos import PostingDTO
from utils.schema_handler import SchemaHandler


class PostingResource:
    @SchemaHandler.validate("post_posting.json")
    def on_post_apply(self, payload: dict) -> JSONResponse:
        controller = PostingController()
        posting, ja_existia = controller.apply(payload)

        # 200 no replay: o mesmo pedido nao credita duas vezes.
        codigo = http_status.HTTP_200_OK if ja_existia else http_status.HTTP_201_CREATED

        return JSONResponse(
            content=jsonable_encoder(PostingDTO.applied_response(posting)),
            status_code=codigo,
        )

    def on_get_reconciliation(self) -> JSONResponse:
        controller = PostingController()

        return JSONResponse(
            content=jsonable_encoder(controller.reconciliation()),
            status_code=http_status.HTTP_200_OK,
        )
