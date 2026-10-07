from datetime import datetime
from typing import Optional, Tuple
from uuid import uuid4

from sqlalchemy import and_, or_, tuple_

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
        onboarding.customer_key = customer.customer_key
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

    def get_by_key_for_update_skip_locked(self, onboarding_key: str) -> Optional[Onboarding]:
        """A abertura travada até o COMMIT, ou None se outro já a travou
        (FOR UPDATE SKIP LOCKED): o worker pula e pega na próxima passada."""
        return (
            self.session.query(Onboarding)
            .filter(Onboarding.onboarding_key == onboarding_key)
            .with_for_update(skip_locked=True)
            .populate_existing()
            .first()
        )

    def overdue(self, now: datetime, after: Optional[Tuple[datetime, int]], limit: int) -> list:
        """As aberturas que o worker precisa vencer: em DRAFT depois do prazo,
        ou já EXPIRED com o cadastro ainda guardado (o bucket falhou numa
        passada anterior). As mais antigas primeiro.

        Cada lote começa depois do último visto (`after`, o par expires_at e
        id). Assim a passada sempre anda, mesmo que um lote inteiro falhe e
        continue na lista: as vencidas que vêm depois não ficam esperando."""
        draft_overdue = and_(OnboardingStatus.enumerator == OnboardingStatus.DRAFT, Onboarding.expires_at <= now)
        expired_with_data = and_(OnboardingStatus.enumerator == OnboardingStatus.EXPIRED, Onboarding.customer_id.isnot(None))

        query = (
            self.session.query(Onboarding.expires_at, Onboarding.id, Onboarding.onboarding_key)
            .join(OnboardingStatus, Onboarding.status_id == OnboardingStatus.id)
            .filter(or_(draft_overdue, expired_with_data))
        )

        if after is not None:
            query = query.filter(tuple_(Onboarding.expires_at, Onboarding.id) > tuple_(*after))

        return query.order_by(Onboarding.expires_at, Onboarding.id).limit(limit).all()

    def erase_personal_data(self, onboarding: Onboarding, now: datetime) -> None:
        """Apaga o que é dado pessoal (LGPD): as linhas do RG, o cadastro e a
        renda, a ocupação e o PEP da abertura. Fica a linha da abertura, com
        a customer_key, a etapa e o histórico, que não identificam ninguém."""
        customer = onboarding.customer

        for document in list(onboarding.documents):
            self.session.delete(document)

        onboarding.customer = None
        onboarding.declared_monthly_income = None
        onboarding.occupation = None
        onboarding.pep_self_declared = None
        onboarding.updated_at = now

        # Primeiro a abertura solta o cadastro (customer_id nulo), e só então
        # o cadastro é apagado: a FK não deixaria na ordem contrária.
        self.session.flush()
        self.session.delete(customer)

    def get_by_idempotency_key(self, idempotency_key: str) -> Optional[Onboarding]:
        return self.session.query(Onboarding).filter(Onboarding.idempotency_key == idempotency_key).first()

    def get_status(self, enumerator: str) -> OnboardingStatus:
        return self.session.query(OnboardingStatus).filter(OnboardingStatus.enumerator == enumerator).one()
