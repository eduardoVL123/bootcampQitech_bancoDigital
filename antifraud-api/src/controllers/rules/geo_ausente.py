from controllers.engine.context import ACESSO
from controllers.engine.rule import Rule


class GeoAusente(Rule):
    """O Pix chegou sem geolocalizacao, e isso e uma mudanca para este titular.

    O campo e opcional no contrato, entao a ausencia nunca e erro. Pelo app e
    pela web, +20 (decisao do time com o tech lead: pesa sem obrigar
    verificacao sozinha). Pela api, uma empresa pagando pelo proprio sistema
    nao tem GPS, e a ausencia nao diz nada.

    Muita gente nega a permissao de localizacao para sempre. Para quem tem
    historico e NUNCA mandou GPS, a ausencia e o normal dele: somar +20
    baixava o corte de 2FA dessa pessoa em todo Pix (um destino novo de +20
    ja dava 40). Ausencia que pesa e a de quem costuma mandar, ou de quem
    ainda nao tem historico.
    """

    code = "GEO_AUSENTE"
    axis = ACESSO
    family = "disponibilidade_de_localizacao"

    def evaluate(self, ctx, params):
        p = params[self.code]
        if ctx.gps is not None:
            return self.not_triggered()
        pontos = p["points"].get(ctx.channel, 0)
        if pontos == 0:
            return self.not_triggered(f"Sem geolocalizacao pelo canal {ctx.channel}, onde ela nao e esperada.")
        com_gps, total = ctx.history.gps_habit(ctx.source_document, ctx.moment, p["habit_days"])
        if total >= p["habit_min_attempts"] and com_gps == 0:
            return self.not_triggered(f"Sem geolocalizacao, como nos {total} Pix anteriores deste titular.")
        return self.triggered(pontos, f"Sem geolocalizacao pelo canal {ctx.channel}.")
