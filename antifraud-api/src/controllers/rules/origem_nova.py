from controllers.engine.context import MOVIMENTACAO
from controllers.engine.rule import Rule
from utils.money import brl


class OrigemNova(Rule):
    """Conta pagadora com menos de 48 horas movimentando valor relevante.

    Idade da conta e contexto, nao prova: conta recem-aberta movimentando e
    o comeco tipico de conta laranja ou de cadastro com dado roubado.
    """

    code = "ORIGEM_NOVA"
    axis = MOVIMENTACAO
    family = "ciclo_da_origem"

    def evaluate(self, ctx, params):
        p = params[self.code]
        horas = (ctx.moment - ctx.source_account.opening_date).total_seconds() / 3600
        if horas < p["max_age_hours"] and ctx.amount > p["min_amount"]:
            return self.triggered(p["points"], f"Conta pagadora aberta ha {horas:.0f} h movimentando {brl(ctx.amount)}.")
        return self.not_triggered()
