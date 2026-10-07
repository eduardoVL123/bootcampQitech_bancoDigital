from datetime import datetime
from typing import Optional
from uuid import uuid4

from database import Context
from models import Customer, Onboarding, OnboardingDocument, OnboardingStatus, OnboardingStatusEvent


class OnboardingRepository:
    """Grava, busca e trava a abertura, o histórico e as imagens do RG. Só aqui existe query de abertura."""

    def __init__(self, context: Context) -> None:
        self.session = context.db_session

    @staticmethod
    def new_key() -> str:
        """A onboarding_key nasce antes da gravação, porque o cliente também a guarda (request_key)."""
        return str(uuid4())

    def create(
        self,
        onboarding_key: str,
        customer: Customer,
        onboarding_data: dict,
        idempotency_key: str,
        request_hash: str,
        expires_at: datetime,
        now: datetime,
    ) -> Onboarding:
        onboarding = Onboarding()

        onboarding.onboarding_key = onboarding_key
        onboarding.customer = customer
        onboarding.idempotency_key = idempotency_key
        onboarding.request_hash = request_hash
        onboarding.declared_monthly_income = onboarding_data["declared_monthly_income_cents"]
        onboarding.occupation = onboarding_data.get("occupation")
        onboarding.pep_self_declared = onboarding_data["pep_self_declared"]
        onboarding.analysis_attempts = 0
        onboarding.expires_at = expires_at

        self.session.add(onboarding)
        self.change_status(onboarding, OnboardingStatus.DRAFT, OnboardingStatusEvent.API, now)
        return onboarding

    def change_status(self, onboarding: Onboarding, enumerator: str, actor: str, now: datetime) -> None:
        """Muda a etapa e grava o evento junto: as duas coisas entram no mesmo COMMIT."""
        status = self.get_status(enumerator)
        onboarding.status = status

        event = OnboardingStatusEvent()
        event.status = status
        event.actor = actor
        event.event_datetime = now
        onboarding.status_events.append(event)

    def add_document(
        self,
        onboarding: Onboarding,
        side: str,
        object_key: str,
        content_type: str,
        size_bytes: int,
        now: datetime,
    ) -> None:
        """Uma linha por imagem do RG, só com o caminho no bucket: a foto nunca entra no Postgres."""
        document = OnboardingDocument()
        document.document_type = OnboardingDocument.RG
        document.side = side
        document.object_key = object_key
        document.content_type = content_type
        document.size_bytes = size_bytes
        document.created_at = now
        onboarding.documents.append(document)

    def get_by_key(self, onboarding_key: str) -> Optional[Onboarding]:
        return self.session.query(Onboarding).filter(Onboarding.onboarding_key == onboarding_key).first()

    def get_by_key_for_update(self, onboarding_key: str) -> Onboarding:
        """A abertura, que já se sabe que existe, travada até o COMMIT (SELECT ... FOR UPDATE).
        O populate_existing relê do banco o que a sessão tinha guardado de antes da trava."""
        return (
            self.session.query(Onboarding)
            .filter(Onboarding.onboarding_key == onboarding_key)
            .with_for_update()
            .populate_existing()
            .one()
        )

    def get_by_idempotency_key(self, idempotency_key: str) -> Optional[Onboarding]:
        return self.session.query(Onboarding).filter(Onboarding.idempotency_key == idempotency_key).first()

    def get_status(self, enumerator: str) -> OnboardingStatus:
        return self.session.query(OnboardingStatus).filter(OnboardingStatus.enumerator == enumerator).one()
