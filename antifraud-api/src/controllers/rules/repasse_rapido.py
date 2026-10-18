from datetime import timedelta
from fractions import Fraction

from controllers.engine.context import DESTINO
from controllers.engine.flow import project
from controllers.engine.profile import profile_for
from controllers.engine.rule import Rule
from utils.money import brl


class RepasseRapido(Rule):
    """A conta recebeu de varios titulares e esta escoando esse dinheiro, na ultima hora ou no ultimo dia.

    E o lado de saida da conta laranja. So e visivel quando o dinheiro
    passou pelo motor: a conta foi destino de outros Pix e agora e a origem.

    O que se compara e o acumulado da janela, nao o Pix sozinho
    (controllers/engine/flow.py): tres saidas de R$ 1.000 depois de tres
    entradas de R$ 1.000 sao o mesmo repasse que uma saida de R$ 3.000. E a
    devolucao vale so ate o credito que quem pagou ainda tem na conta, entao
    o centavo que o destino mandou antes nao vira um salvo-conduto.

    Em cada janela da politica (`windows`), o repasse aparece quando:
    - ha `min_payers` titulares ainda expostos (pagaram mais do que
      receberam de volta);
    - o escoamento acumulado E chega a `share` da base liquida B (o que
      entrou de terceiros menos o que voltou para eles), com o Pix atual;
    - e o Pix atual escoa alguma parte do pool. Uma devolucao integral nao
      herda o alerta das saidas anteriores.

    Depois disso, o destino decide quanto pesa: repassar para o fornecedor
    de sempre, com o perfil e o ritmo normais, nao e o mesmo que repassar
    para alguem novo. As duas janelas sao avaliadas, e vale a de mais
    pontos; no empate, a mais curta. Os pontos nao somam entre janelas.
    """

    code = "REPASSE_RAPIDO"
    axis = DESTINO
    family = "fluxo_e_rede"

    def evaluate(self, ctx, params):
        p = params[self.code]
        corte = Fraction(str(p["share"]))
        maior = max(janela["minutes"] for janela in p["windows"])
        eventos = ctx.history.flow_events(ctx.source_account.id, ctx.moment, maior)
        atual = (ctx.amount, ctx.destination_document, ctx.destination_account.id)

        avaliacoes = []
        for janela in sorted(p["windows"], key=lambda item: item["minutes"]):
            inicio = ctx.moment - timedelta(minutes=janela["minutes"])
            fluxo = project([evento for evento in eventos if evento[0] > inicio], ctx.source_account.id,
                            ctx.source_document, atual)
            if fluxo.identifies(janela["min_payers"], corte):
                avaliacoes.append(self._avalia(ctx, params, p, janela["minutes"], fluxo))
        if not avaliacoes:
            return self.not_triggered()
        return max(avaliacoes, key=lambda resultado: resultado.raw_points)

    def _avalia(self, ctx, params, p, minutos, fluxo):
        quando = "na ultima hora" if minutos <= 60 else f"nas ultimas {minutos // 60} h"
        detalhe = (f"Recebeu {brl(fluxo.incoming)} de terceiros {quando}; {brl(fluxo.refunded)} voltaram a quem "
                   f"pagou e {brl(fluxo.outflow)} escoaram, {fluxo.outflow / fluxo.base:.0%} da base de "
                   f"{brl(fluxo.base)} ({fluxo.qualified_payers} titulares). Este Pix escoa "
                   f"{brl(fluxo.current_outflow)}.")
        extra = {"window_minutes": minutos, "attribution": "fifo_heuristic", **fluxo.describe()}
        familiar = self._familiar(ctx, params)
        perfil = profile_for(ctx, params)
        velocity = ctx.result("VELOCITY")
        desvio = ctx.triggered("PERFIL") or (velocity is not None and velocity.is_triggered
                                             and velocity.extra.get("reference") == "adaptive")
        if not familiar or desvio:
            return self.triggered(p["points"], detalhe, data_origin="history", **extra)
        velocity_normal = velocity is not None and velocity.extra.get("reference") == "adaptive"
        if perfil.evaluable and velocity_normal:
            return self.not_triggered(detalhe + " Destino familiar, perfil e ritmo normais.", **extra)
        return self.triggered(p["inconclusive_points"], detalhe + " Destino familiar, sem referencia para conferir.",
                              data_origin="history", **extra)

    def _familiar(self, ctx, params) -> bool:
        regra = params["DESTINO_CONFIAVEL"]
        linhas = ctx.history.approved_to_document(ctx.source_document, ctx.destination_document, ctx.moment)
        if len(linhas) < regra["min_payments"]:
            return False
        fuso = ctx.local_moment.tzinfo
        datas = [linha[1].astimezone(fuso) for linha in linhas]
        return (len({d.date() for d in datas}) >= regra["min_days"]
                and ctx.moment - min(datas) >= timedelta(days=regra["min_span_days"]))
