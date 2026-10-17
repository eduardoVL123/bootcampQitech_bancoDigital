from datetime import timedelta

from controllers.engine.context import DESTINO, FACIAL
from controllers.engine.rule import Rule


class CoordenacaoEntreContas(Rule):
    """Um aparelho operando tres ou mais titulares para o mesmo destino novo, em 10 minutos.

    Varias contas sendo usadas juntas para escoar para uma conta recem-aberta.
    Quando esta regra dispara, o APARELHO_COMPARTILHADO dos mesmos titulares
    fica com 0: e o mesmo fato, e nao pode contar duas vezes.
    """

    code = "COORDENACAO_ENTRE_CONTAS"
    axis = DESTINO
    family = "fluxo_e_rede"

    def evaluate(self, ctx, params):
        p = params[self.code]
        if ctx.moment - ctx.destination_account.opening_date >= timedelta(days=p["destination_max_days"]):
            return self.not_triggered()
        titulares = ctx.history.coordinated_payers(ctx.device_id, ctx.destination_account.id, ctx.moment,
                                                   p["window_minutes"]) | {ctx.source_document}
        if len(titulares) < p["min_documents"]:
            return self.not_triggered()
        return self.triggered(p["points"], f"{len(titulares)} titulares no mesmo aparelho para a mesma conta nova "
                              f"em {p['window_minutes']} min.", floor=FACIAL, data_origin="history")
