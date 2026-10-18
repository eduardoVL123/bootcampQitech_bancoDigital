"""O cenario: uma hipotese em palavras do que esta acontecendo.

So explica, nao soma pontos. Os candidatos sao conferidos nesta ordem, e o
primeiro que casar vence; todos os que casaram vao em `scenario_candidates`.
"""
from models import PixStatus


def _any(ctx, *rules) -> bool:
    return any(ctx.triggered(rule) for rule in rules)


def _limite(ctx, decision) -> bool:
    return any(r.hard_block and r.is_triggered and r.rule == "LIMITE_POR_PIX"
               for r in ctx.results.values())


def _recebedor_critico(ctx, decision) -> bool:
    """Bloqueio por evidencia do recebedor: a do mock externo ou a da lista interna."""
    for regra in ("REPUTACAO_EXTERNA", "REPUTACAO_INTERNA"):
        resultado = ctx.result(regra)
        if resultado is not None and resultado.is_triggered and resultado.hard_block:
            return True
    return False


def _conta_tomada(ctx, decision) -> bool:
    if ctx.triggered("RUPTURA_DE_CONTEXTO"):
        return True
    geografia = _any(ctx, "VIAGEM_IMPOSSIVEL", "GEO_IP_DIVERGENTE", "GEO_AUSENTE")
    return ctx.triggered("APARELHO_NOVO") and geografia and ctx.triggered("CONTRAPARTE_INEDITA")


def _coacao(ctx, decision) -> bool:
    return (ctx.triggered("NOTURNO") and ctx.triggered("CONTRAPARTE_INEDITA")
            and _any(ctx, "PERFIL", "LIMITE_POR_PIX"))


def _com_pontos(ctx, decision) -> bool:
    return any(r.effective_points > 0 for r in ctx.results.values())


CANDIDATES = [
    ("restricao_por_limite", _limite),
    ("risco_critico_do_recebedor", _recebedor_critico),
    ("coordenacao_entre_contas", lambda ctx, d: ctx.triggered("COORDENACAO_ENTRE_CONTAS")),
    ("conta_laranja", lambda ctx, d: _any(ctx, "CONTA_LARANJA", "REPASSE_RAPIDO")),
    ("conta_tomada", _conta_tomada),
    ("sondagem_de_limite", lambda ctx, d: ctx.triggered("SONDAGEM_DE_LIMITE")),
    ("data_fora_de_ordem", lambda ctx, d: ctx.triggered("DATA_RETROATIVA")),
    ("esvaziamento_fatiado",
     lambda ctx, d: _any(ctx, "VELOCITY", "FATIAMENTO", "MONTANTE_24H", "DISPERSAO_DE_SAIDA")),
    ("coacao_noturna", _coacao),
    ("pagamento_recorrente",
     lambda ctx, d: ctx.triggered("DESTINO_CONFIAVEL") and d.status == PixStatus.APPROVED),
    ("primeiro_pagamento",
     lambda ctx, d: ctx.triggered("CONTRAPARTE_INEDITA") and d.status == PixStatus.TWO_FACTOR_REQUIRED),
    ("sem_alerta_relevante", lambda ctx, d: not _com_pontos(ctx, d)),
    ("risco_contextual", lambda ctx, d: True),
]


def scenario(ctx, decision) -> tuple:
    casaram = [nome for nome, condicao in CANDIDATES if condicao(ctx, decision)]
    return casaram[0], casaram
