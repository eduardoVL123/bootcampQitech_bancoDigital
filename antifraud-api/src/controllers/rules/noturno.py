from datetime import timedelta

from controllers.engine.context import MOVIMENTACAO
from controllers.engine.rule import Rule
from utils.document_number import is_legal_person
from utils.money import brl


class Noturno(Rule):
    """Pix noturno de pessoa fisica para outra pessoa, acima de R$ 1.000.

    A hora e a de Sao Paulo, convertida do instante: o mesmo instante escrito
    com outro fuso da o mesmo resultado. O Banco Central limita a R$ 1.000 o
    Pix noturno para pessoa fisica (IN BCB 512/2024, na redacao da IN BCB 669/2025);
    aqui isso e uma heuristica de risco,
    nao a reproducao da regra regulatoria.

    Recebedor PJ fica de fora, porque loja, delivery e aplicativo recebem de
    madrugada. A excecao e a PJ com conta nova (`new_legal_person_days`): e o
    MEI aberto ha poucos dias que a conta laranja usa para escapar desta regra.
    """

    code = "NOTURNO"
    axis = MOVIMENTACAO
    family = "horario"

    def evaluate(self, ctx, params):
        p = params[self.code]
        hora = ctx.local_moment.hour
        noite = hora >= p["start_hour"] or hora < p["end_hour"]
        outro_titular = ctx.source_document != ctx.destination_document
        if not (noite and outro_titular and ctx.amount > p["min_amount"]) or is_legal_person(ctx.source_document):
            return self.not_triggered()
        quando = f"{brl(ctx.amount)} as {ctx.local_moment:%H:%M} (Sao Paulo), de pessoa fisica"
        if not is_legal_person(ctx.destination_document):
            return self.triggered(p["points"], f"{quando} para outra pessoa fisica.")
        idade = ctx.moment - ctx.destination_account.opening_date
        if idade < timedelta(days=p["new_legal_person_days"]):
            return self.triggered(p["points"], f"{quando} para uma PJ com conta aberta ha {idade.days} dias.")
        return self.not_triggered()
