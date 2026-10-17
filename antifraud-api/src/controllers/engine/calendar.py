"""O calendario do proprio cliente: em que dias do mes ele faz os pagamentos grandes.

Versao enxuta, declarada no README: so o dia do mes, com tolerancia de 2
dias para cada lado (uma janela de 5 dias). Sem dia util nem feriado.

Um padrao existe quando, em pelo menos 3 meses, a janela contem 60% ou mais
dos pagamentos relevantes (R$ 1.000 ou mais) do mes, com no minimo 2 deles
por mes. Os meses vem dos 6 anteriores ao de hoje; a referencia e congelada
no inicio do dia, como as outras.
"""
from dataclasses import dataclass, field
from typing import Optional

from controllers.engine.profile import day_start

HISTORY_DAYS = 186


@dataclass
class Calendar:
    evaluable: bool
    center: Optional[int] = None
    months: int = 0
    inside: bool = False
    phase: list = field(default_factory=list)
    reason: str = ""


def _distance(dia: int, centro: int) -> int:
    return abs(dia - centro)


def calendar_for(ctx, params) -> Calendar:
    if "calendar" in ctx.cache:
        return ctx.cache["calendar"]
    p = params["PADRAO_MENSAL"]
    fuso = ctx.local_moment.tzinfo
    linhas = ctx.history.approved_amounts_of_payer(ctx.source_account.id, day_start(ctx), HISTORY_DAYS)
    por_mes = {}
    for valor, data in linhas:
        local = data.astimezone(fuso)
        if int(valor) >= p["min_amount"]:
            por_mes.setdefault((local.year, local.month), []).append(local.day)
    meses = {mes: dias for mes, dias in por_mes.items() if len(dias) >= p["min_per_month"]}
    if len(meses) < p["months"]:
        resultado = Calendar(False, reason=f"So {len(meses)} meses com pagamentos relevantes; a regra pede {p['months']}.")
        ctx.cache["calendar"] = resultado
        return resultado

    melhor_centro, melhor_meses = None, 0
    for centro in range(1, 32):
        cobertos = sum(
            1 for dias in meses.values()
            if sum(1 for d in dias if _distance(d, centro) <= p["tolerance_days"]) / len(dias) >= p["share"]
        )
        if cobertos > melhor_meses:
            melhor_centro, melhor_meses = centro, cobertos
    if melhor_meses < p["months"]:
        resultado = Calendar(False, months=len(meses), reason="Os pagamentos relevantes nao se concentram numa janela.")
        ctx.cache["calendar"] = resultado
        return resultado

    def na_janela(data) -> bool:
        return _distance(data.astimezone(fuso).day, melhor_centro) <= p["tolerance_days"]

    dentro = na_janela(ctx.local_moment)
    fase = [linha for linha in linhas if na_janela(linha[1]) == dentro]
    resultado = Calendar(True, center=melhor_centro, months=melhor_meses, inside=dentro, phase=fase)
    ctx.cache["calendar"] = resultado
    return resultado
