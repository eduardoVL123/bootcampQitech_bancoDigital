from controllers.engine.context import MOVIMENTACAO
from controllers.engine.profile import profile_for
from controllers.engine.rule import Rule
from utils.money import brl


class LimitePorPix(Rule):
    """Valor alto pede confirmacao; acima do teto operacional, bloqueia.

    Nao e teto do Pix: e o corte do perfil de demonstracao, configuravel na
    politica. Quando o perfil do proprio cliente diz que esse valor e normal
    para ele (o fornecedor que sempre recebe R$ 40 mil), o corte de
    confirmacao vira so informacao.
    """

    code = "LIMITE_POR_PIX"
    axis = MOVIMENTACAO
    family = "valor_individual"

    def evaluate(self, ctx, params):
        p = params[self.code]
        if ctx.amount > p["ceiling"]:
            return self.triggered(
                0, f"{brl(ctx.amount)} acima do teto operacional de {brl(p['ceiling'])}.", hard_block=True,
            )
        if ctx.amount < p["high"]:
            return self.not_triggered()
        perfil = profile_for(ctx, params)
        if perfil.compatible:
            return self.not_triggered(
                f"{brl(ctx.amount)} atinge o corte de {brl(p['high'])}, mas e compativel com o perfil "
                f"do cliente (referencia {perfil.reference}).",
            )
        return self.triggered(p["points"], f"{brl(ctx.amount)} atinge o corte de confirmacao de {brl(p['high'])}.")
