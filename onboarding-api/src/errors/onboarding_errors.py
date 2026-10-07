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


class DocumentNotFound(QIException):
    code = "ONB005016"

    def __init__(self) -> None:
        title = "Document not found"
        http_status = 404
        description = "The requested document side was not found for this onboarding."
        translation = "Este lado do documento não foi encontrado para esta abertura."
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


class OnboardingNotDraft(QIException):
    code = "ONB005008"

    def __init__(self) -> None:
        title = "Onboarding is not waiting for documents"
        http_status = 409
        description = "The onboarding is no longer in DRAFT and does not accept documents."
        translation = "A abertura não está em DRAFT e não espera mais documento."
        super().__init__(title, self.code, http_status, description, translation)


class RepeatedDocumentSide(QIException):
    """O RG tem dois lados, e a abertura guarda no máximo duas imagens. Uma
    terceira imagem sempre repete um lado, e por isso as duas regras viram
    uma recusa só."""

    code = "ONB005009"

    def __init__(self, field) -> None:
        title = "Repeated document side"
        http_status = 409
        description = "The upload would exceed two images or repeats a side already sent."
        translation = "O envio passaria de duas imagens do RG, ou repete um lado já enviado."
        errors = [{"field": field, "rule": "repeated_side", "message": "Este lado do RG já foi enviado."}]
        super().__init__(title, self.code, http_status, description, translation, errors)


class FileTooLarge(QIException):
    code = "ONB005011"

    def __init__(self, field, max_megabytes) -> None:
        title = "File too large"
        http_status = 413
        description = f"Each image must have at most {max_megabytes} MB."
        translation = f"Cada imagem pode ter até {max_megabytes} MB."
        errors = [{"field": field, "rule": "max_size", "message": f"Até {max_megabytes} MB."}]
        super().__init__(title, self.code, http_status, description, translation, errors)


class UnsupportedFileType(QIException):
    """O tipo vem dos primeiros bytes do arquivo. O nome e o Content-Type são
    o que o cliente diz, e não provam nada."""

    code = "ONB005012"

    def __init__(self, field) -> None:
        title = "Unsupported file type"
        http_status = 422
        description = "The file is neither JPEG nor PNG."
        translation = "O arquivo não é JPEG nem PNG."
        errors = [{"field": field, "rule": "file_type", "message": "Só JPEG ou PNG."}]
        super().__init__(title, self.code, http_status, description, translation, errors)


class BucketUnavailable(QIException):
    code = "ONB005015"

    def __init__(self) -> None:
        title = "Document storage unavailable"
        http_status = 503
        description = "The document storage did not answer. Nothing was saved; repeat with the same key."
        translation = "O bucket não respondeu e nada foi gravado. Repita com a mesma chave."
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
