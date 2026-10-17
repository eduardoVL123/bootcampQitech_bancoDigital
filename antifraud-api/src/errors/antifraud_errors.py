"""Os erros da antifraud-api, na faixa QIT006xxx.

Recusa de entrada nao e decisao de fraude: um Pix analisado sempre volta
201 (ou 200 no replay), com o status da analise. Estes erros sao para o
pedido que nem chega a ser analisado.
"""
from errors.base_error import QIException


class NotFoundPixAnalysis(QIException):
    code = "QIT006001"

    def __init__(self, pix_id) -> None:
        title = "Pix analysis not found"
        http_status = 404
        description = f"There is no analysis for the Pix {pix_id}."
        translation = "Não existe análise para este Pix."
        super().__init__(title, self.code, http_status, description, translation)


class TransactionDateInTheFuture(QIException):
    """A data do Pix esta mais de cinco minutos a frente do relogio do servidor.

    422 e nao 400: o formato esta certo, e o que nao pode existir e o valor.
    """

    code = "QIT006002"

    def __init__(self, transaction_date, tolerance_seconds) -> None:
        title = "Transaction date in the future"
        http_status = 422
        description = (
            f"The date {transaction_date} is more than {tolerance_seconds} seconds ahead of the server clock."
        )
        translation = "A data informada está no futuro."
        super().__init__(title, self.code, http_status, description, translation)


class TransactionBeforeAccountOpening(QIException):
    code = "QIT006003"

    def __init__(self, side) -> None:
        title = "Transaction before account opening"
        http_status = 422
        description = f"The date is earlier than the opening_date of the {side}."
        translation = "A data é anterior à abertura de uma das contas."
        super().__init__(title, self.code, http_status, description, translation)


class PixIdReused(QIException):
    """O mesmo id com outro conteudo.

    O mesmo id e o mesmo Pix (resposta da organizacao em 17/10): repetir o
    pedido devolve a analise gravada. Se o conteudo mudou, nao e repeticao,
    e outro Pix tentando usar um id que ja tem dono.
    """

    code = "QIT006004"

    def __init__(self, pix_id) -> None:
        title = "Pix id already used with another content"
        http_status = 409
        description = f"The Pix {pix_id} was already analyzed with a different content. A new Pix needs a new id."
        translation = "Este id já foi usado por outro Pix. Um Pix novo precisa de um id novo."
        super().__init__(title, self.code, http_status, description, translation)
