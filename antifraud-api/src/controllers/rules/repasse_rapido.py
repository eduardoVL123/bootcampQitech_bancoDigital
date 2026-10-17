from datetime import timedelta

from controllers.engine.context import DESTINO
from controllers.engine.profile import profile_for
from controllers.engine.rule import Rule
from utils.money import brl


class RepasseRapido(Rule):
    """A conta recebeu de varios titulares na ultima hora e repassa quase tudo (dispersao).

    E o lado de saida da conta laranja. Repassar para o fornecedor de
    sempre, com o perfil e o ritmo normais, nao e o mesmo que repassar para
    alguem novo: so pontua cheio com destino sem familiaridade ou desvio do
    padrao. So e visivel quando o dinheiro passou pelo motor: a conta foi
    destino de outros Pix e agora e a origem.
    """

    code = "REPASSE_RAPIDO"
    axis = DESTINO
    family = "fluxo_e_rede"

    def evaluate(self, ctx, params):
        p = params[self.code]
        recebido, pagadores = ctx.history.received_by_account(ctx.source_account.id, ctx.moment, p["window_minutes"])
        if len(pagadores) < p["min_payers"] or recebido == 0:
            return self.not_triggered()
        if ctx.destination_document in pagadores or ctx.destination_document == ctx.source_document:
            return self.not_triggered("O dinheiro volta para quem pagou.")
        fatia = ctx.amount / recebido
        if fatia < p["share"]:
            return self.not_triggered()

        detalhe = (f"Recebeu {brl(recebido)} de {len(pagadores)} titulares na ultima hora e repassa "
                   f"{brl(ctx.amount)} ({fatia:.0%}).")
        familiar = self._familiar(ctx, params)
        perfil = profile_for(ctx, params)
        velocity = ctx.result("VELOCITY")
        desvio = ctx.triggered("PERFIL") or (velocity is not None and velocity.is_triggered
                                             and velocity.extra.get("reference") == "adaptive")
        if not familiar or desvio:
            return self.triggered(p["points"], detalhe, data_origin="history")
        velocity_normal = velocity is not None and velocity.extra.get("reference") == "adaptive"
        if perfil.evaluable and velocity_normal:
            return self.not_triggered(detalhe + " Destino familiar, perfil e ritmo normais.")
        return self.triggered(p["inconclusive_points"], detalhe + " Destino familiar, sem referencia para conferir.",
                              data_origin="history")

    def _familiar(self, ctx, params) -> bool:
        regra = params["DESTINO_CONFIAVEL"]
        linhas = ctx.history.approved_to_document(ctx.source_document, ctx.destination_document, ctx.moment)
        if len(linhas) < regra["min_payments"]:
            return False
        fuso = ctx.local_moment.tzinfo
        datas = [linha[1].astimezone(fuso) for linha in linhas]
        return (len({d.date() for d in datas}) >= regra["min_days"]
                and ctx.moment - min(datas) >= timedelta(days=regra["min_span_days"]))
