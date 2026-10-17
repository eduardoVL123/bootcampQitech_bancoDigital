from datetime import timedelta

from controllers.engine.context import DESTINO
from controllers.engine.reference import adaptive_level
from controllers.engine.rule import Rule


class ContaLaranja(Rule):
    """Muitos titulares diferentes pagando a mesma conta na ultima hora (concentracao).

    Loja e vaquinha recebem de muita gente, entao nao ha bloqueio. Com
    referencia de entradas do recebedor, o corte e o dele: a loja que sempre
    recebe de 30 clientes por hora nao e laranja. Sem referencia, a idade do
    destino decide o peso, porque a conta laranja tipica e nova.
    """

    code = "CONTA_LARANJA"
    axis = DESTINO
    family = "fluxo_e_rede"

    def evaluate(self, ctx, params):
        p = params[self.code]
        janela = p["window_minutes"]
        pagadores = ctx.history.payers_to_account(ctx.destination_account.id, ctx.moment, janela) | {ctx.source_document}
        contagem = len(pagadores)

        nivel = adaptive_level(ctx, params, "payers", janela, contagem, p)
        if nivel is not None:
            if not nivel.points:
                return self.not_triggered(reference="adaptive", **nivel.describe())
            return self.triggered(nivel.points, f"{contagem} pagadores distintos em {janela} min, acima do padrao do "
                                  f"recebedor (limiares {nivel.moderate}/{nivel.high}).", data_origin="history",
                                  reference="adaptive", **nivel.describe())

        nova = ctx.moment - ctx.destination_account.opening_date < timedelta(days=p["new_destination_days"])
        faixas = p["fallback_new"] if nova else p["fallback_old"]
        for faixa in faixas:
            if contagem >= faixa["count"]:
                idade = "nova" if nova else "antiga"
                return self.triggered(faixa["points"], f"{contagem} pagadores distintos em {janela} min para uma conta "
                                      f"{idade}, sem referencia do recebedor.", data_origin="history",
                                      reference="fallback", payers=contagem)
        return self.not_triggered(reference="fallback")
