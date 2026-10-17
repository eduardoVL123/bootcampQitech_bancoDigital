from controllers.engine.context import DESTINO
from controllers.engine.rule import Rule
from utils.money import brl


class ContraparteInedita(Rule):
    """Primeiro pagamento aprovado deste titular para aquele titular, acima de R$ 1.000.

    Todo aluguel um dia foi o primeiro: sozinho vale pouco, e soma com destino
    novo ou valor fora do perfil. A relacao e por titular (documento), nao
    por conta.
    """

    code = "CONTRAPARTE_INEDITA"
    axis = DESTINO
    family = "novidade_do_destino"

    def evaluate(self, ctx, params):
        p = params[self.code]
        if ctx.source_document == ctx.destination_document or ctx.amount <= p["min_amount"]:
            return self.not_triggered()
        if ctx.history.approved_to_document(ctx.source_document, ctx.destination_document, ctx.moment):
            return self.not_triggered()
        return self.triggered(p["points"], f"Primeiro pagamento a este titular, de {brl(ctx.amount)}.",
                              data_origin="history")
