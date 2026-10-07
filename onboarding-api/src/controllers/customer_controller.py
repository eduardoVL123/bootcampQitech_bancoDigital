from controllers.base_controller import BaseController
from dtos import CustomerDTO
from errors import CustomerNotFound
from repositories import CustomerRepository
from utils.credential import Credential


class CustomerController(BaseController):
    """Quem pode ver um cadastro: o próprio cliente ou compliance."""

    def __init__(self) -> None:
        super().__init__(__name__)
        self.customer_repository = CustomerRepository(self.context)

    def get(self, customer_key: str, credential: Credential) -> dict:
        customer = self.customer_repository.get_by_key(customer_key)

        # De outra pessoa responde igual a não existir (R8).
        if customer is None or not (credential.is_compliance or credential.is_customer(customer.customer_key)):
            raise CustomerNotFound()

        return CustomerDTO.public(customer)
