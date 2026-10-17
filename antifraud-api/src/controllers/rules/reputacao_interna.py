from controllers.engine.context import DESTINO
from controllers.engine.rule import Rule


class ReputacaoInterna(Rule):
    """O documento destino ou o aparelho estao na lista interna vigente.

    A lista tem casos confirmados (semeados) e o "nao fui eu" do titular
    depois de um desafio. Nunca a decisao do proprio motor: uma rejeicao por
    limite nao diz nada sobre o recebedor, e alimentar a lista com ela faria
    um falso positivo gerar outros em cadeia.
    """

    code = "REPUTACAO_INTERNA"
    axis = DESTINO
    family = "reputacao"

    def evaluate(self, ctx, params):
        p = params[self.code]
        for tipo, valor in (("document", ctx.destination_document), ("device", ctx.device_id)):
            entrada = ctx.watchlist.listed(tipo, valor, ctx.moment)
            if entrada is not None:
                alvo = "Documento destino" if tipo == "document" else "Aparelho"
                return self.triggered(p["points"], f"{alvo} na lista interna ({entrada.report_type}, {entrada.creator}).",
                                      data_origin="history", evidence_ids=[entrada.evidence_id],
                                      creator=entrada.creator)
        return self.not_triggered()
