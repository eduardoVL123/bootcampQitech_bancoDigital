"""Os erros gerais, que toda API tem (schema, token, credencial, rota).

Na onboarding-api eles usam o prefixo ONB, como os da faixa dela: todo erro
que esta API responde começa com ONB (decisão de 06/10, RFC 05 v0.6). Os
códigos que só o gateway responde continuam QIT, porque são de outra API.
"""
import sys
import inspect


def error_verification():
    clsmembers = inspect.getmembers(sys.modules["errors"], inspect.isclass)

    errors_dict = dict()
    for _class in clsmembers:
        class_name = _class[0]
        class_type = _class[1]
        is_custom_exception = False
        if issubclass(class_type, QIException) and class_name != "QIException":
            is_custom_exception = True

        if is_custom_exception:
            code = class_type.code
            if errors_dict.get(code) is not None:
                used_class_name = errors_dict[code]
                raise Exception(f"The code {code} is being used twice: In {class_name} and {used_class_name}")
            errors_dict[code] = class_name
    return


class QIException(Exception):
    """Todo erro previsto da API.

    `errors` é a lista de {field, rule, message} que a RFC 05 pede no corpo,
    e `headers` leva cabeçalhos que a recusa exige (Retry-After no 429,
    WWW-Authenticate no 401). Nenhum dos dois pode trazer CPF, CNPJ ou renda.
    """

    def __init__(self, title, code, http_status, description, translation, errors=None, headers=None) -> None:
        self.title = title
        self.description = description
        self.translation = translation
        self.code = code
        self.http_status = http_status
        self.errors = errors or []
        self.headers = headers or {}


class MethodNotAllowed(QIException):
    code = "ONB000405"

    def __init__(self) -> None:
        title = "Method not allowed"
        http_status = 405
        description = "The requested method is forbidden for this resource."
        translation = "O método desejado não foi encontrado para esse recurso."
        super().__init__(title, self.code, http_status, description, translation)


class InternalError(QIException):
    code = "ONB000500"

    def __init__(self) -> None:
        title = "Internal Error"
        http_status = 500
        description = "An internal error has occurred and its being investigated."
        translation = "Um erro interno aconteceu e está sendo investigado."
        super().__init__(title, self.code, http_status, description, translation)


class NotFoundResource(QIException):
    code = "ONB000404"

    def __init__(self) -> None:
        title = "Resource not Found"
        http_status = 404
        description = "The requested resource could not be found but may be available in the future. Subsequent requests by the client are permissible."
        translation = "O resource solicitado não pode ser encontrado, mas pode estar disponível no futuro. Requests subsequentes do cliente são permitidos."
        super().__init__(title, self.code, http_status, description, translation)


class InvalidSchema(QIException):
    code = "ONB000001"

    def __init__(self, __description, errors=None) -> None:
        title = "Bad Request"
        http_status = 400
        description = __description
        translation = "Payload Inválido"
        super().__init__(title, self.code, http_status, description, translation, errors)


class ForbiddenNotInternal(QIException):
    code = "ONB000002"

    def __init__(self) -> None:
        title = "Forbidden"
        http_status = 403
        description = "Request must be internal"
        translation = "Requisição precisa ser interna"
        super().__init__(title, self.code, http_status, description, translation)


# As recusas de credencial seguem o padrão OAuth 2.0 (RFC 00 e RFC 05):
# o cabeçalho WWW-Authenticate diz ao cliente o que fazer.
BEARER_REALM = 'Bearer realm="banco"'


class MissingCredential(QIException):
    code = "ONB000003"

    def __init__(self) -> None:
        title = "Missing credential"
        http_status = 401
        description = "Send the credential in the Authorization header, as a Bearer token."
        translation = "Envie a credencial no cabeçalho Authorization, no formato Bearer."
        headers = {"WWW-Authenticate": BEARER_REALM}
        super().__init__(title, self.code, http_status, description, translation, headers=headers)


class InvalidCredential(QIException):
    code = "ONB000006"

    def __init__(self) -> None:
        title = "Invalid credential"
        http_status = 401
        description = "The credential has an invalid format or signature."
        translation = "A credencial tem formato ou assinatura inválidos."
        headers = {"WWW-Authenticate": f'{BEARER_REALM}, error="invalid_token"'}
        super().__init__(title, self.code, http_status, description, translation, headers=headers)


class ExpiredCredential(QIException):
    code = "ONB000007"

    def __init__(self) -> None:
        title = "Expired credential"
        http_status = 401
        description = "The credential has expired. Repeat POST /onboarding with the same key to get a new one."
        translation = "A credencial venceu. Repita o POST /onboarding com a mesma chave para receber outra."
        headers = {"WWW-Authenticate": f'{BEARER_REALM}, error="invalid_token", error_description="token expirado"'}
        super().__init__(title, self.code, http_status, description, translation, headers=headers)


class InsufficientScope(QIException):
    """A credencial é válida, mas o escopo dela não dá acesso à rota: a do
    cliente (onboarding) numa rota só de compliance."""

    code = "ONB000008"

    def __init__(self, scope) -> None:
        title = "Insufficient scope"
        http_status = 403
        description = f"This route requires a credential with the {scope} scope."
        translation = f"Esta rota exige uma credencial com o escopo {scope}."
        headers = {"WWW-Authenticate": f'{BEARER_REALM}, error="insufficient_scope", scope="{scope}"'}
        super().__init__(title, self.code, http_status, description, translation, headers=headers)


class InvalidIdempotencyKey(QIException):
    """O gateway já confere a chave (RFC 00) e responde QIT000011. A
    onboarding-api confere de novo, com o código dela, para não gravar
    pedido sem chave quando é chamada sem o gateway na frente (decisão D7
    do plano de testes)."""

    code = "ONB000011"

    def __init__(self, rule) -> None:
        title = "Invalid idempotency key"
        http_status = 400
        description = "The X-Idempotency-Key header is missing or is not a UUID."
        translation = "O cabeçalho X-Idempotency-Key está ausente ou não é um UUID."
        errors = [{"field": "X-Idempotency-Key", "rule": rule, "message": "Mande um UUID novo a cada pedido."}]
        super().__init__(title, self.code, http_status, description, translation, errors)


class IdempotencyKeyReused(QIException):
    code = "ONB000012"

    def __init__(self) -> None:
        title = "Idempotency key reused"
        http_status = 409
        description = "This X-Idempotency-Key was already used with a different request."
        translation = "Esta X-Idempotency-Key já foi usada com outro pedido."
        super().__init__(title, self.code, http_status, description, translation)


class InvalidParameter(QIException):
    code = "ONB000010"

    def __init__(self, description) -> None:
        title = "Invalid Parameter"
        http_status = 400
        translation = "Parâmetros inválidos foram fornecidos na requisição."
        super().__init__(title, self.code, http_status, description, translation)
