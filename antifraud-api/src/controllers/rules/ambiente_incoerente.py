from controllers.engine.context import ACESSO
from controllers.engine.rule import Rule
from utils.geo import in_brazil


class AmbienteIncoerente(Rule):
    """O GPS ou o IP fora do Brasil.

    O retangulo nao e a fronteira, e e um corte barato para "claramente
    fora". So +20: brasileiro viaja. O fuso do horario e so representacao do
    instante e nao entra aqui; ele vai como sinal em `signals`.
    """

    code = "AMBIENTE_INCOERENTE"
    axis = ACESSO
    family = "mudanca_de_acesso"

    def evaluate(self, ctx, params):
        p = params[self.code]
        if ctx.gps is not None and not in_brazil(ctx.gps.latitude, ctx.gps.longitude):
            return self.triggered(p["points"], "GPS fora do Brasil.", data_origin="gps")
        if ctx.ip_location is not None and ctx.ip_location.country != "BR":
            return self.triggered(p["points"], f"IP localizado fora do Brasil ({ctx.ip_location.source}).",
                                  data_origin="ip_location")
        return self.not_triggered()
