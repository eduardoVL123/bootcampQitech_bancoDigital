from controllers.engine.context import FACIAL_DOCUMENT, MOVIMENTACAO
from controllers.engine.rule import Rule
from utils.money import brl


class SondagemDeLimite(Rule):
    """Depois de um 2FA ou de uma recusa, tentar de novo com valor menor.

    Uma reducao pode ser ajuste legitimo (+30). Duas reducoes seguidas,
    cada uma depois de uma decisao restritiva, e ir baixando ate passar
    (+50 e verificacao reforcada).
    """

    code = "SONDAGEM_DE_LIMITE"
    axis = MOVIMENTACAO
    family = "uso_de_limites"

    def evaluate(self, ctx, params):
        p = params[self.code]
        anteriores = ctx.history.restrictive_attempts(ctx.source_account.id, ctx.moment, p["window_minutes"])
        valores = [int(linha.amount) for linha in anteriores] + [ctx.amount]
        reducoes = 0
        for indice in range(len(valores) - 1, 0, -1):
            if valores[indice] < valores[indice - 1]:
                reducoes += 1
            else:
                break
        if reducoes == 0:
            return self.not_triggered()
        sequencia = " -> ".join(brl(v) for v in valores[-(reducoes + 1):])
        if reducoes >= 2:
            return self.triggered(p["two"], f"Valores baixando depois de decisoes restritivas: {sequencia}.",
                                  floor=FACIAL_DOCUMENT, data_origin="history")
        return self.triggered(p["one"], f"Valor menor depois de uma decisao restritiva: {sequencia}.",
                              data_origin="history")
