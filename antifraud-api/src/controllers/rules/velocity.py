from controllers.engine.context import MOVIMENTACAO, NONE
from controllers.engine.reference import adaptive_level
from controllers.engine.rule import Rule
from utils.document_number import is_legal_person


class Velocity(Rule):
    """Tentativas de saida da conta em 5 e 30 minutos, contando esta.

    Os tres status contam: quem leva 2FA ou recusa e insiste e exatamente o
    sinal. Replay nao conta (o mesmo id nem chega aqui).

    Com referencia (7 dias ativos e 20 tentativas nos 30 dias anteriores), o
    corte e o do proprio cliente: quem faz 40 Pix por hora no trabalho nao
    esta numa rajada. Sem referencia, a regua de reserva e firme, porque
    conta nova ou pouco usada e o perfil da conta laranja e da conta tomada.

    Os cortes sao um para CPF e outro para CNPJ (`pf` e `pj` na politica):
    empresa paga fornecedores e folha em lote, e dez Pix em cinco minutos e o
    dia normal dela. Para pessoa fisica, continua sendo a rajada.
    """

    code = "VELOCITY"
    axis = MOVIMENTACAO
    family = "ritmo_e_acumulado"

    def evaluate(self, ctx, params):
        p = params[self.code]
        tipo = "PJ" if is_legal_person(ctx.source_document) else "PF"
        cortes = p[tipo.lower()]
        contagens = {
            minutos: ctx.history.attempts(ctx.source_account.id, ctx.moment, minutos) + 1
            for minutos in p["windows_minutes"]
        }

        melhor = None
        referencias = {}
        for minutos, contagem in contagens.items():
            nivel = adaptive_level(ctx, params, "attempts", minutos, contagem, cortes)
            if nivel is None:
                continue
            referencias[minutos] = nivel.describe()
            if nivel.points and (melhor is None or nivel.points > melhor.points):
                melhor = nivel
        if referencias:
            if melhor is None:
                return self.not_triggered(reference="adaptive", windows=referencias, payer_type=tipo)
            return self.triggered(
                melhor.points, f"{melhor.count} tentativas em {melhor.minutes} min, acima do padrao do cliente "
                f"(limiares {melhor.moderate}/{melhor.high}).", floor=melhor.floor, data_origin="history",
                reference="adaptive", windows=referencias, payer_type=tipo,
            )

        janela = p["fallback_window_minutes"]
        contagem = contagens[janela]
        for faixa in cortes["fallback"]:
            if contagem >= faixa["count"]:
                return self.triggered(
                    faixa["points"], f"{contagem} tentativas de saida em {janela} min, sem referencia do cliente "
                    f"(corte de {tipo}).", floor=faixa["floor"] if faixa["floor"] != NONE else NONE,
                    data_origin="history", reference="fallback", payer_type=tipo,
                )
        return self.not_triggered(reference="fallback", payer_type=tipo)
