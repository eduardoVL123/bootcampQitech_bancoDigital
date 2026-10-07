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


class AccountNotActive(QIException):
    """409: o pedido e possivel, o ESTADO de agora e que nao deixa."""

    code = "QIT002011"

    def __init__(self, account_key, status) -> None:
        title = "Account does not allow movement"
        http_status = 409
        description = f"Account {account_key} is {status} and cannot be moved."
        translation = "Esta conta não movimenta no estado atual."
        super().__init__(title, self.code, http_status, description, translation)


class InsufficientBalance(QIException):
    """409, e nao 422.

    A MDN define 409 como conflito com o estado atual do servidor, e e
    exatamente isso: o pedido e possivel em si, o saldo de agora e que
    nao deixa. O 422 fica para o pedido impossivel por ele mesmo.
    """

    code = "QIT002012"

    def __init__(self, account_key) -> None:
        title = "Insufficient balance"
        http_status = 409
        description = f"Account {account_key} does not have enough balance."
        translation = "Saldo insuficiente."
        super().__init__(title, self.code, http_status, description, translation)


class PostingKeyReused(QIException):
    code = "QIT002016"

    def __init__(self, posting_key) -> None:
        title = "Posting key reused with a different set of entries"
        http_status = 409
        description = f"Posting key {posting_key} was already used with other entries."
        translation = "Esta chave já foi usada para outro conjunto de lançamentos."
        super().__init__(title, self.code, http_status, description, translation)


class PostingDoesNotSumZero(QIException):
    """422: o pedido e impossivel por ele mesmo, em qualquer estado.

    Um conjunto que nao soma zero cria ou destroi dinheiro. A trigger
    adiada do banco tambem recusa no COMMIT; esta checagem existe para
    o cliente receber um erro nomeado em vez de um 500.
    """

    code = "QIT002017"

    def __init__(self, total) -> None:
        title = "Entries do not sum to zero"
        http_status = 422
        description = f"The entries sum to {total}, and a posting must sum to zero."
        translation = "Os lançamentos precisam somar zero."
        super().__init__(title, self.code, http_status, description, translation)


class TransactionShapeInvalid(QIException):
    """422: o pedido e impossivel por ele mesmo, em qualquer estado.

    Deposito com origem, transferencia sem destino, transferencia para
    a propria conta. Nao e o estado do banco que recusa: e o pedido que
    nao faz sentido.
    """

    code = "QIT002019"

    def __init__(self, motivo) -> None:
        title = "Transaction shape is invalid"
        http_status = 422
        description = f"The transaction is invalid: {motivo}."
        translation = "O pedido não combina com o tipo de transação."
        super().__init__(title, self.code, http_status, description, translation)


class IdempotencyKeyReused(QIException):
    """409: a mesma chave chegou com OUTRO pedido.

    Repetir o mesmo pedido devolve o original. Repetir a chave com um
    pedido diferente e erro do cliente, e nao pode ser silencioso: um
    dos dois pedidos nao seria executado sem ninguem perceber.
    """

    code = "QIT002020"

    def __init__(self, idempotency_key) -> None:
        title = "Idempotency key reused with a different request"
        http_status = 409
        description = f"Idempotency key {idempotency_key} was already used with another request."
        translation = "Esta chave já foi usada para outro pedido."
        super().__init__(title, self.code, http_status, description, translation)


class MissingIdempotencyKey(QIException):
    code = "QIT002021"

    def __init__(self) -> None:
        title = "Idempotency-Key header is required"
        http_status = 400
        description = "Every movement requires the Idempotency-Key header."
        translation = "O cabeçalho Idempotency-Key é obrigatório."
        super().__init__(title, self.code, http_status, description, translation)


class InvalidStatementCursor(QIException):
    """400: o cursor nao foi emitido por este servidor, ou nao e desta conta."""

    code = "QIT002015"

    def __init__(self) -> None:
        title = "Invalid statement cursor"
        http_status = 400
        description = "The cursor was not issued by this server, or belongs to another account."
        translation = "O cursor do extrato é inválido."
        super().__init__(title, self.code, http_status, description, translation)
