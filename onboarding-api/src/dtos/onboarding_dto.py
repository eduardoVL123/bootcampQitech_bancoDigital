from models import Onboarding, OnboardingStatus


# O próximo passo que a pessoa vê em cada etapa (RFC 05, Rotas).
NEXT_STEP_BY_STATUS = {
    OnboardingStatus.DRAFT: "SEND_DOCUMENT",
}


class OnboardingDTO:
    """Monta a resposta pública da abertura: só chaves (R5) e nenhum dado pessoal."""

    @staticmethod
    def started(onboarding: Onboarding, access_token: str) -> dict:
        """A resposta do POST /onboarding, igual no 201 e no 200 da repetição."""
        status = onboarding.status.enumerator

        return {
            "onboarding_key": onboarding.onboarding_key,
            "customer_key": onboarding.customer.customer_key,
            "status": status,
            "expires_at": onboarding.expires_at.isoformat(),
            "access_token": access_token,
            "next_step": NEXT_STEP_BY_STATUS[status],
        }

    @staticmethod
    def detail(onboarding: Onboarding) -> dict:
        """A resposta do GET /onboarding/{key}: a etapa, o próximo passo, o
        prazo e o histórico. Nunca os dados do cadastro nem os consultados."""
        status = onboarding.status.enumerator

        customer_key = None
        if onboarding.customer is not None:
            customer_key = onboarding.customer.customer_key

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
            "customer_key": customer_key,
            "status": status,
            "next_step": NEXT_STEP_BY_STATUS[status],
            "expires_at": onboarding.expires_at.isoformat(),
            "documents": [],
            "checks": [],
            "reason_codes": reason_codes,
            "risk_level": onboarding.risk_level,
            "account_key": onboarding.account_key,
            "status_events": status_events,
        }
