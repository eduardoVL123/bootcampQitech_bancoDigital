from datetime import timedelta

from controllers.engine.context import MOVIMENTACAO, NONE
from controllers.engine.rule import Rule
from utils.money import brl


class ContaReativada(Rule):
    """Conta antiga, com atividade antiga observada, parada ha 60 dias, que volta movimentando.

    Conta comprada ou tomada costuma ficar parada e ser usada de repente. O
    primeiro contato com o motor nao e reativacao: sem atividade antiga
    observada, nao ha intervalo para medir.

    A volta e o primeiro dia (`window_hours`) depois da parada, e nao so a
    primeira hora: quem volta com dois Pix por hora fica abaixo de qualquer
    rajada, mas no dia ja sao varios. Dispara com `burst_count` tentativas
    no dia, com `window_amount` somados, ou com um Pix acima de
    `min_amount`. Pede a facial (`floor`): na conta tomada, quem esta do
    outro lado nao passa; o dono que so voltou a usar passa uma vez.

    A janela do dia, a soma e o piso entraram na politica versao 2. Com a
    versao 1, vale a regra de antes: 3 tentativas em `burst_minutes`, ou um
    Pix acima de `min_amount`, sem piso.
    """

    code = "CONTA_REATIVADA"
    axis = MOVIMENTACAO
    family = "ciclo_da_origem"

    def evaluate(self, ctx, params):
        p = params[self.code]
        idade = ctx.moment - ctx.source_account.opening_date
        if idade < timedelta(days=p["min_account_age_days"]):
            return self.not_triggered()
        minutos = p["window_hours"] * 60 if "window_hours" in p else p["burst_minutes"]
        inicio_da_volta = ctx.moment - timedelta(minutes=minutos)
        anterior = ctx.history.last_attempt_before(ctx.source_account.id, inicio_da_volta)
        if anterior is None:
            return self.not_triggered("Sem atividade antiga observada.")
        parada = inicio_da_volta - anterior
        if parada < timedelta(days=p["idle_days"]):
            return self.not_triggered()
        tentativas, soma = ctx.history.attempts_count_and_amount(ctx.source_account.id, ctx.moment, minutos)
        tentativas, soma = tentativas + 1, soma + ctx.amount
        soma_alta = "window_amount" in p and soma > p["window_amount"]
        if tentativas >= p["burst_count"] or soma_alta or ctx.amount > p["min_amount"]:
            return self.triggered(
                p["points"], f"Conta parada ha {parada.days} dias voltou com {tentativas} tentativas e "
                f"{brl(soma)} em {minutos // 60} h.", floor=p.get("floor", NONE), data_origin="history",
            )
        return self.not_triggered()
