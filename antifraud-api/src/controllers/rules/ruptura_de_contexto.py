from datetime import timedelta

from controllers.engine.context import FACIAL_DOCUMENT
from controllers.engine.rule import Rule
from utils.geo import haversine_km


class RupturaDeContexto(Rule):
    """O retrato da conta tomada: o acesso, o dinheiro e o relacionamento mudam juntos.

    - Acesso: aparelho novo, ou GPS a mais de 50 km de todos os pontos
      aprovados dos ultimos 90 dias (com 5 pontos em 3 dias). IP diferente
      ou GPS ausente NAO contam: nao provam que o lugar mudou.
    - Dinheiro: o PERFIL ou a VELOCITY disparados contra a regua do proprio
      cliente. A regua de reserva da velocity nao basta.
    - Relacionamento: destinatario sem familiaridade, num cliente com
      historico suficiente (10 aprovados em 3 dias) para a ausencia dizer
      alguma coisa.

    Zero pontos: cada componente ja pontuou na sua regra. Muda so o nivel de
    verificacao, para facial e documento.
    """

    code = "RUPTURA_DE_CONTEXTO"
    axis = None
    family = "composta"

    def evaluate(self, ctx, params):
        p = params[self.code]
        acesso = self._acesso(ctx, p)
        financeiro = self._financeiro(ctx)
        relacionamento = self._relacionamento(ctx, params, p)
        componentes = {"access": acesso, "financial": financeiro, "relationship": relacionamento}
        if acesso and financeiro and relacionamento:
            return self.triggered(0, f"Mudaram juntos: {acesso}; {financeiro}; {relacionamento}.",
                                  floor=FACIAL_DOCUMENT, data_origin="history", components=componentes)
        return self.not_triggered(components=componentes)

    def _acesso(self, ctx, p):
        if ctx.triggered("APARELHO_NOVO"):
            return "aparelho novo"
        if ctx.gps is None:
            return None
        pontos = ctx.history.approved_gps_points(ctx.source_document, ctx.moment, p["geo_window_days"])
        fuso = ctx.local_moment.tzinfo
        if len(pontos) < p["geo_min_points"] or len({item[2].astimezone(fuso).date() for item in pontos}) < p["geo_min_days"]:
            return None
        mais_perto = min(haversine_km(float(item[0]), float(item[1]), ctx.gps.latitude, ctx.gps.longitude) for item in pontos)
        if mais_perto > p["far_km"]:
            return f"GPS a {mais_perto:.0f} km do ponto habitual mais proximo"
        return None

    def _financeiro(self, ctx):
        if ctx.triggered("PERFIL"):
            return "valor fora do perfil"
        velocity = ctx.result("VELOCITY")
        if velocity is not None and velocity.is_triggered and velocity.extra.get("reference") == "adaptive":
            return "ritmo acima do padrao do cliente"
        return None

    def _relacionamento(self, ctx, params, p):
        inicio = ctx.local_moment.replace(hour=0, minute=0, second=0, microsecond=0)
        historico = ctx.history.approved_amounts_of_payer(ctx.source_account.id, inicio, params["PERFIL"]["window_days"])
        fuso = ctx.local_moment.tzinfo
        dias = {item[1].astimezone(fuso).date() for item in historico}
        if len(historico) < p["history_min_payments"] or len(dias) < p["history_min_days"]:
            return None
        familiar = params["DESTINO_CONFIAVEL"]
        linhas = ctx.history.approved_to_document(ctx.source_document, ctx.destination_document, ctx.moment)
        datas = [item[1].astimezone(fuso) for item in linhas]
        e_familiar = (
            len(linhas) >= familiar["min_payments"]
            and len({d.date() for d in datas}) >= familiar["min_days"]
            and ctx.moment - min(datas) >= timedelta(days=familiar["min_span_days"])
        )
        return None if e_familiar else "destinatario sem familiaridade"
