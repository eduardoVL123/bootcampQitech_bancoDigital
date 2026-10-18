from datetime import timedelta

from controllers.engine.context import DESTINO
from controllers.engine.reference import adaptive_level
from controllers.engine.rule import Rule
from utils.money import brl


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
    vitimas ao longo do dia para nao juntar muitas na mesma hora. E uma
    terceira leitura, a dos pagadores sem vinculo (`long`), para a laranja
    paciente que espalha as vitimas por dias. Vale a que pontuar mais.
    """

    code = "CONTA_LARANJA"
    axis = DESTINO
    family = "fluxo_e_rede"

    def evaluate(self, ctx, params):
        p = params[self.code]
        nova = ctx.moment - ctx.destination_account.opening_date < timedelta(days=p["new_destination_days"])
        achados = [achado for janela in p["windows"] if (achado := self._na_janela(ctx, params, janela, nova))]
        longa = self._pagadores_sem_vinculo(ctx, p, nova)
        if longa is not None:
            achados.append(longa)
        if not achados:
            return self.not_triggered()
        pontos, detalhe, extra = max(achados, key=lambda achado: achado[0])
        return self.triggered(pontos, detalhe, data_origin="history", **extra)

    def _pagadores_sem_vinculo(self, ctx, p, nova):
        """Muitos pagadores sem vinculo com a conta, num dia ou numa semana (`long` na politica).

        As janelas contam pagadores distintos. Esta leitura conta so os que
        nunca tinham pago a conta nem recebido do dono dela, e compara o que
        eles somam com o que a conta recebia antes: o corte e o proprio
        recebedor. Vaquinha e autonomo recebem de muitos tambem, mas valores
        pequenos: por isso o corte de valor medio por pagador.
        """
        longa = p.get("long")
        if not longa:
            return None
        conta = ctx.destination_account.id
        atual_novo = not ctx.history.approved_to_document(ctx.source_document, ctx.destination_document, ctx.moment)
        for horas in longa["windows_hours"]:
            novos, soma = ctx.history.new_payers_to_account(conta, ctx.destination_document, ctx.moment, horas)
            if atual_novo and ctx.source_document not in novos:
                novos, soma = novos | {ctx.source_document}, soma + ctx.amount
            if len(novos) < longa["min_new_payers"] or soma < longa["min_amount"]:
                continue
            if soma / len(novos) < longa["min_average"]:
                continue
            antes = ctx.history.received_before(conta, ctx.moment, horas, longa["history_days"])
            if soma < longa["multiple"] * antes:
                continue
            pontos = longa["points_new"] if nova else longa["points_old"]
            return (pontos, f"{len(novos)} pagadores que nunca tinham pago esta conta somam {brl(soma)} em {horas} h; "
                    f"nos {longa['history_days']} dias antes ela recebeu {brl(antes)}.",
                    {"reference": "long_window", "window_hours": horas, "new_payers": len(novos)})
        return None

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
