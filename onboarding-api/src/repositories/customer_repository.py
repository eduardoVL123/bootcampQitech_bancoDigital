from datetime import date
from typing import Optional
from uuid import uuid4

from database import Context
from models import Customer, CustomerType


class CustomerRepository:
    """Grava e busca o cliente. Só aqui existe query de cliente."""

    def __init__(self, context: Context, simulate_database_error: bool = False) -> None:
        self.session = context.db_session
        self.simulate_database_error = simulate_database_error

    def create(
        self,
        customer_data: dict,
        request_key: str,
        birth_date: Optional[date],
        opening_date: Optional[date],
    ) -> Customer:
        customer = Customer()

        customer.customer_key = str(uuid4())
        customer.request_key = request_key
        customer.type = self.get_type(customer_data["type"])
        customer.name = customer_data["name"]
        customer.document_number = customer_data["document_number"]
        customer.birth_date = birth_date
        customer.opening_date = opening_date

        # Falha simulada (X-Fault-Injection: database_error, só com
        # FAULT_INJECTION_ENABLED=true): a linha leva as duas datas, e o CHECK
        # por tipo do database.sql a recusa. É um erro de verdade do PostgreSQL,
        # com os dados da pessoa no comando e na mensagem, para o teste provar
        # que nada disso chega ao log (RFC 05, Log sem dado pessoal; F10-04).
        if self.simulate_database_error:
            customer.birth_date = birth_date or opening_date
            customer.opening_date = opening_date or birth_date

        self.session.add(customer)
        return customer

    def get_by_key(self, customer_key: str) -> Optional[Customer]:
        return self.session.query(Customer).filter(Customer.customer_key == customer_key).first()

    def get_type(self, enumerator: str) -> CustomerType:
        return self.session.query(CustomerType).filter(CustomerType.enumerator == enumerator).one()
