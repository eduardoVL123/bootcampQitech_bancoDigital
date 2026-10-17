from controllers.engine.context import MOVIMENTACAO, NONE
from controllers.engine.reference import adaptive_level
from controllers.engine.rule import Rule


class Velocity(Rule):
    """Tentativas de saida da conta em 5 e 30 minutos, contando esta.

    Os tres status contam: quem leva 2FA ou recusa e insiste e exatamente o
    sinal. Replay nao conta (o mesmo id nem chega aqui).

    Com referencia (7 dias ativos e 20 tentativas nos 30 dias anteriores), o
    corte e o do proprio cliente: quem faz 40 Pix por hora no trabalho nao
    esta numa rajada. Sem referencia, a regua de reserva e firme, porque
    conta nova ou pouco usada e o perfil da conta laranja e da conta tomada.
    """

    code = "VELOCITY"
    axis = MOVIMENTACAO
    family = "ritmo_e_acumulado"

    def evaluate(self, ctx, params):
        p = params[self.code]
        contagens = {
            minutos: ctx.history.attempts(ctx.source_account.id, ctx.moment, minutos) + 1
            for minutos in p["windows_minutes"]
        }

        melhor = None
        referencias = {}
        for minutos, contagem in contagens.items():
            nivel = adaptive_level(ctx, params, "attempts", minutos, contagem, p)
            if nivel is None:
                continue
            referencias[minutos] = nivel.describe()
            if nivel.points and (melhor is None or nivel.points > melhor.points):
                melhor = nivel
        if referencias:
            if melhor is None:
                return self.not_triggered(reference="adaptive", windows=referencias)
            return self.triggered(
                melhor.points, f"{melhor.count} tentativas em {melhor.minutes} min, acima do padrao do cliente "
                f"(limiares {melhor.moderate}/{melhor.high}).", floor=melhor.floor, data_origin="history",
                reference="adaptive", windows=referencias,
            )

        janela = p["fallback_window_minutes"]
        contagem = contagens[janela]
        for faixa in p["fallback"]:
            if contagem >= faixa["count"]:
                return self.triggered(
                    faixa["points"], f"{contagem} tentativas de saida em {janela} min, sem referencia do cliente.",
                    floor=faixa["floor"] if faixa["floor"] != NONE else NONE, data_origin="history",
                    reference="fallback",
                )
        return self.not_triggered(reference="fallback")
