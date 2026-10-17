from controllers.engine.context import ACESSO
from controllers.engine.rule import Rule
from utils.geo import haversine_km


class GeoIpDivergente(Rule):
    """O GPS e o lugar do IP a mais de 500 km um do outro.

    GPS forjado, ou aparelho operado de longe. Os 500 km cobrem a operadora
    que sai para a internet por outro estado.
    """

    code = "GEO_IP_DIVERGENTE"
    axis = ACESSO
    family = "mudanca_de_acesso"

    def evaluate(self, ctx, params):
        p = params[self.code]
        if ctx.gps is None or ctx.ip_location is None:
            return self.not_evaluable("Falta o GPS ou a localizacao do IP para comparar.")
        km = haversine_km(ctx.gps.latitude, ctx.gps.longitude, ctx.ip_location.latitude, ctx.ip_location.longitude)
        if km <= p["km"]:
            return self.not_triggered()
        return self.triggered(p["points"], f"GPS a {km:.0f} km do lugar do IP ({ctx.ip_location.source}).",
                              data_origin="ip_location", km=round(km))
