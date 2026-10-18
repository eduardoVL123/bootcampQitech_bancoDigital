from datetime import timedelta

from controllers.engine.context import MOVIMENTACAO
from controllers.engine.rule import Rule
from utils.document_number import is_legal_person
from utils.money import brl


class DispersaoDeSaida(Rule):
    """O titular espalha dinheiro para muitos destinos que nunca tinha pago, em 24 horas.

    E o dreno de quem controla o aparelho da vitima (mao fantasma, acesso
    remoto): aparelho, IP e lugar sao os de sempre, cada Pix fica abaixo dos
    cortes de valor e de ritmo, e cada um vai para uma conta diferente. O que
    denuncia e a quantidade de destinos novos no mesmo dia.

    Destino novo e o titular que este pagador nunca tinha pago (Pix aprovado)
    antes da janela; tentativas barradas tambem contam, porque mostram para
    onde o dinheiro ia. Pix abaixo de `min_amount` nao conta. O Pix atual
    precisa ser para um destino novo: pagar quem ja paga nao espalha nada.
    O corte e um para pessoa fisica e outro para empresa
    (`min_destinations`): empresa paga fornecedores novos o tempo todo.

    Entrou na politica versao 2: com uma politica sem o bloco, nao avalia.
    """

    code = "DISPERSAO_DE_SAIDA"
    axis = MOVIMENTACAO
    family = "dispersao_de_saida"

    def evaluate(self, ctx, params):
        p = params.get(self.code)
        if p is None:
            return self.not_evaluable("A politica em uso nao tem o bloco desta regra.")
        if ctx.destination_document == ctx.source_document or ctx.amount < p["min_amount"]:
            return self.not_triggered()
        inicio = ctx.moment - timedelta(hours=p["window_hours"])
        ja_pagos = ctx.history.approved_to_document(ctx.source_document, ctx.destination_document, ctx.moment)
        if any(linha[1] <= inicio for linha in ja_pagos):
            return self.not_triggered()
        novos = ctx.history.new_destinations(ctx.source_document, ctx.moment, p["window_hours"], p["min_amount"])
        novos = novos | {ctx.destination_document}
        tipo = "pj" if is_legal_person(ctx.source_document) else "pf"
        corte = p["min_destinations"][tipo]
        if len(novos) < corte:
            return self.not_triggered()
        return self.triggered(
            p["points"], f"{len(novos)} destinos nunca pagos antes em {p['window_hours']} h, contando este "
            f"(corte de {corte} para {tipo.upper()}, Pix a partir de {brl(p['min_amount'])}).",
            data_origin="history", new_destinations=len(novos), window_hours=p["window_hours"],
        )
