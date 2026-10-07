from errors import QIException


class NotFoundAccount(QIException):
    """404, e nao 403, quando a conta nao e de quem pede.

    A MDN registra que o servidor pode responder 404 no lugar de 403
    para esconder a existencia do recurso de quem nao tem direito a ele.
    Responder 403 confirmaria que a conta existe. E a R8, e e o item
    numero 1 do OWASP API Security Top 10.
    """

    code = "QIT002010"

    def __init__(self, account_key) -> None:
        title = "Account not found"
        http_status = 404
        description = f"Account with key {account_key} was not found."
        translation = "Conta não encontrada."
        super().__init__(title, self.code, http_status, description, translation)
