"""O que uma regra recebe e o que ela devolve.

A regra nao escreve SQL e nao grava nada. Ela le o Pix pelo contexto e faz
perguntas ao historico (`ctx.history`), que o controller montou com os
repositories. Assim cada regra e uma funcao do que aconteceu, e a ordem em
que os dados chegam ao banco fica num lugar so.
"""
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

TRIGGERED = "triggered"
NOT_TRIGGERED = "not_triggered"
NOT_EVALUABLE = "not_evaluable"

MOVIMENTACAO = "movimentacao"
ACESSO = "acesso"
DESTINO = "destino"
AXES = (MOVIMENTACAO, ACESSO, DESTINO)

NONE = "none"
FACIAL = "facial"
FACIAL_DOCUMENT = "facial_document"
LEVELS = (NONE, FACIAL, FACIAL_DOCUMENT)


@dataclass
class RuleResult:
    rule: str
    evaluation: str
    axis: Optional[str]
    family: Optional[str]
    raw_points: int = 0
    hard_block: bool = False
    floor: str = NONE
    detail: str = ""
    data_origin: str = "payload"
    evidence_ids: list = field(default_factory=list)
    extra: dict = field(default_factory=dict)
    effective_points: int = 0
    correlated: bool = False

    @property
    def is_triggered(self) -> bool:
        return self.evaluation == TRIGGERED


@dataclass
class Location:
    latitude: float
    longitude: float
    source: str
    country: Optional[str] = None


@dataclass
class PixContext:
    pix_id: str
    amount: int
    moment: datetime
    local_moment: datetime
    source_account: object
    destination_account: object
    source_document: str
    destination_document: str
    device_id: str
    channel: str
    ip: str
    network: str
    gps: Optional[Location]
    ip_location: Optional[Location]
    history: object
    reputation: object = None
    watchlist: object = None
    # A marcacao do DICT sobre o recebedor, ja consultada pelo controller
    # antes das travas (connectors/dict_connector.py), ou None.
    external_evidence: object = None
    results: dict = field(default_factory=dict)
    cache: dict = field(default_factory=dict)

    def result(self, rule: str) -> Optional[RuleResult]:
        """O resultado de uma regra que ja rodou. As regras compostas leem daqui."""
        return self.results.get(rule)

    def triggered(self, rule: str) -> bool:
        resultado = self.results.get(rule)
        return resultado is not None and resultado.is_triggered
