from fastapi import Request
from fastapi import status as http_status
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse

from controllers.customer_controller import CustomerController
from utils.credential import read_credential


class CustomerResource:
    """A rota do cadastro do cliente (RFC 05). Só leitura."""

    def on_get_by_key(self, request: Request, customer_key: str) -> JSONResponse:
        credential = read_credential(request)

        controller = CustomerController()
        customer = controller.get(customer_key, credential)

        return JSONResponse(content=jsonable_encoder(customer), status_code=http_status.HTTP_200_OK)
