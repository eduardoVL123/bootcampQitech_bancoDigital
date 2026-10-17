from controllers.engine.context import DESTINO
from controllers.engine.rule import Rule


class DestinoNovo(Rule):
    """Conta destino aberta ha pouco tempo: menos de 30 dias, ou menos de 1 dia.

    Golpe usa conta de passagem nova, porque a antiga ja foi denunciada. A
    conta do exemplo do documento tem 7 dias e 13 horas: com corte em 7 dias
    a regra nao a pegaria.
    """

    code = "DESTINO_NOVO"
    axis = DESTINO
    family = "novidade_do_destino"

    def evaluate(self, ctx, params):
        p = params[self.code]
        idade = ctx.moment - ctx.destination_account.opening_date
        horas = idade.total_seconds() / 3600
        if horas < p["very_new_hours"]:
            return self.triggered(p["very_new_points"], f"Conta destino aberta ha {horas:.0f} h.")
        if idade.days < p["days"]:
            return self.triggered(p["points"], f"Conta destino aberta ha {idade.days} dias e {int(horas % 24)} h.")
        return self.not_triggered()
