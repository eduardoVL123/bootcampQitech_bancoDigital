from controllers.engine.context import MOVIMENTACAO
from controllers.engine.profile import profile_for
from controllers.engine.rule import Rule
from utils.money import brl


class Perfil(Rule):
    """O valor fora do padrao do proprio cliente: z modificado por mediana e MAD.

    A mediana nao se deixa puxar pelo proprio aluguel, como a media se
    deixaria. Exige diferenca de R$ 500 e um multiplo da mediana, para nao
    disparar por z alto em valor pequeno. So o desvio para cima conta.
    """

    code = "PERFIL"
    axis = MOVIMENTACAO
    family = "valor_individual"

    def evaluate(self, ctx, params):
        perfil = profile_for(ctx, params)
        if not perfil.evaluable:
            return self.not_evaluable("Sem referencia de valores aprovados para comparar.")
        if perfil.level is None:
            return self.not_triggered(**perfil.describe())
        return self.triggered(
            perfil.points, f"{brl(ctx.amount)} contra mediana de {brl(round(perfil.m))} na referencia "
            f"{perfil.reference} ({perfil.sample} pagamentos).", data_origin="history", **perfil.describe(),
        )
