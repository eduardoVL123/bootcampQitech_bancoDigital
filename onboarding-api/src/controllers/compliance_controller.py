from typing import List, Optional
from uuid import UUID

from connectors import PepConnector, ReceitaConnector, SanctionsConnector
from controllers.base_controller import BaseController
from controllers.kyc_controller import BUREAU_UNAVAILABLE
from dtos import OnboardingDTO
from errors import BureauStillUnavailable
from models import OnboardingStatus, OnboardingStatusEvent
from repositories import OnboardingRepository
from utils.clock import now_utc


class ComplianceController(BaseController):
    """O que compliance faz pela API (RFC 05). Nesta fatia, a retentativa em
    lote; a fila e a decisão chegam na F8."""

    def __init__(self) -> None:
        super().__init__(__name__)
        self.onboarding_repository = OnboardingRepository(self.context)

    def requeue_bureau_unavailable(self, onboarding_keys: Optional[List[str]]) -> dict:
        """Devolve à fila as aberturas paradas só por birô fora (RFC 05, Birô fora do ar).

        Primeiro, uma chamada de teste a cada birô obrigatório, sem nenhuma
        trava aberta: se algum ainda não responde, nada muda. Depois, todas
        de uma vez, no mesmo COMMIT, cada uma com o evento. A abertura volta
        sem motivo e sem tentativas, e a contagem das 24 horas recomeça (D28).
        Sem `onboarding_keys`, vale para todas as paradas por birô fora.
        """
        for bureau in (ReceitaConnector(), SanctionsConnector(), PepConnector()):
            if not bureau.is_up():
                raise BureauStillUnavailable()

        if onboarding_keys is not None:
            # A mesma chave escrita em maiúsculas continua sendo a mesma abertura.
            onboarding_keys = [str(UUID(key)) for key in onboarding_keys]

        now = now_utc()
        onboardings = self.onboarding_repository.in_review_only_for(BUREAU_UNAVAILABLE, onboarding_keys)

        for onboarding in onboardings:
            onboarding.reason_codes = None
            onboarding.risk_level = None
            onboarding.analysis_attempts = 0
            onboarding.next_attempt_at = None
            onboarding.lease_until = None
            onboarding.updated_at = now
            self.onboarding_repository.change_status(onboarding, OnboardingStatus.PENDING_KYC, OnboardingStatusEvent.COMPLIANCE, now)

        response = OnboardingDTO.requeued(len(onboardings))

        self.session.commit()
        return response
