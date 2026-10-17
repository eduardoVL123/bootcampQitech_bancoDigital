from controllers.engine.context import FACIAL, MOVIMENTACAO
from controllers.engine.profile import profile_for
from controllers.engine.rule import Rule
from utils.money import brl


class PerfilSemHistorico(Rule):
    """Sem referencia nenhuma, e valor alto: verificacao facial.

    Cliente sem historico nao e fraude, mas tambem nao e perfil normal. Soma
    pouco (+20) e garante ao menos a verificacao facial.
    """

    code = "PERFIL_SEM_HISTORICO"
    axis = MOVIMENTACAO
    family = "valor_individual"

    def evaluate(self, ctx, params):
        p = params[self.code]
        if profile_for(ctx, params).evaluable or ctx.amount <= p["min_amount"]:
            return self.not_triggered()
        return self.triggered(p["points"], f"{brl(ctx.amount)} sem historico de valores para comparar.",
                              floor=FACIAL, data_origin="history")
