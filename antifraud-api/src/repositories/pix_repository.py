from database import Context
from models import PixAnalysis, PixRuleResult, PixStatus


class PixRepository:
    def __init__(self, context: Context) -> None:
        self.session = context.db_session

    def get_by_pix_id(self, pix_id: str) -> PixAnalysis:
        return self.session.query(PixAnalysis).filter(PixAnalysis.pix_id == pix_id).first()

    def get_status(self, enumerator: str) -> PixStatus:
        return self.session.query(PixStatus).filter(PixStatus.enumerator == enumerator).one()

    def create(self, analysis: PixAnalysis, rule_results: list) -> PixAnalysis:
        """Grava a analise e uma linha por regra avaliada, sem commit.

        O flush manda o INSERT agora: e aqui que o UNIQUE do pix_id estoura
        quando dois pedidos com o mesmo id chegam juntos, e o controller
        trata isso como replay.
        """
        self.session.add(analysis)
        self.session.flush()
        for resultado in rule_results:
            self.session.add(PixRuleResult(analysis_id=analysis.id, **resultado))
        self.session.flush()
        return analysis
