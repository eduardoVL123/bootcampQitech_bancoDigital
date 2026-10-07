from datetime import datetime
from typing import Optional

from sqlalchemy import exists, or_
from sqlalchemy.orm import aliased

from database import Context
from models import OnboardingOutbox


class OutboxRepository:
    """Busca e trava os eventos da outbox. Quem grava o evento é o
    change_status do OnboardingRepository, junto com a etapa (regra 12)."""

    def __init__(self, context: Context) -> None:
        self.session = context.db_session

    def take_next_due(self, now: datetime) -> Optional[OnboardingOutbox]:
        """O próximo evento a entregar, travado até o COMMIT, ou None.

        Só sai o mais antigo que falta entregar de cada abertura: enquanto um
        evento dela está PENDING, os seguintes esperam (decisão D33). Assim
        account.created nunca chega antes de account.kyc.approved. SKIP
        LOCKED: duas réplicas nunca pegam o mesmo."""
        earlier = aliased(OnboardingOutbox)
        earlier_pending = exists().where(
            earlier.onboarding_id == OnboardingOutbox.onboarding_id,
            earlier.status == OnboardingOutbox.PENDING,
            earlier.id < OnboardingOutbox.id,
        )

        return (
            self.session.query(OnboardingOutbox)
            .filter(
                OnboardingOutbox.status == OnboardingOutbox.PENDING,
                or_(OnboardingOutbox.next_attempt_at.is_(None), OnboardingOutbox.next_attempt_at <= now),
                ~earlier_pending,
            )
            .order_by(OnboardingOutbox.id)
            .with_for_update(skip_locked=True, of=OnboardingOutbox)
            .populate_existing()
            .first()
        )

    def get_for_update(self, event_id: str) -> OnboardingOutbox:
        """O evento, que já se sabe que existe, travado até o COMMIT."""
        return (
            self.session.query(OnboardingOutbox)
            .filter(OnboardingOutbox.event_id == event_id)
            .with_for_update()
            .populate_existing()
            .one()
        )
