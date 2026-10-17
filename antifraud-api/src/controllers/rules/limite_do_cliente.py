from controllers.engine.context import MOVIMENTACAO
from controllers.engine.rule import Rule
from utils.money import brl


class LimiteDoCliente(Rule):
    """Pix acima do limite que o proprio titular escolheu, o vigente no instante.

    Bloqueio prioritario: passar do limite nao e duvida, e contra a vontade
    do dono da conta. Sem limite cadastrado, a regra nao se aplica: ausencia
    de cadastro nao e limite zero.
    """

    code = "LIMITE_DO_CLIENTE"
    axis = MOVIMENTACAO
    family = "uso_de_limites"

    def evaluate(self, ctx, params):
        vigente = ctx.limits.effective(ctx.source_account.id, ctx.moment)
        if vigente is None:
            return self.not_triggered()
        if ctx.amount > vigente.amount:
            return self.triggered(0, f"{brl(ctx.amount)} acima do limite de {brl(vigente.amount)} escolhido pelo titular.",
                                  hard_block=True, data_origin="history")
        return self.not_triggered(f"Dentro do limite de {brl(vigente.amount)}.")
