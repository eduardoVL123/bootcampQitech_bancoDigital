from datetime import timedelta

from controllers.engine.context import MOVIMENTACAO
from controllers.engine.rule import Rule


class ContaReativada(Rule):
    """Conta antiga, com atividade antiga observada, parada ha 60 dias, que volta de uma vez.

    Conta comprada ou tomada costuma ficar parada e ser usada de repente. O
    primeiro contato com o motor nao e reativacao: sem atividade antiga
    observada, nao ha intervalo para medir.
    """

    code = "CONTA_REATIVADA"
    axis = MOVIMENTACAO
    family = "ciclo_da_origem"

    def evaluate(self, ctx, params):
        p = params[self.code]
        idade = ctx.moment - ctx.source_account.opening_date
        if idade < timedelta(days=p["min_account_age_days"]):
            return self.not_triggered()
        inicio_da_rajada = ctx.moment - timedelta(minutes=p["burst_minutes"])
        anterior = ctx.history.last_attempt_before(ctx.source_account.id, inicio_da_rajada)
        if anterior is None:
            return self.not_triggered("Sem atividade antiga observada.")
        parada = inicio_da_rajada - anterior
        if parada < timedelta(days=p["idle_days"]):
            return self.not_triggered()
        tentativas = ctx.history.attempts(ctx.source_account.id, ctx.moment, p["burst_minutes"]) + 1
        if tentativas >= p["burst_count"] or ctx.amount > p["min_amount"]:
            return self.triggered(
                p["points"], f"Conta parada ha {parada.days} dias voltou com {tentativas} tentativas em "
                f"{p['burst_minutes']} min.", data_origin="history",
            )
        return self.not_triggered()
