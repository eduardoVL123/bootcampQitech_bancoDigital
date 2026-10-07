from fastapi import status as http_status
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse

from controllers import CustomerController
from dtos import CustomerDTO, CustomerDocumentDTO
from utils.schema_handler import SchemaHandler


class CustomerResource:

    @SchemaHandler.validate("post_customer.json")
    def on_post_create(self, payload: dict) -> JSONResponse:
        controller = CustomerController()
        customer = controller.create(payload)

        status_code = http_status.HTTP_200_OK if customer.is_idempotent else http_status.HTTP_201_CREATED

        return JSONResponse(
            content=jsonable_encoder(CustomerDTO.created_response(customer)),
            status_code=status_code,
        )

    def on_get_by_key(self, customer_key: str) -> JSONResponse:
        controller = CustomerController()
        customer = controller.get_by_key(customer_key)

        return JSONResponse(
            content=jsonable_encoder(CustomerDTO.full_response(customer)),
            status_code=http_status.HTTP_200_OK,
        )

    @SchemaHandler.validate("post_customer_document.json")
    def on_post_document(self, customer_key: str, payload: dict) -> JSONResponse:
        controller = CustomerController()
        document = controller.create_document(customer_key, payload)

        return JSONResponse(
            content=jsonable_encoder(CustomerDocumentDTO.created_response(document)),
            status_code=http_status.HTTP_201_CREATED,
        )
