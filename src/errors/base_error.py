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
    def __init__(self, title, code, http_status, description, translation, headers=None) -> None:
        self.title = title
        self.description = description
        self.translation = translation
        self.code = code
        self.http_status = http_status
        # Alguns erros precisam de cabecalho na resposta. O 401 e o
        # caso: a RFC 9110 diz que uma resposta 401 TEM de trazer o
        # WWW-Authenticate dizendo que esquema de autenticacao o
        # servidor aceita. Sem ele, o cliente nao sabe o que mandar.
        self.headers = headers or {}


class MethodNotAllowed(QIException):
    code = "QIT000405"

    def __init__(self) -> None:
        title = "Method not allowed"
        http_status = 405
        description = "The requested method is forbidden for this resource."
        translation = "O método desejado não foi encontrado para esse recurso."
        super().__init__(title, self.code, http_status, description, translation)


class InternalError(QIException):
    code = "QIT000500"

    def __init__(self) -> None:
        title = "Internal Error"
        http_status = 500
        description = "An internal error has occurred and its being investigated."
        translation = "Um erro interno aconteceu e está sendo investigado."
        super().__init__(title, self.code, http_status, description, translation)


class NotFoundResource(QIException):
    code = "QIT000404"

    def __init__(self) -> None:
        title = "Resource not Found"
        http_status = 404
        description = "The requested resource could not be found but may be available in the future. Subsequent requests by the client are permissible."
        translation = "O resource solicitado não pode ser encontrado, mas pode estar disponível no futuro. Requests subsequentes do cliente são permitidos."
        super().__init__(title, self.code, http_status, description, translation)


class InvalidSchema(QIException):
    code = "QIT000001"

    def __init__(self, __description) -> None:
        title = "Bad Request"
        http_status = 400
        description = __description
        translation = "Payload Inválido"
        super().__init__(title, self.code, http_status, description, translation)


class ForbiddenNotInternal(QIException):
    code = "QIT000002"

    def __init__(self) -> None:
        title = "Forbidden"
        http_status = 403
        description = "Request must be internal"
        translation = "Requisição precisa ser interna"
        super().__init__(title, self.code, http_status, description, translation)


class InvalidParameter(QIException):
    code = "QIT000010"

    def __init__(self, description) -> None:
        title = "Invalid Parameter"
        http_status = 400
        translation = "Parâmetros inválidos foram fornecidos na requisição."
        super().__init__(title, self.code, http_status, description, translation)


# A credencial do cliente, conferida em src/utils/credential.py.
# A faixa QIT000 e a dos erros gerais: credencial nao e assunto de
# conta, e toda API do ecossistema precisa dos mesmos quatro.
BEARER_REALM = 'Bearer realm="bootcamp"'


class MissingCredential(QIException):
    code = "QIT000003"

    def __init__(self) -> None:
        title = "Missing credential"
        http_status = 401
        description = "Send the credential in the Authorization header, as a Bearer token."
        translation = "Envie a credencial no cabeçalho Authorization, no formato Bearer."
        super().__init__(
            title, self.code, http_status, description, translation,
            headers={"WWW-Authenticate": BEARER_REALM},
        )


class InvalidCredential(QIException):
    code = "QIT000004"

    def __init__(self) -> None:
        title = "Invalid credential"
        http_status = 401
        description = "The credential is malformed or its signature does not match."
        translation = "A credencial está malformada ou a assinatura não confere."
        super().__init__(
            title, self.code, http_status, description, translation,
            headers={"WWW-Authenticate": BEARER_REALM + ', error="invalid_token"'},
        )


class ExpiredCredential(QIException):
    code = "QIT000005"

    def __init__(self) -> None:
        title = "Expired credential"
        http_status = 401
        description = "The credential has expired. Ask for a new one."
        translation = "A credencial venceu. Peça uma nova."
        super().__init__(
            title, self.code, http_status, description, translation,
            headers={"WWW-Authenticate": BEARER_REALM + ', error="invalid_token"'},
        )


class OperatorScopeRequired(QIException):
    """403 e nao 404, de proposito.

    A R8 manda esconder recurso de outra pessoa com 404. Aqui nao ha
    recurso alheio a esconder: a conta e do proprio cliente, e o que
    falta e permissao para a OPERACAO. Um 404 aqui mentiria dizendo
    que a conta dele nao existe.
    """

    code = "QIT000006"

    def __init__(self) -> None:
        title = "Operator scope required"
        http_status = 403
        description = "This operation requires a credential with the operator scope."
        translation = "Esta operação exige uma credencial com escopo de operador."
        super().__init__(title, self.code, http_status, description, translation)
