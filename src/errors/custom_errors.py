from errors import QIException


class NotFoundCustomer(QIException):
    code = "QIT002001"

    def __init__(self, customer_key) -> None:
        title = "Customer not Found"
        http_status = 404
        description = f"Customer with key {customer_key} was not found."
        translation = "Cliente não foi encontrado."
        super().__init__(title, self.code, http_status, description, translation)
