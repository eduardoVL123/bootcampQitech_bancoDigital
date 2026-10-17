"""O perfil de valor do pagador, contra a primeira referencia elegivel.

Ordem das referencias, sem somar avaliacoes:
1. o par pagador -> recebedor (5 pagamentos em 3 dias, cobrindo 14 dias):
   o aluguel compara com os alugueis, o fornecedor com o fornecedor;
2. a fase do calendario do PADRAO_MENSAL, quando ele identificou uma;
3. as saidas gerais do pagador (10 pagamentos em 3 dias).

Todas usam so aprovados dos 90 dias ate o inicio de hoje (Sao Paulo): o
proprio Pix e os de hoje nao entram na regua.
"""
from dataclasses import dataclass
from datetime import timedelta
from statistics import median
from typing import Optional

MAD_SCALE = 0.6745


@dataclass
class Profile:
    evaluable: bool
    reference: Optional[str] = None
    sample: int = 0
    m: float = 0
    mad: float = 0
    z: Optional[float] = None
    points: int = 0
    level: Optional[str] = None

    @property
    def compatible(self) -> bool:
        return self.evaluable and self.level is None

    def describe(self) -> dict:
        return {
            "reference": self.reference, "sample": self.sample, "median": round(self.m),
            "mad": round(self.mad), "zscore": round(self.z, 2) if self.z is not None else None,
        }


def day_start(ctx):
    return ctx.local_moment.replace(hour=0, minute=0, second=0, microsecond=0)


def _eligible(ctx, linhas, regra: dict) -> bool:
    if len(linhas) < regra["min_payments"]:
        return False
    fuso = ctx.local_moment.tzinfo
    datas = [linha[1].astimezone(fuso) for linha in linhas]
    if len({d.date() for d in datas}) < regra["min_days"]:
        return False
    span = regra.get("min_span_days")
    return span is None or (max(datas) - min(datas)) >= timedelta(days=span)


def _reference(ctx, params):
    p = params["PERFIL"]
    inicio = day_start(ctx)
    janela = p["window_days"]
    refs = p["references"]

    par = ctx.history.approved_amounts_of_pair(ctx.source_document, ctx.destination_document, inicio, janela)
    if _eligible(ctx, par, refs["pair"]):
        return "pair", par

    fase = ctx.cache.get("calendar_phase_amounts")
    if fase and _eligible(ctx, fase, refs["calendar_phase"]):
        return "calendar_phase", fase

    pagador = ctx.history.approved_amounts_of_payer(ctx.source_account.id, inicio, janela)
    if _eligible(ctx, pagador, refs["payer"]):
        return "payer", pagador
    return None, None


def profile_for(ctx, params) -> Profile:
    if "profile" in ctx.cache:
        return ctx.cache["profile"]
    nome, linhas = _reference(ctx, params)
    if nome is None:
        perfil = Profile(evaluable=False)
    else:
        perfil = _evaluate(ctx.amount, [int(linha[0]) for linha in linhas], nome, params["PERFIL"])
    ctx.cache["profile"] = perfil
    return perfil


def _evaluate(x: int, valores: list, nome: str, p: dict) -> Profile:
    m = median(valores)
    mad = median(abs(v - m) for v in valores)
    perfil = Profile(evaluable=True, reference=nome, sample=len(valores), m=m, mad=mad)
    if x - m < p["min_difference"]:
        return perfil
    if mad > 0:
        perfil.z = MAD_SCALE * (x - m) / mad
        alto, moderado = p["mad"]["high"], p["mad"]["moderate"]
        if perfil.z > alto["z"] and x > alto["multiple"] * m:
            perfil.level, perfil.points = "high", alto["points"]
        elif perfil.z > moderado["z"] and x > moderado["multiple"] * m:
            perfil.level, perfil.points = "moderate", moderado["points"]
    else:
        alto, moderado = p["mad_zero"]["high"], p["mad_zero"]["moderate"]
        if x > alto["multiple"] * m:
            perfil.level, perfil.points = "high", alto["points"]
        elif x > moderado["multiple"] * m:
            perfil.level, perfil.points = "moderate", moderado["points"]
    return perfil
