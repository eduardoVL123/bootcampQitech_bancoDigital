from controllers.engine.context import DESTINO
from controllers.engine.rule import Rule


class RedeSuspeita(Rule):
    """O destino esta a ate dois saltos de uma conta com evidencia qualificada.

    Por SQL, sem banco de grafos nem worker: a ancora pagou o destino, ou
    pagou alguem que pagou o destino, nos ultimos 30 dias, por Pix
    aprovados. O caminho vai no metadata. Vizinho nao vira ancora nova.

    Dois cuidados contra contaminar quem nao tem nada com a rede:
    - aresta de centavos nao conta (`min_edge_amount`): sem o corte, uma
      ancora que e cliente da casa marcava qualquer conta com um Pix de
      R$ 0,01, e todo mundo que pagasse aquela conta levava +30;
    - destino que o pagador ja paga nao ganha a suspeita: para quem ja tem
      relacao com aquela conta, "a ancora tambem pagou ela" nao diz nada.
    """

    code = "REDE_SUSPEITA"
    axis = DESTINO
    family = "fluxo_e_rede"

    def evaluate(self, ctx, params):
        p = params[self.code]
        ancoras = ctx.reputation.anchors(ctx.moment) - {ctx.destination_document}
        caminho = ctx.history.network_path(ancoras, ctx.destination_document, ctx.moment, p["days"],
                                           p["min_edge_amount"])
        if caminho is None:
            return self.not_triggered()
        if ctx.history.approved_to_document(ctx.source_document, ctx.destination_document, ctx.moment):
            return self.not_triggered("Destino ja pago antes por este titular: o vinculo com a ancora nao muda isso.")
        saltos, documentos = caminho
        return self.triggered(p["points"], f"Destino a {saltos} salto(s) de uma conta com evidencia de fraude.",
                              data_origin="history", hops=saltos, path=documentos)
