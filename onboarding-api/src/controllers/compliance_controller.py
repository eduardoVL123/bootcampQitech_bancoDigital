from typing import List, Optional, Tuple
from uuid import UUID

from connectors import PepConnector, ReceitaConnector, SanctionsConnector
from controllers.base_controller import BaseController
from controllers.kyc_controller import BUREAU_UNAVAILABLE
from dtos import OnboardingDTO
from errors import ApprovalWithoutBureauChecks, BureauStillUnavailable, OnboardingNotFound, OnboardingNotInReview
from models import OnboardingStatus, OnboardingStatusEvent
from repositories import OnboardingRepository
from utils.clock import now_utc
from utils.credential import Credential


APPROVE = "APPROVE"

# O motivo de quem compliance recusou (RFC 05, motivos). Substitui os da revisão.
COMPLIANCE_REJECTED = "COMPLIANCE_REJECTED"


class ComplianceController(BaseController):
    """O que compliance faz pela API (RFC 05, Revisão manual por compliance):
    vê a fila, decide as aberturas em revisão e, quando o birô volta, devolve
    à fila as que pararam por birô fora."""

    def __init__(self) -> None:
        super().__init__(__name__)
        self.onboarding_repository = OnboardingRepository(self.context)

    def list_queue(self, status: str, reason_code: Optional[str], limit: int, offset: int) -> dict:
        """Uma página da fila, da abertura mais antiga para a mais nova (D30)."""
        onboardings = self.onboarding_repository.queue_page(status, reason_code, limit, offset)

        # Pedimos um a mais que o limite só para saber se existe próxima página.
        is_last_page = len(onboardings) <= limit

        return {
            "data": [OnboardingDTO.queue_item(onboarding) for onboarding in onboardings[:limit]],
            "is_last_page": is_last_page,
        }

    def decide(self, onboarding_key: str, decision: str, justification: str, credential: Credential) -> Tuple[dict, bool]:
        """Aprova ou recusa uma abertura em MANUAL_REVIEW, com a justificativa e
        quem decidiu no histórico (D31). Devolve a resposta e se foi aprovação.

        A trava vem antes da conferência da etapa: duas decisões juntas passam
        daqui uma de cada vez, e a segunda já vê a etapa que a primeira gravou.
        """
        if self.onboarding_repository.get_by_key(onboarding_key) is None:
            raise OnboardingNotFound()

        now = now_utc()
        onboarding = self.onboarding_repository.get_by_key_for_update(onboarding_key)

        if onboarding.status.enumerator != OnboardingStatus.MANUAL_REVIEW:
            raise OnboardingNotInReview()

        approved = decision == APPROVE

        if approved:
            # Sem as consultas obrigatórias, não há aprovação: o caminho é a
            # retentativa em lote quando o birô voltar (D32).
            if onboarding.reason_codes == BUREAU_UNAVAILABLE:
                raise ApprovalWithoutBureauChecks()
            new_status = OnboardingStatus.APPROVED
        else:
            onboarding.reason_codes = COMPLIANCE_REJECTED
            new_status = OnboardingStatus.REJECTED

        onboarding.updated_at = now
        self.onboarding_repository.change_status(
            onboarding, new_status, OnboardingStatusEvent.COMPLIANCE, now, justification, credential.subject
        )

        response = OnboardingDTO.decided(onboarding)

        self.session.commit()
        return response, approved

    def requeue_bureau_unavailable(self, onboarding_keys: Optional[List[str]], credential: Credential) -> dict:
        """Devolve à fila as aberturas paradas só por birô fora (RFC 05, Birô fora do ar).

        Primeiro, uma chamada de teste a cada birô obrigatório, sem nenhuma
        trava aberta: se algum ainda não responde, nada muda. Depois, todas
        de uma vez, no mesmo COMMIT, cada uma com o evento e quem pediu. A
        abertura volta sem motivo e sem tentativas, e a contagem das 24 horas
        recomeça (D28). Sem `onboarding_keys`, vale para todas as paradas por birô fora.
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
            self.onboarding_repository.change_status(
                onboarding, OnboardingStatus.PENDING_KYC, OnboardingStatusEvent.COMPLIANCE, now, decided_by=credential.subject
            )

        response = OnboardingDTO.requeued(len(onboardings))

        self.session.commit()
        return response
