from statistics import median

from controllers.engine.calendar import calendar_for
from controllers.engine.context import FACIAL, MOVIMENTACAO
from controllers.engine.rule import Rule
from utils.money import brl

MIN_PHASE_SAMPLE = 10


class PadraoMensal(Rule):
    """Pagamento grande fora da janela do mes em que o cliente costuma pagar, para alguem novo.

    Dispara so com a combinacao completa: ha um padrao (3 meses), o Pix esta
    fora da janela, o valor e 3 vezes a mediana dessa fase do mes, e o
    destino ou o aparelho sao novos. Data sozinha nao basta. Quando o PERFIL
    ja pontuou o mesmo desvio de valor, esta regra nao soma de novo: fica so
    o piso de verificacao facial.
    """

    code = "PADRAO_MENSAL"
    axis = MOVIMENTACAO
    family = "horario"

    def evaluate(self, ctx, params):
        p = params[self.code]
        calendario = calendar_for(ctx, params)
        if not calendario.evaluable:
            return self.not_evaluable(calendario.reason)
        if calendario.inside or ctx.amount < p["min_amount"]:
            return self.not_triggered(center_day=calendario.center)
        if len(calendario.phase) < MIN_PHASE_SAMPLE:
            return self.not_evaluable("Poucos pagamentos nesta fase do mes para comparar o valor.")
        m = median(int(linha[0]) for linha in calendario.phase)
        if ctx.amount < p["multiple"] * m:
            return self.not_triggered(center_day=calendario.center)
        destino_novo = not ctx.history.approved_to_document(ctx.source_document, ctx.destination_document, ctx.moment)
        if not (destino_novo or ctx.triggered("APARELHO_NOVO")):
            return self.not_triggered(center_day=calendario.center)
        pontos = 0 if ctx.triggered("PERFIL") else p["points"]
        return self.triggered(
            pontos, f"{brl(ctx.amount)} no dia {ctx.local_moment.day}, fora da janela habitual (dia "
            f"{calendario.center} +/- {p['tolerance_days']}), contra mediana de {brl(round(m))} nesta fase, "
            "para destino ou aparelho novo.", floor=FACIAL, data_origin="history", center_day=calendario.center,
        )
