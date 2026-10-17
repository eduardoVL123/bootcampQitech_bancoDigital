from datetime import timedelta

from sqlalchemy import text
from sqlalchemy.dialects.postgresql import insert

from database import Context
from models import Watchlist

CLIENT_REPORT_DAYS = 30


class WatchlistRepository:
    def __init__(self, context: Context) -> None:
        self.session = context.db_session

    def listed(self, kind: str, value: str, moment):
        """A entrada vigente da lista para este aparelho ou documento, se houver."""
        return self.session.execute(text(
            "SELECT evidence_id, creator, report_type FROM watchlist WHERE kind = :kind AND value = :value "
            "AND available_from <= :momento AND expires_at > :momento ORDER BY available_from LIMIT 1"
        ), {"kind": kind, "value": value, "momento": moment}).first()

    def add_client_report(self, kind: str, value: str, evidence_id: str, event_date) -> None:
        """O titular disse "nao fui eu": evidencia independente da decisao do motor."""
        comando = insert(Watchlist).values(
            kind=kind, value=value, report_type="fraud", creator="client", evidence_id=evidence_id,
            available_from=event_date, expires_at=event_date + timedelta(days=CLIENT_REPORT_DAYS),
        ).on_conflict_do_nothing(index_elements=["evidence_id"])
        self.session.execute(comando)
