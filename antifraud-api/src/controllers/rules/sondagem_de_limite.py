from controllers.engine.context import FACIAL_DOCUMENT, MOVIMENTACAO
from controllers.engine.rule import Rule
from utils.money import brl


class SondagemDeLimite(Rule):
    """Depois de um 2FA ou de uma recusa, tentar de novo com valor menor.

    Uma reducao pode ser ajuste legitimo (+30). Duas reducoes seguidas,
    cada uma depois de uma decisao restritiva, e ir baixando ate passar
    (+50 e verificacao reforcada).

    Sondar e tentar de novo O MESMO pagamento com um valor um pouco menor.
    Um Pix bem menor para outro destino e outro pagamento: o carro pediu 2FA
    e, 10 minutos depois, o almoco de R$ 30 levava +30. Para outro destino,
    so conta se o valor ainda for uma fracao relevante do anterior
    (`other_destination_min_ratio`), que e o caso de quem troca de conta
    laranja e continua baixando.

    Duas janelas: a de 15 min vale para as duas faixas, e a longa
    (`long_window_minutes`) so para a de duas reducoes. Quem espera 40 min
    entre uma tentativa e outra continua sondando; uma reducao so, horas
    depois, e ajuste.
    """

    code = "SONDAGEM_DE_LIMITE"
    axis = MOVIMENTACAO
    family = "uso_de_limites"

    def evaluate(self, ctx, params):
        p = params[self.code]
        curta, valores_curta = self._reducoes(ctx, p, p["window_minutes"])
        if valores_curta is None:
            return self.not_triggered("Valor bem menor e para outro destino: outro pagamento, nao a mesma "
                                      "tentativa com valor reduzido.")
        longa, valores_longa = self._reducoes(ctx, p, p["long_window_minutes"])
        if max(curta, longa) >= 2:
            reducoes, valores = (curta, valores_curta) if curta >= 2 else (longa, valores_longa)
            sequencia = " -> ".join(brl(v) for v in valores[-(reducoes + 1):])
            return self.triggered(p["two"], f"Valores baixando depois de decisoes restritivas: {sequencia}.",
                                  floor=FACIAL_DOCUMENT, data_origin="history")
        if curta == 1:
            sequencia = " -> ".join(brl(v) for v in valores_curta[-2:])
            return self.triggered(p["one"], f"Valor menor depois de uma decisao restritiva: {sequencia}.",
                                  data_origin="history")
        return self.not_triggered()

    def _reducoes(self, ctx, p, minutos):
        """(reducoes seguidas ate este Pix, valores) na janela; valores None quando e outro pagamento."""
        anteriores = ctx.history.restrictive_attempts(ctx.source_account.id, ctx.moment, minutos)
        if anteriores:
            ultimo = anteriores[-1]
            outro_destino = ultimo.destination_document != ctx.destination_document
            if outro_destino and ctx.amount < p["other_destination_min_ratio"] * int(ultimo.amount):
                return 0, None
        valores = [int(linha.amount) for linha in anteriores] + [ctx.amount]
        reducoes = 0
        for indice in range(len(valores) - 1, 0, -1):
            if valores[indice] < valores[indice - 1]:
                reducoes += 1
            else:
                break
        return reducoes, valores
