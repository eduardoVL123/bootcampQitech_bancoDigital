"""Os erros da onboarding-api, faixa ONB005xxx (RFC 05, tabela de códigos).

Nenhuma mensagem leva CPF, CNPJ, renda ou foto: o erro diz o campo e a
regra, nunca o valor que veio.
"""
from errors.base_error import QIException


class MissingRequiredFields(QIException):
    code = "ONB005001"

    def __init__(self, errors) -> None:
        title = "Missing required fields"
        http_status = 400
        description = "One or more required fields are missing."
        translation = "Faltam campos obrigatórios."
        super().__init__(title, self.code, http_status, description, translation, errors)


class UnderageCustomer(QIException):
    code = "ONB005002"

    def __init__(self, minimum_age) -> None:
        title = "Customer is underage"
        http_status = 400
        description = f"The customer must be at least {minimum_age} years old."
        translation = f"É preciso ter pelo menos {minimum_age} anos para abrir uma conta."
        errors = [{"field": "birth_date", "rule": "minimum_age", "message": f"Idade mínima de {minimum_age} anos."}]
        super().__init__(title, self.code, http_status, description, translation, errors)


class DocumentAlreadyRegistered(QIException):
    code = "ONB005003"

    def __init__(self) -> None:
        title = "Document already registered"
        http_status = 409
        description = "There is already a customer with this document number."
        translation = "Já existe um cliente com este documento."
        errors = [{"field": "document_number", "rule": "unique", "message": "Documento já cadastrado."}]
        super().__init__(title, self.code, http_status, description, translation, errors)


class InvalidDocumentNumber(QIException):
    """O documento tem o formato certo e não existe: os dígitos verificadores
    não batem. É 422, e não 400: a API leu o pedido, e o valor é que é impossível."""

    code = "ONB005004"

    def __init__(self, rule) -> None:
        title = "Invalid document number"
        http_status = 422
        description = "The check digits of the document number do not match."
        translation = "O CPF ou CNPJ informado não é válido: os dígitos verificadores não batem."
        errors = [{"field": "document_number", "rule": rule, "message": "Dígitos verificadores não batem."}]
        super().__init__(title, self.code, http_status, description, translation, errors)


class OnboardingNotFound(QIException):
    """Inexistente ou de outra pessoa: o mesmo corpo nos dois casos (R8), para
    não revelar que a abertura existe."""

    code = "ONB005006"

    def __init__(self) -> None:
        title = "Onboarding not found"
        http_status = 404
        description = "The requested onboarding was not found."
        translation = "Abertura não encontrada."
        super().__init__(title, self.code, http_status, description, translation)


class CustomerNotFound(QIException):
    """Inexistente ou de outra pessoa, com o mesmo corpo (R8)."""

    code = "ONB005007"

    def __init__(self) -> None:
        title = "Customer not found"
        http_status = 404
        description = "The requested customer was not found."
        translation = "Cliente não encontrado."
        super().__init__(title, self.code, http_status, description, translation)


class TooManyAttempts(QIException):
    """Limite por documento ou por origem (RFC 05, Limites de pedidos). A
    mensagem não diz qual dos dois, para não ajudar quem testa CPFs."""

    code = "ONB005013"

    def __init__(self, retry_after_seconds) -> None:
        title = "Too many attempts"
        http_status = 429
        description = "Too many attempts for this document or from this origin."
        translation = "Muitas tentativas para este documento ou desta origem. Espere o tempo do Retry-After."
        headers = {"Retry-After": str(retry_after_seconds)}
        super().__init__(title, self.code, http_status, description, translation, headers=headers)


class InvalidDate(QIException):
    """O schema confere o formato (AAAA-MM-DD), mas não sabe quantos dias
    tem fevereiro nem que dia é hoje. Isso é conferido aqui."""

    code = "ONB005005"

    def __init__(self, field) -> None:
        title = "Invalid date"
        http_status = 422
        description = "The date does not exist or is in the future."
        translation = "A data informada não existe ou está no futuro."
        errors = [{"field": field, "rule": "valid_date", "message": "Data inexistente ou no futuro."}]
        super().__init__(title, self.code, http_status, description, translation, errors)
