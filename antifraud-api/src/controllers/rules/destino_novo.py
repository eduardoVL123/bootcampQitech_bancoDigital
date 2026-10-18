from controllers.engine.context import DESTINO
from controllers.engine.rule import Rule
from utils.money import brl


class DestinoNovo(Rule):
    """Conta destino aberta ha pouco tempo: menos de 30 dias, ou menos de 1 dia.

    Golpe usa conta de passagem nova, porque a antiga ja foi denunciada. A
    conta do exemplo do documento tem 7 dias e 13 horas: com corte em 7 dias
    a regra nao a pegaria.

    A conta de menos de 1 dia que o pagador nunca pagou, acima de
    `very_new_floor_min_amount`, pede a facial (`very_new_floor`): e o falso
    parente ("troquei de numero, me faz um Pix?"), com valor dentro do habito
    da vitima. A facial sozinha nao para o golpe (a vitima passa); ela e o
    momento em que o app mostra o aviso ao pagador (controllers/engine/warning.py).
    """

    code = "DESTINO_NOVO"
    axis = DESTINO
    family = "novidade_do_destino"

    def evaluate(self, ctx, params):
        p = params[self.code]
        idade = ctx.moment - ctx.destination_account.opening_date
        horas = idade.total_seconds() / 3600
        if horas < p["very_new_hours"]:
            detalhe = f"Conta destino aberta ha {horas:.0f} h."
            if (p.get("very_new_floor") and ctx.source_document != ctx.destination_document
                    and ctx.amount > p["very_new_floor_min_amount"]
                    and not ctx.history.approved_to_document(ctx.source_document, ctx.destination_document,
                                                             ctx.moment)):
                return self.triggered(p["very_new_points"], f"{detalhe} Primeiro pagamento a esse titular, acima "
                                      f"de {brl(p['very_new_floor_min_amount'])}.", floor=p["very_new_floor"])
            return self.triggered(p["very_new_points"], detalhe)
        if idade.days < p["days"]:
            return self.triggered(p["points"], f"Conta destino aberta ha {idade.days} dias e {int(horas % 24)} h.")
        return self.not_triggered()
