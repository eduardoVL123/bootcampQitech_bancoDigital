from controllers.engine.context import ACESSO, FACIAL_DOCUMENT, NONE
from controllers.engine.rule import Rule
from utils.geo import haversine_km


class ViagemImpossivel(Rule):
    """Do ultimo ponto conhecido do titular ate aqui, mais rapido que um aviao.

    O ponto e o GPS; sem GPS, o lugar do IP. 900 km/h e a velocidade de
    cruzeiro de um aviao comercial. Com GPS dos dois lados, ignora menos de
    100 km (imprecisao em cidade grande); com IP de algum lado, ignora menos
    de 500 km, porque IP e impreciso. Vale +40 e nao rejeita sozinha. Com
    aparelho novo junto, pede a verificacao reforcada.
    """

    code = "VIAGEM_IMPOSSIVEL"
    axis = ACESSO
    family = "mudanca_de_acesso"

    def evaluate(self, ctx, params):
        p = params[self.code]
        atual = ctx.gps or ctx.ip_location
        if atual is None:
            return self.not_evaluable("Sem GPS e sem localizacao do IP neste Pix.")
        anterior = ctx.history.last_located(ctx.source_document, ctx.moment)
        if anterior is None:
            return self.not_evaluable("Sem ponto anterior conhecido do titular.")
        data, lat, lon, ip_lat, ip_lon = anterior
        pelo_ip = ctx.gps is None or lat is None
        lat_anterior, lon_anterior = (float(lat), float(lon)) if lat is not None else (float(ip_lat), float(ip_lon))
        horas = (ctx.moment - data).total_seconds() / 3600
        if horas <= 0:
            return self.not_evaluable("O ponto anterior e do mesmo instante; nao ha intervalo para medir.")
        km = haversine_km(lat_anterior, lon_anterior, atual.latitude, atual.longitude)
        velocidade = km / horas
        minimo = p["min_km_ip"] if pelo_ip else p["min_km_gps"]
        if km <= minimo or velocidade <= p["max_kmh"]:
            return self.not_triggered()
        piso = FACIAL_DOCUMENT if ctx.triggered("APARELHO_NOVO") else NONE
        return self.triggered(
            p["points"], f"{km:.0f} km em {horas * 60:.0f} min ({velocidade:.0f} km/h) desde o ultimo Pix.",
            floor=piso, data_origin="ip_location" if pelo_ip else "gps", km=round(km), kmh=round(velocidade),
        )
