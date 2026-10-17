from controllers.engine.context import MOVIMENTACAO
from controllers.engine.rule import Rule
from utils.money import brl


class AumentoPendente(Rule):
    """Um pedido de aumento de limite ainda nao vigente, e este Pix perto do limite atual.

    Subir o limite e esvaziar a conta logo depois e o roteiro da conta
    tomada. O aumento so vale em 24h; usar mais da metade do limite atual
    nesse meio-tempo e o sinal.
    """

    code = "AUMENTO_PENDENTE"
    axis = MOVIMENTACAO
    family = "uso_de_limites"

    def evaluate(self, ctx, params):
        p = params[self.code]
        pendente = ctx.limits.pending_increase(ctx.source_account.id, ctx.moment, p["delay_hours"])
        if pendente is None:
            return self.not_triggered()
        vigente = ctx.limits.effective(ctx.source_account.id, ctx.moment)
        if vigente is None or ctx.amount <= p["ratio"] * vigente.amount:
            return self.not_triggered()
        return self.triggered(
            p["points"], f"{brl(ctx.amount)} com um aumento para {brl(pendente.amount)} pedido e ainda nao vigente "
            f"(limite atual {brl(vigente.amount)}).", data_origin="history",
        )
