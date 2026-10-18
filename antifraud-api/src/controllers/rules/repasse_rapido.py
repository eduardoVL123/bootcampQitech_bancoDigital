from datetime import timedelta

from controllers.engine.context import DESTINO
from controllers.engine.profile import profile_for
from controllers.engine.rule import Rule
from utils.document_number import is_legal_person
from utils.money import brl


class RepasseRapido(Rule):
    """A conta recebeu de varios titulares e repassa quase tudo (dispersao), na ultima hora ou no ultimo dia.

    E o lado de saida da conta laranja. Repassar para o fornecedor de
    sempre, com o perfil e o ritmo normais, nao e o mesmo que repassar para
    alguem novo: so pontua cheio com destino sem familiaridade ou desvio do
    padrao. So e visivel quando o dinheiro passou pelo motor: a conta foi
    destino de outros Pix e agora e a origem.

    Duas janelas (`windows` na politica): a de 1 h, e a de 24 h, que pede
    mais pagadores e pega a laranja que espera horas antes de repassar.
    Vale a primeira em que o repasse aparece.
    """

    code = "REPASSE_RAPIDO"
    axis = DESTINO
    family = "fluxo_e_rede"

    def evaluate(self, ctx, params):
        p = params[self.code]
        # A laranja esperta divide a saida em varios Pix menores: com
        # `cumulative`, o que conta e o total que ja saiu na janela mais este.
        for janela in p["windows"]:
            recebido, pagadores = ctx.history.received_by_account(ctx.source_account.id, ctx.moment, janela["minutes"])
            if len(pagadores) < janela["min_payers"] or not recebido:
                continue
            ja_saiu = 0
            if p.get("cumulative"):
                ja_saiu = ctx.history.sent_by_account(ctx.source_account.id, ctx.moment, janela["minutes"], pagadores)
            if (ctx.amount + ja_saiu) / recebido >= p["share"]:
                break
        else:
            return self.not_triggered()
        if ctx.destination_document in pagadores or ctx.destination_document == ctx.source_document:
            return self.not_triggered("O dinheiro volta para quem pagou.")
        fatia = (ctx.amount + ja_saiu) / recebido
        quando = "na ultima hora" if janela["minutes"] <= 60 else f"nas ultimas {janela['minutes'] // 60} h"

        detalhe = (f"Recebeu {brl(recebido)} de {len(pagadores)} titulares {quando} e ja repassou "
                   f"{brl(ctx.amount + ja_saiu)} ({fatia:.0%}), contando este Pix.")
        familiar = self._familiar(ctx, params)
        perfil = profile_for(ctx, params)
        velocity = ctx.result("VELOCITY")
        desvio = ctx.triggered("PERFIL") or (velocity is not None and velocity.is_triggered
                                             and velocity.extra.get("reference") == "adaptive")
        if not familiar or desvio:
            # Quem repassa e o dono da laranja: ele passa na selfie, entao so
            # segurar a saida protege as vitimas (e deixa o dinheiro para o MED).
            # O bloqueio vale para onde a laranja manda: pessoa fisica ou conta
            # recente. Para empresa antiga (o organizador que paga a agencia), so pontua.
            idade = ctx.moment - ctx.destination_account.opening_date
            alvo_de_laranja = (not is_legal_person(ctx.destination_document)
                               or idade < timedelta(days=p.get("hard_block_max_destination_days", 0)))
            if p.get("hard_block") and not alvo_de_laranja:
                return self.not_triggered(detalhe + " Destino e empresa antiga: parece fornecedor, nao dispersao.")
            return self.triggered(p["points"], detalhe, data_origin="history",
                                  hard_block=p.get("hard_block", False) and alvo_de_laranja)
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
