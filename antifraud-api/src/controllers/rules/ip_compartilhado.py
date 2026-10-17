from controllers.engine.context import ACESSO
from controllers.engine.rule import Rule


class IpCompartilhado(Rule):
    """Cinco ou mais titulares pagando pelo mesmo IP na ultima hora.

    Peso baixo de proposito: operadora de celular poe milhares de clientes
    atras do mesmo IP. Nunca decide sozinho; soma com aparelho novo ou
    conta laranja.
    """

    code = "IP_COMPARTILHADO"
    axis = ACESSO
    family = "infraestrutura_compartilhada"

    def evaluate(self, ctx, params):
        p = params[self.code]
        titulares = ctx.history.documents_on_ip(ctx.ip, ctx.moment, p["window_minutes"]) | {ctx.source_document}
        if len(titulares) < p["min_documents"]:
            return self.not_triggered()
        return self.triggered(p["points"], f"{len(titulares)} titulares no IP {ctx.ip} na ultima hora.",
                              data_origin="history")
