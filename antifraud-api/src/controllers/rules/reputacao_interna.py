from controllers.engine.context import DESTINO
from controllers.engine.rule import Rule
from repositories.watchlist_repository import CONFIRMED


class ReputacaoInterna(Rule):
    """O documento destino ou o aparelho estao na lista interna vigente.

    A lista tem tres tipos de entrada, e nenhuma vem da decisao do proprio
    motor (uma rejeicao por limite nao diz nada sobre o recebedor, e
    alimentar a lista com ela faria um falso positivo gerar outros em cadeia):
    - `external`: caso confirmado fora daqui (semeado);
    - `client`: a cautelar. Um titular disse "nao fui eu" depois de um
      desafio, e o documento destino fica em observacao por 24 horas;
    - `confirmed`: duas fontes independentes apontaram o mesmo documento
      (dois titulares distintos, ou um titular e a reputacao externa). Ver
      controllers/challenge_controller.py.

    Documento destino com fraude CONFIRMADA e bloqueio, nao 2FA. A
    verificacao responde "e o dono da conta mesmo?", e no golpe quem paga e
    o proprio dono, enganado: ele faz a facial e passa. Contra conta que a
    casa ja sabe que e de golpe, so recusar protege (e a Res. BCB 501/2025
    manda recusar pagamento para conta com fundada suspeita de fraude).

    A cautelar soma +40, sem bloquear: e a palavra de um cliente so, e
    bloquear com ela deixaria qualquer cliente travar o recebimento de
    qualquer pessoa. Se ninguem mais reclamar, ela vence sozinha. O aparelho
    tambem fica em +40: risco de quem paga, e ai a verificacao funciona.
    """

    code = "REPUTACAO_INTERNA"
    axis = DESTINO
    family = "reputacao"

    def evaluate(self, ctx, params):
        p = params[self.code]
        for tipo, valor in (("document", ctx.destination_document), ("device", ctx.device_id)):
            entrada = ctx.watchlist.listed(tipo, valor, ctx.moment)
            if entrada is None:
                continue
            if tipo == "document" and entrada.creator in CONFIRMED and entrada.report_type == "fraud":
                return self.triggered(0, "Documento destino na lista interna como fraude confirmada.",
                                      hard_block=True, data_origin="history", evidence_ids=[entrada.evidence_id],
                                      creator=entrada.creator, kind=tipo)
            if tipo == "document" and entrada.creator == "client":
                return self.triggered(p["points"], "Documento destino em cautelar: um titular disse \"nao fui eu\" "
                                      "e ninguem mais confirmou ainda.", data_origin="history",
                                      evidence_ids=[entrada.evidence_id], creator=entrada.creator, kind=tipo)
            alvo = "Documento destino" if tipo == "document" else "Aparelho"
            # `kind` separa o recebedor denunciado do aparelho de quem paga: so o
            # primeiro confirma o eixo destino (controllers/engine/decision.py).
            return self.triggered(p["points"], f"{alvo} na lista interna ({entrada.report_type}, {entrada.creator}).",
                                  data_origin="history", evidence_ids=[entrada.evidence_id],
                                  creator=entrada.creator, kind=tipo)
        return self.not_triggered()
