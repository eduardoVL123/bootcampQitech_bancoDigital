from database import Context
from models import PixChallengeResult


class ChallengeRepository:
    def __init__(self, context: Context) -> None:
        self.session = context.db_session

    def get(self, analysis_id: int):
        return self.session.query(PixChallengeResult).filter(PixChallengeResult.analysis_id == analysis_id).first()

    def create(self, analysis_id: int, result: str, event_date) -> PixChallengeResult:
        registro = PixChallengeResult(analysis_id=analysis_id, result=result, event_date=event_date)
        self.session.add(registro)
        self.session.flush()
        return registro
