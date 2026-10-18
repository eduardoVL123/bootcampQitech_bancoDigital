from controllers.engine.context import ACESSO, FACIAL
from controllers.engine.rule import Rule
from utils.money import brl


class AparelhoNaoCadastrado(Rule):
    """A regra do Banco Central para aparelho que o titular nunca cadastrou.

    Desde 1/11/2024 (Res. BCB 403/2024), Pix iniciado por um aparelho nunca
    usado pelo cliente fica em R$ 200 por transacao e R$ 1.000 por dia; acima
    disso, o aparelho precisa ser cadastrado antes. O contrato nao traz
    "cadastro de aparelho", entao o motor aproxima assim:
    - cadastrado e o aparelho do primeiro Pix do titular (o do onboarding)
      ou um aparelho em que ele ja confirmou uma verificacao (PATCH
      approved_by_client);
    - fora disso, passar de R$ 200 no Pix ou de R$ 1.000 no dia, nesse
      aparelho, pede a facial: a verificacao e o cadastro.

    Nao soma pontos (o APARELHO_NOVO ja pontua a troca). So pelo app e pela
    web: pela api o "aparelho" e o sistema da empresa.
    """

    code = "APARELHO_NAO_CADASTRADO"
    axis = ACESSO
    family = "cadastro_de_aparelho"

    def evaluate(self, ctx, params):
        p = params[self.code]
        if ctx.channel not in p["channels"]:
            return self.not_triggered()
        if ctx.history.prior_attempts_of_document(ctx.source_document, ctx.moment) == 0:
            return self.not_triggered("Primeiro Pix do titular: e o aparelho do cadastro.")
        dia = ctx.local_moment.replace(hour=0, minute=0, second=0, microsecond=0)
        primeiro, confirmado, hoje = ctx.history.device_registration(ctx.source_document, ctx.device_id,
                                                                     ctx.moment, dia)
        if primeiro == ctx.device_id or confirmado:
            return self.not_triggered("Aparelho cadastrado (o do primeiro Pix, ou ja confirmado numa verificacao).")
        if ctx.amount > p["per_pix"]:
            return self.triggered(0, f"{brl(ctx.amount)} num aparelho sem cadastro: acima de {brl(p['per_pix'])} por "
                                  "Pix, o aparelho precisa ser cadastrado (Res. BCB 403/2024).", floor=FACIAL,
                                  data_origin="history")
        if hoje + ctx.amount > p["per_day"]:
            return self.triggered(0, f"{brl(hoje + ctx.amount)} hoje num aparelho sem cadastro: acima de "
                                  f"{brl(p['per_day'])} por dia, o aparelho precisa ser cadastrado (Res. BCB "
                                  "403/2024).", floor=FACIAL, data_origin="history")
        return self.not_triggered(f"Aparelho sem cadastro, dentro de {brl(p['per_pix'])} por Pix e "
                                  f"{brl(p['per_day'])} por dia.")
