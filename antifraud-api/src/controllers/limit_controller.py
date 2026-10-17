from datetime import datetime, timedelta, timezone

from constants import OWN_PARTICIPANT, TIME_SKEW_SECONDS
from controllers.base_controller import BaseController
from controllers.pix_controller import parse_moment
from errors import TransactionBeforeAccountOpening, TransactionDateInTheFuture
from repositories import AccountRepository, HistoryRepository, LimitRepository, PolicyRepository
from utils.document_number import digits_of


class LimitController(BaseController):
    """O titular muda o proprio limite por Pix.

    Reduzir vale na hora. Aumentar so vale 24 horas depois do pedido: e o
    roteiro do golpe de conta tomada (subir o limite e esvaziar) que esse
    atraso quebra. O Banco Central descreve 24 a 48 horas para o aumento;
    aqui a politica do mock usa 24.
    """

    def __init__(self) -> None:
        super().__init__(__name__)
        self.account_repo = AccountRepository(self.context)
        self.limit_repo = LimitRepository(self.context)
        self.history_repo = HistoryRepository(self.context)
        self.policy_repo = PolicyRepository(self.context)

    def change(self, payload: dict):
        requested_at = parse_moment(payload["requested_at"])
        if requested_at > datetime.now(timezone.utc) + timedelta(seconds=TIME_SKEW_SECONDS):
            raise TransactionDateInTheFuture(payload["requested_at"], TIME_SKEW_SECONDS)
        opening_date = parse_moment(payload["opening_date"])
        if opening_date > requested_at:
            raise TransactionBeforeAccountOpening("account")

        documento = digits_of(payload["owner"]["document_number"])
        conta = self.account_repo.get_or_create(
            OWN_PARTICIPANT, payload["branch"], payload["account_number"], opening_date, documento,
        )
        # A mesma trava do pagador que o Pix usa: o limite nao muda no meio
        # da analise de um Pix desta conta.
        self.history_repo.lock([f"payer:{documento}"])

        atraso = self.policy_repo.get_current().parameters["AUMENTO_PENDENTE"]["delay_hours"]
        vigente = self.limit_repo.effective(conta.id, requested_at)
        valor = int(payload["amount"])
        if vigente is None:
            tipo, vale_a_partir = "initial", requested_at
        elif valor < vigente.amount:
            tipo, vale_a_partir = "decrease", requested_at
        elif valor > vigente.amount:
            tipo, vale_a_partir = "increase", requested_at + timedelta(hours=atraso)
        else:
            tipo, vale_a_partir = "same", requested_at

        limite = self.limit_repo.create(conta.id, valor, tipo, requested_at, vale_a_partir)
        self.session.commit()
        return limite
