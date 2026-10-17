from controllers.engine.context import DESTINO
from controllers.engine.rule import Rule


class RedeSuspeita(Rule):
    """O destino esta a ate dois saltos de uma conta com evidencia qualificada.

    Por SQL, sem banco de grafos nem worker: a ancora pagou o destino, ou
    pagou alguem que pagou o destino, nos ultimos 30 dias, por Pix
    aprovados. O caminho vai no metadata. Vizinho nao vira ancora nova.
    """

    code = "REDE_SUSPEITA"
    axis = DESTINO
    family = "fluxo_e_rede"

    def evaluate(self, ctx, params):
        p = params[self.code]
        ancoras = ctx.reputation.anchors(ctx.moment) - {ctx.destination_document}
        caminho = ctx.history.network_path(ancoras, ctx.destination_document, ctx.moment, p["days"])
        if caminho is None:
            return self.not_triggered()
        saltos, documentos = caminho
        return self.triggered(p["points"], f"Destino a {saltos} salto(s) de uma conta com evidencia de fraude.",
                              data_origin="history", hops=saltos, path=documentos)
