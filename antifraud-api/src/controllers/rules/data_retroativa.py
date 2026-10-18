from controllers.engine.context import FACIAL_DOCUMENT
from controllers.engine.rule import Rule


class DataRetroativa(Rule):
    """O Pix chegou com data anterior a um Pix que esta conta ja fez.

    Toda janela do motor e ancorada na transaction_date, e quem informa a
    data e quem chama. Um Pix datado horas antes do ultimo ja analisado ve
    um passado em que os Pix de agora ainda nao existiam: dez Pix mandados
    no mesmo minuto, com as datas recuando uma hora cada, nao disparavam
    VELOCITY, FATIAMENTO nem SONDAGEM. Basta um bug de relogio no chamador.

    A organizacao disse que as datas podem chegar POUCO fora de ordem, entao
    ate a folga (5 min) nada muda. Alem dela, o motor nao consegue confiar
    nas proprias janelas e pede a verificacao reforcada. Nao soma pontos e
    nao usa o relogio do servidor: payload com data fixa no passado continua
    passando, desde que esteja em ordem.
    """

    code = "DATA_RETROATIVA"
    axis = None
    family = "composta"

    def evaluate(self, ctx, params):
        p = params[self.code]
        ultima = ctx.history.latest_attempt(ctx.source_account.id)
        if ultima is None:
            return self.not_triggered()
        atraso = (ultima - ctx.moment).total_seconds()
        if atraso <= p["tolerance_seconds"]:
            return self.not_triggered()
        return self.triggered(0, f"Data {atraso / 60:.0f} min anterior ao ultimo Pix ja analisado desta conta: as "
                              "janelas de tempo nao enxergam os Pix mais novos.", floor=FACIAL_DOCUMENT,
                              data_origin="history", minutes_before_last=round(atraso / 60))
