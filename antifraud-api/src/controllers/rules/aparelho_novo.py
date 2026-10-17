from controllers.engine.context import ACESSO
from controllers.engine.rule import Rule


class AparelhoNovo(Rule):
    """O aparelho nunca apareceu para este titular, que ja tem historico.

    Troca de aparelho e o momento da conta tomada: o golpista entra pelo
    celular dele. Exige 3 tentativas anteriores, senao todo primeiro Pix da
    vida levaria pontos. Historico identifica novidade; nao certifica que o
    aparelho antigo era confiavel.
    """

    code = "APARELHO_NOVO"
    axis = ACESSO
    family = "mudanca_de_acesso"

    def evaluate(self, ctx, params):
        p = params[self.code]
        anteriores = ctx.history.prior_attempts_of_document(ctx.source_document, ctx.moment)
        if anteriores < p["min_prior_attempts"]:
            return self.not_triggered()
        if ctx.history.device_seen(ctx.source_document, ctx.device_id, ctx.moment):
            return self.not_triggered()
        return self.triggered(p["points"], f"Aparelho {ctx.device_id} nunca usado por este titular "
                              f"({anteriores} tentativas anteriores).", data_origin="history")
