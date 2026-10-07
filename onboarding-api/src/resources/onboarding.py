from typing import List, Optional

from fastapi import File, Request, UploadFile
from fastapi import status as http_status
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse

from constants import MAX_DOCUMENT_BYTES
from controllers.onboarding_controller import OnboardingController
from utils.credential import read_credential
from utils.idempotency_key import read_idempotency_key
from utils.request_origin import read_fault_injection, read_origin_ip
from utils.schema_handler import SchemaHandler


def read_document_files(fields: dict) -> list:
    """Os arquivos do envio do RG, como pares (campo, bytes), na ordem do formulário.

    Lê no máximo um byte além do limite de 5 MB: basta para o controller
    saber que o arquivo passou, sem trazer um arquivo enorme para a memória.
    """
    files = []

    for field, uploads in fields.items():
        for upload in uploads or []:
            files.append((field, upload.file.read(MAX_DOCUMENT_BYTES + 1)))

    return files


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

    def on_put_document(
        self,
        request: Request,
        onboarding_key: str,
        front: Optional[List[UploadFile]] = File(None),
        back: Optional[List[UploadFile]] = File(None),
        both: Optional[List[UploadFile]] = File(None),
    ) -> JSONResponse:
        # Cada campo é uma lista: o mesmo lado mandado duas vezes chega aqui
        # inteiro, e o controller recusa, em vez de ficar só com o último.
        credential = read_credential(request)

        # A chave só é conferida (decisão D7): quem guarda e repete a resposta é o gateway.
        read_idempotency_key(request)

        files = read_document_files({"front": front, "back": back, "both": both})

        controller = OnboardingController(read_fault_injection(request))
        onboarding, complete = controller.send_document(onboarding_key, credential, files)

        # 202 quando o RG ficou completo e a abertura entrou na fila da análise;
        # 200 quando ainda falta um lado.
        if complete:
            status_code = http_status.HTTP_202_ACCEPTED
        else:
            status_code = http_status.HTTP_200_OK

        return JSONResponse(content=jsonable_encoder(onboarding), status_code=status_code)

    def on_get_by_key(self, request: Request, onboarding_key: str) -> JSONResponse:
        credential = read_credential(request)

        controller = OnboardingController()
        onboarding = controller.get(onboarding_key, credential)

        return JSONResponse(content=jsonable_encoder(onboarding), status_code=http_status.HTTP_200_OK)
