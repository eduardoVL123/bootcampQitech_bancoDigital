from datetime import date
from sqlalchemy.exc import IntegrityError

from controllers.base_controller import BaseController
from errors import (
    CustomerOverage,
    CustomerTypePJNotSupported,
    CustomerUnderage,
    DuplicatedCustomerDocument,
    InvalidCustomerBirthdate,
    InvalidCustomerCPF,
    NotFoundCustomer,
    CustomerDocumentAlreadyExists,
    NotFoundCustomerForDocument,
)
from repositories import CustomerRepository, CustomerDocumentRepository
from utils.document_number import is_valid_cpf


class CustomerController(BaseController):
    def __init__(self) -> None:
        super().__init__(__name__)
        self.customer_repo = CustomerRepository(self.context)
        self.document_repo = CustomerDocumentRepository(self.context)

    def create(self, payload: dict):
        if payload.get("type") == "PJ":
            raise CustomerTypePJNotSupported()

        document_number = payload["document_number"]
        if not is_valid_cpf(document_number):
            raise InvalidCustomerCPF(document_number)

        try:
            birth_date = date.fromisoformat(payload["birth_date"])
        except ValueError:
            raise InvalidCustomerBirthdate(payload["birth_date"])

        today = date.today()
        age = today.year - birth_date.year - ((today.month, today.day) < (birth_date.month, birth_date.day))

        if age < 18:
            raise CustomerUnderage(age)
        if age > 120:
            raise CustomerOverage(age)

        try:
            customer = self.customer_repo.create(payload)
            customer.is_idempotent = False
            self.session.commit()
            return customer
        except IntegrityError as e:
            self.context.db_session.rollback()
            error_msg = str(e.orig).lower()
            if "request_key" in error_msg or "customer_request_key_key" in error_msg:
                customer = self.customer_repo.get_by_request_key(payload["request_key"])
                customer.is_idempotent = True
                return customer
            elif "document_number" in error_msg or "customer_document_number_key" in error_msg:
                raise DuplicatedCustomerDocument(document_number)
            raise e

    def get_by_key(self, customer_key: str):
        customer = self.customer_repo.get_by_key(customer_key)
        if not customer:
            raise NotFoundCustomer(customer_key)
        return customer

    def create_document(self, customer_key: str, payload: dict):
        customer = self.customer_repo.get_by_key(customer_key)
        if not customer:
            raise NotFoundCustomerForDocument(customer_key)

        document_type = payload["document_type"]
        side = payload.get("side")

        existing_doc = self.document_repo.get_by_customer_and_type_and_side(customer.id, document_type, side)
        if existing_doc:
            raise CustomerDocumentAlreadyExists(document_type, side)

        try:
            document = self.document_repo.create(customer.id, payload)
            self.session.commit()
            return document
        except IntegrityError as e:
            self.context.db_session.rollback()
            raise CustomerDocumentAlreadyExists(document_type, side)
