from controllers.engine.context import MOVIMENTACAO
from controllers.engine.rule import Rule


class MesmaTitularidade(Rule):
    """Redutor: o mesmo documento nos dois lados.

    Desconta ate 10 pontos so da familia de valor individual. Nao toca em
    limite, rajada, aparelho ou rede: contas do mesmo dono tambem podem ser
    tomadas.
    """

    code = "MESMA_TITULARIDADE"
    axis = MOVIMENTACAO
    family = "confianca"

    def evaluate(self, ctx, params):
        if ctx.source_document != ctx.destination_document:
            return self.not_triggered()
        return self.triggered(-params[self.code]["discount"], "Transferencia entre contas do mesmo titular.")
