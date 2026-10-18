"""A regua de cada cliente: o que e "muito" para ELE.

Para cada dia com movimento nos 30 dias completos antes de hoje, o motor
guarda o pico da janela movel (o maximo de tentativas em 5 min naquele
dia, por exemplo). Com esses picos:

    m = mediana dos picos
    s = MAD dos picos / 0,6745   (a estimativa robusta do desvio padrao)
    moderado = max(minimo, ceil(multiplo * m), ceil(m + k * s))

Tres cuidados, e o porque de cada um:
- A regua e congelada no inicio do dia (Sao Paulo): so usa dias completos
  anteriores. O ataque de hoje nao entra na regua de hoje, e reavaliar o
  mesmo Pix da o mesmo resultado.
- Dia sem movimento fica de fora; nunca vira zero. Zero puxaria a mediana
  para baixo e transformaria em "rajada" o ritmo normal de quem usa pouco.
- Sem 7 dias ativos e 20 eventos, nao ha regua: a regra usa a reserva.
"""
import math
from collections import Counter
from dataclasses import dataclass
from datetime import timedelta
from statistics import median
from typing import Optional

from controllers.engine.context import FACIAL_DOCUMENT, NONE

MAD_TO_SIGMA = 0.6745


@dataclass
class Reference:
    peaks: list
    m: float
    s: float

    def describe(self) -> dict:
        return {"active_days": len(self.peaks), "median_peak": round(self.m, 2), "sigma": round(self.s, 2)}


@dataclass
class Level:
    points: int
    floor: str
    count: int
    minutes: int
    moderate: int
    high: int
    reference: Reference

    def describe(self) -> dict:
        return {"count": self.count, "moderate": self.moderate, "high": self.high, **self.reference.describe()}


@dataclass
class Deviation:
    deviates: bool
    threshold: int
    reference: Reference

    def describe(self) -> dict:
        return {"threshold": self.threshold, **self.reference.describe()}


def _day_start(ctx):
    return ctx.local_moment.replace(hour=0, minute=0, second=0, microsecond=0)


def _events(ctx, params, kind) -> list:
    chave = ("events", kind)
    if chave not in ctx.cache:
        inicio = _day_start(ctx)
        dias = params["reference"]["days"]
        if kind == "payers":
            ctx.cache[chave] = ctx.history.incoming_events(ctx.destination_account.id, inicio - timedelta(days=dias), inicio)
        else:
            ctx.cache[chave] = ctx.history.outgoing_events(ctx.source_account.id, inicio - timedelta(days=dias), inicio)
    return ctx.cache[chave]


def _peaks(ctx, events, kind, minutes) -> list:
    """O pico da janela movel em cada dia com movimento.

    Os eventos chegam em ordem de data (as duas consultas tem ORDER BY), e a
    janela desliza: cada evento entra uma vez e sai uma vez. Varrer de novo
    todos os anteriores para cada evento dava o mesmo resultado com custo
    quadratico: 10 mil eventos de uma loja levavam 11 s por Pix, contra
    37 ms assim (docs/testes/antifraude-escala.md).
    """
    janela = timedelta(minutes=minutes)
    fuso = ctx.local_moment.tzinfo
    por_dia = {}
    esquerda = 0
    soma = 0
    documentos = Counter()
    for indice, (data, valor, extra) in enumerate(events):
        if kind == "approved_amount" and extra:
            soma += valor
        elif kind not in ("attempts", "approved_amount"):
            documentos[extra] += 1
        while events[esquerda][0] <= data - janela:
            _saiu, valor_saiu, extra_saiu = events[esquerda]
            if kind == "approved_amount" and extra_saiu:
                soma -= valor_saiu
            elif kind not in ("attempts", "approved_amount"):
                documentos[extra_saiu] -= 1
                if documentos[extra_saiu] == 0:
                    del documentos[extra_saiu]
            esquerda += 1
        if kind == "attempts":
            atual = indice - esquerda + 1
        elif kind == "approved_amount":
            atual = soma
        else:
            atual = len(documentos)
        dia = data.astimezone(fuso).date()
        por_dia[dia] = max(por_dia.get(dia, 0), atual)
    return [pico for pico in por_dia.values() if pico > 0]


def reference_for(ctx, params, kind, minutes) -> Optional[Reference]:
    chave = ("reference", kind, minutes)
    if chave in ctx.cache:
        return ctx.cache[chave]
    eventos = _events(ctx, params, kind)
    minimos = params["reference"]
    referencia = None
    if len(eventos) >= minimos["min_events"]:
        picos = _peaks(ctx, eventos, kind, minutes)
        if len(picos) >= minimos["min_active_days"]:
            m = median(picos)
            mad = median(abs(p - m) for p in picos)
            referencia = Reference(picos, m, mad / MAD_TO_SIGMA)
    ctx.cache[chave] = referencia
    return referencia


def _threshold(referencia: Reference, faixa: dict) -> int:
    return max(faixa["minimum"], math.ceil(faixa["multiple"] * referencia.m), math.ceil(referencia.m + faixa["k"] * referencia.s))


def adaptive_level(ctx, params, kind, minutes, count, p) -> Optional[Level]:
    """O nivel de uma contagem contra a regua do cliente, ou None sem regua."""
    referencia = reference_for(ctx, params, kind, minutes)
    if referencia is None:
        return None
    moderado = _threshold(referencia, p["moderate"])
    alto = _threshold(referencia, p["high"])
    if count >= alto:
        return Level(p["high"]["points"], FACIAL_DOCUMENT, count, minutes, moderado, alto, referencia)
    if count >= moderado:
        return Level(p["moderate"]["points"], NONE, count, minutes, moderado, alto, referencia)
    return Level(0, NONE, count, minutes, moderado, alto, referencia)


def deviates(ctx, params, kind, minutes, total, p) -> Optional[Deviation]:
    """Se um montante foge do padrao do cliente, ou None sem regua."""
    referencia = reference_for(ctx, params, kind, minutes)
    if referencia is None:
        return None
    corte = math.ceil(max(p["multiple"] * referencia.m, referencia.m + p["k"] * referencia.s, referencia.m + p["floor"]))
    return Deviation(total >= corte, corte, referencia)
