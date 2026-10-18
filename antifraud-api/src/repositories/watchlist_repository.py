from datetime import timedelta

from sqlalchemy import text
from sqlalchemy.dialects.postgresql import insert

from database import Context
from models import Watchlist

# Quem confirmou a fraude: o caso semeado (de fora) ou duas fontes independentes.
CONFIRMED = ("external", "confirmed")


class WatchlistRepository:
    def __init__(self, context: Context) -> None:
        self.session = context.db_session

    def listed(self, kind: str, value: str, moment):
        """A entrada vigente da lista para este aparelho ou documento, se houver.

        Com mais de uma, a confirmada vem primeiro: a cautelar de um "nao fui
        eu" nao pode esconder a fraude confirmada do mesmo documento.
        """
        return self.session.execute(text(
            "SELECT evidence_id, creator, report_type FROM watchlist WHERE kind = :kind AND value = :value "
            "AND available_from <= :momento AND expires_at > :momento "
            "ORDER BY (creator IN ('external', 'confirmed')) DESC, available_from LIMIT 1"
        ), {"kind": kind, "value": value, "momento": moment}).first()

    def add_client_report(self, kind: str, value: str, evidence_id: str, event_date, hours: float,
                          reporter: str = None, since=None) -> None:
        """O titular disse "nao fui eu": evidencia independente da decisao do motor.

        `since` e o inicio da entrada, quando ele vem antes da denuncia: o
        recebedor ja era suspeito desde o Pix contestado.
        """
        self._add(kind, value, "client", evidence_id, event_date, timedelta(hours=hours), reporter, since)

    def reporters_of(self, document: str, moment, days: int) -> set:
        """Os titulares distintos que disseram "nao fui eu" para este documento nos ultimos `days` dias.

        Conta a denuncia mesmo depois que a cautelar dela venceu: a segunda
        vitima costuma reclamar dias depois da primeira.
        """
        return {linha[0] for linha in self.session.execute(text(
            "SELECT DISTINCT reporter FROM watchlist WHERE kind = 'document' AND value = :doc "
            "AND creator = 'client' AND reporter IS NOT NULL "
            "AND available_from > :inicio AND available_from <= :momento"
        ), {"doc": document, "inicio": moment - timedelta(days=days), "momento": moment}).all()}

    def confirm(self, document: str, evidence_id: str, event_date, days: int) -> None:
        """Duas fontes independentes apontaram o documento: vira fraude confirmada, por `days` dias."""
        self._add("document", document, "confirmed", evidence_id, event_date, timedelta(days=days), None)

    def _add(self, kind, value, creator, evidence_id, event_date, duracao, reporter, since=None) -> None:
        comando = insert(Watchlist).values(
            kind=kind, value=value, report_type="fraud", creator=creator, reporter=reporter,
            evidence_id=evidence_id, available_from=since or event_date, expires_at=event_date + duracao,
        ).on_conflict_do_nothing(index_elements=["evidence_id"])
        self.session.execute(comando)
