from controllers.engine.context import ACESSO
from controllers.engine.rule import Rule


class AparelhoCompartilhado(Rule):
    """Tres ou mais titulares pagando pelo mesmo aparelho em 30 dias.

    Familia divide celular, entao e sinal (+25), nao bloqueio. Quando o
    aparelho opera varios titulares para o mesmo destino novo, quem pontua
    e a COORDENACAO_ENTRE_CONTAS, e esta regra fica com 0.
    """

    code = "APARELHO_COMPARTILHADO"
    axis = ACESSO
    family = "infraestrutura_compartilhada"

    def evaluate(self, ctx, params):
        p = params[self.code]
        titulares = ctx.history.documents_on_device(ctx.device_id, ctx.moment, p["days"]) | {ctx.source_document}
        if len(titulares) < p["min_documents"]:
            return self.not_triggered()
        return self.triggered(p["points"], f"{len(titulares)} titulares no aparelho {ctx.device_id} em {p['days']} dias.",
                              data_origin="history")
