from controllers.engine.context import MOVIMENTACAO
from controllers.engine.rule import Rule
from utils.document_number import is_legal_person
from utils.money import brl


class Noturno(Rule):
    """Pix noturno entre pessoas fisicas, acima de R$ 1.000.

    A hora e a de Sao Paulo, convertida do instante: o mesmo instante escrito
    com outro fuso da o mesmo resultado. O Banco Central limita a R$ 1.000 o
    Pix noturno entre pessoas fisicas; aqui isso e uma heuristica de risco,
    nao a reproducao da regra regulatoria.
    """

    code = "NOTURNO"
    axis = MOVIMENTACAO
    family = "horario"

    def evaluate(self, ctx, params):
        p = params[self.code]
        hora = ctx.local_moment.hour
        noite = hora >= p["start_hour"] or hora < p["end_hour"]
        entre_pessoas = not is_legal_person(ctx.source_document) and not is_legal_person(ctx.destination_document)
        outro_titular = ctx.source_document != ctx.destination_document
        if noite and entre_pessoas and outro_titular and ctx.amount > p["min_amount"]:
            return self.triggered(
                p["points"],
                f"{brl(ctx.amount)} as {ctx.local_moment:%H:%M} (Sao Paulo), de pessoa fisica para outra pessoa fisica.",
            )
        return self.not_triggered()
