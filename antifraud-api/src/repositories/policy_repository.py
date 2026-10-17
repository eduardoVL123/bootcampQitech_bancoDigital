from database import Context
from models import FraudPolicy


class PolicyRepository:
    def __init__(self, context: Context) -> None:
        self.session = context.db_session

    def get_current(self) -> FraudPolicy:
        """A politica de versao mais alta. A analise grava qual usou."""
        return self.session.query(FraudPolicy).order_by(FraudPolicy.version.desc()).first()
