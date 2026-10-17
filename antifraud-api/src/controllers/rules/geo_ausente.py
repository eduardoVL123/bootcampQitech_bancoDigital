from controllers.engine.context import ACESSO
from controllers.engine.rule import Rule


class GeoAusente(Rule):
    """O Pix chegou sem geolocalizacao.

    O campo e opcional no contrato, entao a ausencia nunca e erro. Mas pesa:
    pelo app e pela web, +20 (decisao do time com o tech lead: pesa sem
    obrigar verificacao sozinha). Pela api, uma empresa pagando pelo proprio
    sistema nao tem GPS, e a ausencia nao diz nada.
    """

    code = "GEO_AUSENTE"
    axis = ACESSO
    family = "disponibilidade_de_localizacao"

    def evaluate(self, ctx, params):
        if ctx.gps is not None:
            return self.not_triggered()
        pontos = params[self.code]["points"].get(ctx.channel, 0)
        if pontos == 0:
            return self.not_triggered(f"Sem geolocalizacao pelo canal {ctx.channel}, onde ela nao e esperada.")
        return self.triggered(pontos, f"Sem geolocalizacao pelo canal {ctx.channel}.")
