from controllers.engine.context import MOVIMENTACAO
from controllers.engine.reference import deviates
from controllers.engine.rule import Rule
from utils.money import brl


class Montante24h(Rule):
    """Aprovados da conta em 24h, mais este, acima de R$ 50.000.

    Com referencia, exige tambem o desvio do padrao do cliente: o corte
    fixo E o desvio. Sem referencia, so o corte.
    """

    code = "MONTANTE_24H"
    axis = MOVIMENTACAO
    family = "ritmo_e_acumulado"

    def evaluate(self, ctx, params):
        p = params[self.code]
        aprovado, _ = ctx.history.approved_sum_and_count(ctx.source_account.id, ctx.moment, 24 * 60)
        total = aprovado + ctx.amount
        if total <= p["limit"]:
            return self.not_triggered()
        desvio = deviates(ctx, params, "approved_amount", 24 * 60, total, p["deviation"])
        if desvio is not None and not desvio.deviates:
            return self.not_triggered(
                f"{brl(total)} em 24h passa do corte, mas e o padrao do cliente.", reference=desvio.describe(),
            )
        return self.triggered(
            p["points"], f"{brl(total)} em 24h (aprovados mais este), acima de {brl(p['limit'])}.",
            data_origin="history", reference=desvio.describe() if desvio else "fallback",
        )
