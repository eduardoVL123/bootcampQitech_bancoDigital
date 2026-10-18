from database import Context
from models import PixAnalysis, PixStatus


class PixRepository:
    def __init__(self, context: Context) -> None:
        self.session = context.db_session

    def get_by_pix_id(self, pix_id: str) -> PixAnalysis:
        return self.session.query(PixAnalysis).filter(PixAnalysis.pix_id == pix_id).first()

    def get_status(self, enumerator: str) -> PixStatus:
        return self.session.query(PixStatus).filter(PixStatus.enumerator == enumerator).one()

    def create(self, analysis: PixAnalysis) -> PixAnalysis:
        """Grava a analise, sem commit. O resultado das regras vai no metadata dela.

        O flush manda o INSERT agora: e aqui que o UNIQUE do pix_id estoura
        quando dois pedidos com o mesmo id chegam juntos, e o controller
        trata isso como replay.
        """
        self.session.add(analysis)
        self.session.flush()
        return analysis
