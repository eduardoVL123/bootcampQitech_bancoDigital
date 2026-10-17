from datetime import timedelta

from controllers.engine.context import MOVIMENTACAO
from controllers.engine.rule import Rule
from utils.money import brl


class DestinoConfiavel(Rule):
    """Redutor: o destino ja e familiar.

    Familiar e 3 pagamentos aprovados a este titular, em 3 dias diferentes,
    o primeiro ha 7 dias ou mais, e o valor de agora nao passa do maior ja
    pago a ele. Um Pix de R$ 10 nao "aquece" o destino para um de R$ 2.500.
    Desconta ate 10 pontos so da familia de valor individual.
    """

    code = "DESTINO_CONFIAVEL"
    axis = MOVIMENTACAO
    family = "confianca"

    def evaluate(self, ctx, params):
        p = params[self.code]
        if ctx.source_document == ctx.destination_document:
            return self.not_triggered()
        linhas = ctx.history.approved_to_document(ctx.source_document, ctx.destination_document, ctx.moment)
        if len(linhas) < p["min_payments"]:
            return self.not_triggered()
        fuso = ctx.local_moment.tzinfo
        datas = [linha[1].astimezone(fuso) for linha in linhas]
        maior = max(int(linha[0]) for linha in linhas)
        familiar = (
            len({d.date() for d in datas}) >= p["min_days"]
            and ctx.moment - min(datas) >= timedelta(days=p["min_span_days"])
            and ctx.amount <= maior
        )
        if not familiar:
            return self.not_triggered()
        return self.triggered(-p["discount"], f"{len(linhas)} pagamentos anteriores a este titular, ate {brl(maior)}.",
                              data_origin="history")
