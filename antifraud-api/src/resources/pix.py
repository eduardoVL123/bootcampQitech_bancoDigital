from fastapi import status as http_status
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse

from controllers import PixController
from controllers.challenge_controller import ChallengeController
from dtos import PixDTO
from utils.schema_handler import SchemaHandler


class PixResource:
    @SchemaHandler.validate("post_pix_transaction.json")
    def on_post(self, payload: dict) -> JSONResponse:
        controller = PixController()
        analysis, ja_existia = controller.analyze(payload)
        status_code = http_status.HTTP_200_OK if ja_existia else http_status.HTTP_201_CREATED
        corpo = PixDTO.analysis(analysis, controller.challenge_of(analysis) if ja_existia else None)
        return JSONResponse(content=jsonable_encoder(corpo), status_code=status_code)

    def on_get_by_id(self, pix_id: str) -> JSONResponse:
        controller = PixController()
        analysis = controller.get(pix_id)
        corpo = PixDTO.analysis(analysis, controller.challenge_of(analysis))
        return JSONResponse(content=jsonable_encoder(corpo), status_code=http_status.HTTP_200_OK)

    @SchemaHandler.validate("patch_pix_transaction.json")
    def on_patch(self, pix_id: str, payload: dict) -> JSONResponse:
        analysis, challenge = ChallengeController().answer(pix_id, payload)
        return JSONResponse(content=jsonable_encoder(PixDTO.analysis(analysis, challenge)),
                            status_code=http_status.HTTP_200_OK)
