from models import Onboarding, OnboardingCheck, OnboardingDocument, OnboardingStatus


# Em DRAFT, o próximo passo depende dos lados do RG que já chegaram (decisão D23).
NEXT_STEP_BY_SIDES_SHOWN = {
    frozenset(): "SEND_DOCUMENT",
    frozenset({OnboardingDocument.FRONT}): "SEND_BACK",
    frozenset({OnboardingDocument.BACK}): "SEND_FRONT",
}

# O próximo passo nas outras etapas (RFC 05, Rotas; decisão D26): esperar,
# enquanto o banco trabalha, ou nada, quando a abertura terminou.
NEXT_STEP_BY_STATUS = {
    OnboardingStatus.PENDING_KYC: "WAIT",
    OnboardingStatus.ANALYSIS: "WAIT",
    OnboardingStatus.MANUAL_REVIEW: "WAIT",
    OnboardingStatus.APPROVED: "WAIT",
    OnboardingStatus.ACTIVE: "NONE",
    OnboardingStatus.REJECTED: "NONE",
}


def next_step(onboarding: Onboarding) -> str:
    status = onboarding.status.enumerator

    if status == OnboardingStatus.DRAFT:
        sides_shown = OnboardingDocument.sides_shown(document.side for document in onboarding.documents)
        return NEXT_STEP_BY_SIDES_SHOWN[sides_shown]

    return NEXT_STEP_BY_STATUS[status]


class OnboardingDTO:
    """Monta a resposta pública da abertura: só chaves (R5) e nenhum dado pessoal."""

    @staticmethod
    def started(onboarding: Onboarding, access_token: str) -> dict:
        """A resposta do POST /onboarding, igual no 201 e no 200 da repetição."""
        return {
            "onboarding_key": onboarding.onboarding_key,
            "customer_key": onboarding.customer_key,
            "status": onboarding.status.enumerator,
            "expires_at": onboarding.expires_at.isoformat(),
            "access_token": access_token,
            "next_step": next_step(onboarding),
        }

    @staticmethod
    def document_received(onboarding: Onboarding) -> dict:
        """A resposta do envio do RG: a etapa e o próximo passo."""
        return {
            "onboarding_key": onboarding.onboarding_key,
            "status": onboarding.status.enumerator,
            "next_step": next_step(onboarding),
        }

    @staticmethod
    def requeued(count: int) -> dict:
        """A resposta da retentativa em lote: quantas aberturas voltaram para a fila."""
        return {"requeued_count": count}

    @staticmethod
    def check(check: OnboardingCheck) -> dict:
        """Uma verificação como o cliente vê: o tipo, o resultado e o motivo.
        Nunca o que o birô respondeu, nem o protocolo dele (LGPD)."""
        return {
            "check_type": check.check_type,
            "result": check.result,
            "reason_code": check.reason_code,
        }

    @staticmethod
    def document(document: OnboardingDocument) -> dict:
        """Uma imagem do RG como o cliente vê: sem o caminho no bucket (decisão D22)."""
        return {
            "side": document.side,
            "content_type": document.content_type,
            "size_bytes": document.size_bytes,
            "created_at": document.created_at.isoformat(),
        }

    @staticmethod
    def detail(onboarding: Onboarding) -> dict:
        """A resposta do GET /onboarding/{key}: a etapa, o próximo passo, o
        prazo e o histórico. Nunca os dados do cadastro nem os consultados."""
        status = onboarding.status.enumerator

        reason_codes = []
        if onboarding.reason_codes:
            reason_codes = onboarding.reason_codes.split(",")

        status_events = []
        for event in onboarding.status_events:
            status_events.append({
                "status": event.status.enumerator,
                "reason_code": event.reason_code,
                "actor": event.actor,
                "event_datetime": event.event_datetime.isoformat(),
            })

        return {
            "onboarding_key": onboarding.onboarding_key,
            "customer_key": onboarding.customer_key,
            "status": status,
            "next_step": next_step(onboarding),
            "expires_at": onboarding.expires_at.isoformat(),
            "documents": [OnboardingDTO.document(document) for document in onboarding.documents],
            "checks": [OnboardingDTO.check(check) for check in onboarding.checks],
            "reason_codes": reason_codes,
            "risk_level": onboarding.risk_level,
            "account_key": onboarding.account_key,
            "status_events": status_events,
        }
