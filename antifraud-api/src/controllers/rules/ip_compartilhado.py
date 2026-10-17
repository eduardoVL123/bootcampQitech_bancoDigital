from controllers.engine.context import ACESSO
from controllers.engine.rule import Rule


class IpCompartilhado(Rule):
    """Cinco ou mais titulares pagando pelo mesmo IP na ultima hora, numa rede nova para quem paga.

    Peso baixo de proposito: operadora de celular poe milhares de clientes
    atras do mesmo IP (CGNAT). Contado so pelo IP, ele somava com o NOTURNO
    (25 + 15 = 40) e pedia a facial ao quinto cliente da operadora que
    pagasse um amigo de sempre a noite.

    Por isso so conta quando a rede (o /24) e nova para este titular: o
    cliente que sempre paga daquela operadora esta na rede de sempre, e a
    "fazenda" de contas operadas de um mesmo lugar aparece numa rede que
    nenhuma delas usava.
    """

    code = "IP_COMPARTILHADO"
    axis = ACESSO
    family = "infraestrutura_compartilhada"

    def evaluate(self, ctx, params):
        p = params[self.code]
        titulares = ctx.history.documents_on_ip(ctx.ip, ctx.moment, p["window_minutes"]) | {ctx.source_document}
        if len(titulares) < p["min_documents"]:
            return self.not_triggered()
        if ctx.history.network_seen(ctx.source_document, ctx.network, ctx.moment):
            return self.not_triggered(f"{len(titulares)} titulares no IP, mas e a rede de sempre deste titular.")
        return self.triggered(p["points"], f"{len(titulares)} titulares no IP {ctx.ip} na ultima hora, numa rede "
                              "nova para este titular.", data_origin="history")
