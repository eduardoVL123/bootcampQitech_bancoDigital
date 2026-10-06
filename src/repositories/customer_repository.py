from datetime import date
from uuid import uuid4

from database import Context
from models import Customer, CustomerType


class CustomerRepository:
    def __init__(self, context: Context) -> None:
        self.session = context.db_session

    def create(self, customer_data: dict) -> Customer:
        customer = Customer()
        customer.customer_key = str(uuid4())
        customer.request_key = customer_data["request_key"]
        customer.name = customer_data["name"]
        customer.document_number = customer_data["document_number"]

        if "birth_date" in customer_data and customer_data["birth_date"]:
            customer.birth_date = date.fromisoformat(customer_data["birth_date"])
        
        customer.customer_type = self.get_customer_type(customer_data["type"])

        self.session.add(customer)
        self.session.flush()
        return customer

    def get_by_key(self, customer_key: str) -> Customer:
        return self.session.query(Customer).filter(Customer.customer_key == customer_key).first()

    def get_by_document_number(self, document_number: str) -> Customer:
        return self.session.query(Customer).filter(Customer.document_number == document_number).first()

    def get_by_request_key(self, request_key: str) -> Customer:
        return self.session.query(Customer).filter(Customer.request_key == request_key).first()

    def get_customer_type(self, enumerator: str) -> CustomerType:
        return self.session.query(CustomerType).filter(CustomerType.enumerator == enumerator).one()
