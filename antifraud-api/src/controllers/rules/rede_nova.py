from controllers.engine.context import ACESSO
from controllers.engine.rule import Rule


class RedeNova(Rule):
    """A rede do IP (o /24) nunca apareceu para este titular, que ja tem historico.

    Mesma ideia do aparelho novo, mais fraca: rede muda mais que aparelho
    (casa, trabalho, 4G). Esta na mesma familia, entao nao soma com ele.
    """

    code = "REDE_NOVA"
    axis = ACESSO
    family = "mudanca_de_acesso"

    def evaluate(self, ctx, params):
        p = params[self.code]
        anteriores = ctx.history.prior_attempts_of_document(ctx.source_document, ctx.moment)
        if anteriores < p["min_prior_attempts"]:
            return self.not_triggered()
        if ctx.history.network_seen(ctx.source_document, ctx.network, ctx.moment):
            return self.not_triggered()
        return self.triggered(p["points"], f"Rede {ctx.network} nunca usada por este titular.", data_origin="history")
