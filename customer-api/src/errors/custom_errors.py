from errors import QIException


class NotFoundCustomer(QIException):
    code = "QIT002001"

    def __init__(self, customer_key) -> None:
        title = "Customer not Found"
        http_status = 404
        description = f"Customer with key {customer_key} was not found."
        translation = "Cliente não foi encontrado."
        super().__init__(title, self.code, http_status, description, translation)


class DuplicatedCustomerDocument(QIException):
    """Já existe um cadastro com este CPF.

    409 Conflict: o pedido está correto em si, e o que impede é o que já
    está no banco. Não é erro de quem pediu, é conflito com o estado
    atual, e por isso não é 400.
    """

    code = "QIT002002"

    def __init__(self, document_number) -> None:
        title = "Customer CPF already registered"
        http_status = 409
        description = f"There is already a customer with CPF {document_number}."
        translation = "Já existe um cadastro com este CPF."
        super().__init__(title, self.code, http_status, description, translation)


class CustomerUnderage(QIException):
    code = "QIT002003"

    def __init__(self, age) -> None:
        title = "Customer is underage"
        http_status = 422
        description = f"The customer is {age} years old, and the minimum is 18."
        translation = "É preciso ter pelo menos 18 anos."
        super().__init__(title, self.code, http_status, description, translation)


class CustomerOverage(QIException):
    code = "QIT002004"

    def __init__(self, age) -> None:
        title = "Customer is overage"
        http_status = 422
        description = f"The customer is {age} years old, and the maximum is 120."
        translation = "É preciso ter no máximo 120 anos."
        super().__init__(title, self.code, http_status, description, translation)


class InvalidCustomerCPF(QIException):
    """O CPF tem o formato certo e não existe.

    422, e não 400, de propósito: 400 quer dizer "não consegui ler o seu
    pedido". Aqui a API leu, entendeu, e o valor é que não pode existir,
    porque os dois últimos dígitos não batem com a conta feita sobre os
    nove primeiros. A conta está em src/utils/document_number.py.
    """

    code = "QIT002005"

    def __init__(self, document_number) -> None:
        title = "Invalid Customer Document Number"
        http_status = 422
        description = f"The document number {document_number} is not a valid CPF."
        translation = "O CPF informado não é válido."
        super().__init__(title, self.code, http_status, description, translation)


class InvalidCustomerBirthdate(QIException):
    """A data tem o formato certo e não existe no calendário.

    Existe porque o `pattern` do schema sabe contar dígitos, não dias:
    "2025-02-30" e "9999-99-99" passam pelo regex e morrem no
    `date.fromisoformat`. Sem esta classe, esse ValueError virava 500, a
    API culpando a si mesma por um erro de quem chamou.
    """

    code = "QIT002006"

    def __init__(self, birthdate) -> None:
        title = "Invalid Customer Birthdate"
        http_status = 422
        description = f"The birthdate {birthdate} is not a real date."
        translation = "A data de nascimento informada não existe."
        super().__init__(title, self.code, http_status, description, translation)


class CustomerTypePJNotSupported(QIException):
    code = "QIT002007"

    def __init__(self) -> None:
        title = "Customer Type PJ not supported"
        http_status = 422
        description = "The customer type PJ is not supported in the MVP."
        translation = "O tipo de cliente PJ não é suportado no MVP."
        super().__init__(title, self.code, http_status, description, translation)


class CustomerDocumentAlreadyExists(QIException):
    code = "QIT002008"

    def __init__(self, document_type, side) -> None:
        title = "Customer Document already exists"
        http_status = 409
        description = f"The customer already has a {document_type} for side {side}."
        translation = "O cliente já possui este documento cadastrado para este lado."
        super().__init__(title, self.code, http_status, description, translation)


class NotFoundCustomerForDocument(QIException):
    code = "QIT002009"

    def __init__(self, customer_key) -> None:
        title = "Customer not Found for Document"
        http_status = 404
        description = f"Customer with key {customer_key} was not found."
        translation = "Cliente não foi encontrado para adicionar o documento."
        super().__init__(title, self.code, http_status, description, translation)
