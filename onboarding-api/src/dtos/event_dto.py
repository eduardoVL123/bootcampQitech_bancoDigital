from dtos.onboarding_dto import reason_codes
from models import Onboarding, OnboardingOutbox


class EventDTO:
    """O que vai para a webhook-api (RFC 05, Eventos): só chaves, risco e
    motivos. Nunca dado pessoal, porque o evento sai do banco."""

    @staticmethod
    def data(onboarding: Onboarding, event_type: str) -> dict:
        """O data do evento, com o que a abertura tem no momento da mudança de etapa."""
        if event_type == OnboardingOutbox.KYC_APPROVED:
            return {
                "onboarding_key": onboarding.onboarding_key,
                "customer_key": onboarding.customer_key,
                "risk_level": onboarding.risk_level,
            }

        if event_type == OnboardingOutbox.CREATED:
            return {
                "onboarding_key": onboarding.onboarding_key,
                "customer_key": onboarding.customer_key,
                "account_key": onboarding.account_key,
            }

        return {
            "onboarding_key": onboarding.onboarding_key,
            "reason_codes": reason_codes(onboarding),
        }

    @staticmethod
    def envelope(outbox: OnboardingOutbox) -> dict:
        """O corpo do POST /internal/event."""
        return {
            "event_id": outbox.event_id,
            "event_type": outbox.event_type,
            "occurred_at": outbox.occurred_at.isoformat(),
            "data": outbox.payload,
        }
