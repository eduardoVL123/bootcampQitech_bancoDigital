from datetime import timedelta

from controllers.engine.context import DESTINO
from controllers.engine.rule import Rule
from utils.money import brl


class TetoDestinoNovo(Rule):
    """Teto por Pix para conta destino na primeira semana.

    Concentracao em conta nova e ambigua: pode ser a loja lancando um produto
    ou a conta laranja recebendo das vitimas. Sem denuncia do recebedor, o
    eixo destino nao reprova sozinho (passo 5 de controllers/engine/decision.py),
    e nessa duvida e o teto que segura: antes de a conta ter a regua dela, o Pix
    acima do teto reprova. A loja vende o tiquete pequeno; a laranja nao recebe
    o valor alto.

    Nao soma pontos e nao decide sozinha: so pesa quando o eixo destino chega
    ao corte sem denuncia. Fora disso, o Pix para conta nova segue como antes.
    """

    code = "TETO_DESTINO_NOVO"
    axis = DESTINO
    family = "novidade_do_destino"

    def evaluate(self, ctx, params):
        p = params[self.code]
        if ctx.moment - ctx.destination_account.opening_date >= timedelta(days=p["days"]):
            return self.not_triggered()
        if ctx.amount <= p["per_pix"]:
            return self.not_triggered(f"Conta destino da primeira semana, dentro do teto de {brl(p['per_pix'])}.")
        return self.triggered(0, f"{brl(ctx.amount)} para conta aberta ha menos de {p['days']} dias: acima do teto de "
                              f"{brl(p['per_pix'])}, que reprova quando o eixo destino chega ao corte sem denuncia "
                              "do recebedor.")
