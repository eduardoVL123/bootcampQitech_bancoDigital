from sqlalchemy.dialects.postgresql import insert

from database import Context
from models import PixAccount


class AccountRepository:
    def __init__(self, context: Context) -> None:
        self.session = context.db_session

    def get_or_create(self, participant: str, branch: str, account_number: str, opening_date, document: str) -> PixAccount:
        """A conta, criada na primeira vez que o motor a ve.

        O INSERT ... ON CONFLICT DO NOTHING nao devolve a linha que ja existia
        (armadilha 11 do CLAUDE.md), por isso o SELECT logo depois. Se o
        opening_date chegar diferente mais tarde, vale o primeiro.
        """
        comando = insert(PixAccount).values(
            participant=participant, branch=branch, account_number=account_number,
            opening_date=opening_date, owner_document=document,
        ).on_conflict_do_nothing(constraint="pix_account_unique")
        self.session.execute(comando)
        return self.session.query(PixAccount).filter(
            PixAccount.participant == participant,
            PixAccount.branch == branch,
            PixAccount.account_number == account_number,
        ).one()

    def get(self, participant: str, branch: str, account_number: str):
        return self.session.query(PixAccount).filter(
            PixAccount.participant == participant,
            PixAccount.branch == branch,
            PixAccount.account_number == account_number,
        ).first()
