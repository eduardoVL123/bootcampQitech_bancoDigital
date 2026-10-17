from statistics import median

from controllers.engine.context import MOVIMENTACAO
from controllers.engine.profile import day_start
from controllers.engine.rule import Rule
from utils.money import brl


class MontanteDiarioAtipico(Rule):
    """O acumulado de hoje, com este Pix, acima de 3 vezes a mediana dos dias do cliente.

    Compara o acumulado parcial de hoje com dias completos: e conservador de
    proposito. Dias sem movimento ficam de fora da mediana. Mede ACUMULO:
    exige pelo menos um Pix aprovado antes, hoje. Um Pix sozinho fora do
    padrao e assunto do PERFIL, e contar de novo aqui puniria duas vezes o
    mesmo valor (a massa de cenarios pegou isso no primeiro aluguel).
    """

    code = "MONTANTE_DIARIO_ATIPICO"
    axis = MOVIMENTACAO
    family = "ritmo_e_acumulado"

    def evaluate(self, ctx, params):
        p = params[self.code]
        inicio = day_start(ctx)
        totais = [int(t) for t in ctx.history.daily_approved_totals(ctx.source_account.id, inicio, p["days"],
                                                                     params["timezone"])]
        if len(totais) < p["min_days"]:
            return self.not_evaluable(f"So {len(totais)} dias com movimento; a regra pede {p['min_days']}.")
        minutos_de_hoje = int((ctx.moment - inicio).total_seconds() // 60) + 1
        aprovado_hoje, quantos_hoje = ctx.history.approved_sum_and_count(ctx.source_account.id, ctx.moment,
                                                                         minutos_de_hoje)
        if quantos_hoje == 0:
            return self.not_triggered("Primeiro Pix aprovado do dia: nao ha acumulo.")
        hoje = aprovado_hoje + ctx.amount
        m = median(totais)
        if hoje > p["multiple"] * m and hoje - m >= p["min_excess"]:
            return self.triggered(p["points"], f"{brl(hoje)} hoje contra mediana diaria de {brl(round(m))} "
                                  f"({len(totais)} dias).", data_origin="history", days=len(totais))
        return self.not_triggered()
