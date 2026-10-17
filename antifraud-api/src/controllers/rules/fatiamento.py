from controllers.engine.context import MOVIMENTACAO
from controllers.engine.reference import deviates
from controllers.engine.rule import Rule
from utils.money import brl


class Fatiamento(Rule):
    """Tres ou mais aprovados na ultima hora e a soma com este acima de R$ 10.000.

    Varios Pix medios na mesma hora, cada um abaixo do corte de valor.
    Dispara a partir da quarta operacao.
    """

    code = "FATIAMENTO"
    axis = MOVIMENTACAO
    family = "ritmo_e_acumulado"

    def evaluate(self, ctx, params):
        p = params[self.code]
        soma, quantidade = ctx.history.approved_sum_and_count(ctx.source_account.id, ctx.moment, p["window_minutes"])
        total = soma + ctx.amount
        if quantidade < p["min_prior"] or total <= p["limit"]:
            return self.not_triggered()
        desvio = deviates(ctx, params, "approved_amount", p["window_minutes"], total, p["deviation"])
        if desvio is not None and not desvio.deviates:
            return self.not_triggered(
                f"{brl(total)} em {quantidade + 1} Pix na hora, dentro do padrao do cliente.",
                reference=desvio.describe(),
            )
        return self.triggered(
            p["points"], f"{quantidade} aprovados na ultima hora e {brl(total)} somando este.",
            data_origin="history", reference=desvio.describe() if desvio else "fallback",
        )
