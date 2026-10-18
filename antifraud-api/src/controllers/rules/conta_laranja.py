from datetime import timedelta

from controllers.engine.context import DESTINO
from controllers.engine.reference import adaptive_level
from controllers.engine.rule import Rule


def _texto(minutos: int) -> str:
    return f"{minutos // 60} h" if minutos >= 120 else f"{minutos} min"


class ContaLaranja(Rule):
    """Muitos titulares diferentes pagando a mesma conta (concentracao), na ultima hora ou no ultimo dia.

    Loja e vaquinha recebem de muita gente, entao nao ha bloqueio. Com
    referencia de entradas do recebedor, o corte e o dele: a loja que sempre
    recebe de 30 clientes por hora nao e laranja. Sem referencia, a idade do
    destino decide o peso, porque a conta laranja tipica e nova.

    Duas janelas, cada uma com os seus cortes (`windows` na politica): a de 1 h
    pega a rajada, e a de 24 h, com corte maior, pega a laranja que espalha as
    vitimas ao longo do dia para nao juntar muitas na mesma hora. Vale a que
    pontuar mais.
    """

    code = "CONTA_LARANJA"
    axis = DESTINO
    family = "fluxo_e_rede"

    def evaluate(self, ctx, params):
        p = params[self.code]
        nova = ctx.moment - ctx.destination_account.opening_date < timedelta(days=p["new_destination_days"])
        achados = [achado for janela in p["windows"] if (achado := self._na_janela(ctx, params, janela, nova))]
        if not achados:
            return self.not_triggered()
        pontos, detalhe, extra = max(achados, key=lambda achado: achado[0])
        return self.triggered(pontos, detalhe, data_origin="history", **extra)

    def _na_janela(self, ctx, params, janela, nova):
        """(pontos, detalhe, extra) da janela, ou None se ela nao pontua."""
        minutos = janela["minutes"]
        pagadores = ctx.history.payers_to_account(ctx.destination_account.id, ctx.moment, minutos) | {ctx.source_document}
        contagem = len(pagadores)

        nivel = adaptive_level(ctx, params, "payers", minutos, contagem, janela)
        if nivel is not None:
            if not nivel.points:
                return None
            return (nivel.points, f"{contagem} pagadores distintos em {_texto(minutos)}, acima do padrao do recebedor "
                    f"(limiares {nivel.moderate}/{nivel.high}).",
                    {"reference": "adaptive", "window_minutes": minutos, **nivel.describe()})

        faixas = janela["fallback_new"] if nova else janela["fallback_old"]
        for faixa in faixas:
            if contagem >= faixa["count"]:
                idade = "nova" if nova else "antiga"
                return (faixa["points"], f"{contagem} pagadores distintos em {_texto(minutos)} para uma conta {idade}, "
                        "sem referencia do recebedor.",
                        {"reference": "fallback", "window_minutes": minutos, "payers": contagem})
        return None
