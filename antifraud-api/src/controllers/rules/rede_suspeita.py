from controllers.engine.context import DESTINO
from controllers.engine.rule import Rule
from utils.money import brl


class RedeSuspeita(Rule):
    """O destino esta ligado, pelo dinheiro, a uma conta com fraude confirmada.

    Por SQL, sem banco de grafos nem worker, nos ultimos 30 dias. Os dois
    sentidos do dinheiro:
    - da ancora para o destino: a ancora pagou o destino (1 salto), ou pagou
      alguem que pagou o destino (2 saltos), por Pix aprovados. Um salto e
      dinheiro direto da fraude; dois ja e vizinhanca, e o peso cai;
    - do destino para a ancora: o destino repassou para a ancora o dinheiro
      que tinha acabado de receber de gente sem vinculo com ele. E a laranja
      que manda para o chefe. So pagar a ancora nao conta, porque a vitima
      tambem pagou o golpista (ver history.forwarded_to_anchor).
    O caminho vai no metadata. Vizinho nao vira ancora nova, e so a fraude
    confirmada e ancora: a palavra de uma fonte so nao espalha suspeita
    (ver reputation.anchors).

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
        achados = []
        if caminho is not None:
            saltos, documentos = caminho
            pontos = p.get("points_by_hops", {}).get(str(saltos), p["points"])
            achados.append((pontos, f"Destino a {saltos} salto(s) de uma conta com fraude confirmada.",
                            {"hops": saltos, "direction": "from_anchor", "path": documentos}))
        reverso = p.get("reverse")
        if reverso and (caminho is None or caminho[0] > 1):
            repasse = ctx.history.forwarded_to_anchor(ancoras, ctx.destination_document, ctx.moment, p["days"],
                                                      p["min_edge_amount"], reverso["hours"], reverso["min_payers"],
                                                      reverso["share"])
            if repasse is not None:
                ancora, pagadores, recebido, enviado = repasse
                achados.append((reverso["points"], f"Destino repassou {brl(enviado)} para uma conta com fraude "
                                f"confirmada, logo depois de receber {brl(recebido)} de {pagadores} pagadores sem vinculo.",
                                {"hops": 1, "direction": "to_anchor", "path": [ctx.destination_document, ancora]}))
        if not achados:
            return self.not_triggered()
        if ctx.history.approved_to_document(ctx.source_document, ctx.destination_document, ctx.moment):
            return self.not_triggered("Destino ja pago antes por este titular: o vinculo com a ancora nao muda isso.")
        pontos, detalhe, extra = max(achados, key=lambda achado: achado[0])
        return self.triggered(pontos, detalhe, data_origin="history", **extra)
