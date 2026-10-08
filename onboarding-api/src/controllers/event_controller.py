from datetime import timedelta

from connectors import WebhookConnector
from constants import EVENT_LEASE_SECONDS, EVENT_RETRY_MINUTES
from controllers.base_controller import BaseController
from dtos import EventDTO
from models import OnboardingOutbox
from repositories import OutboxRepository
from utils.clock import now_utc


class EventController(BaseController):
    """A entrega dos eventos da outbox à webhook-api (RFC 05, Eventos). Quem
    chama é o onboarding-worker, a cada segundo.

    Como na análise do KYC, cada passo é um COMMIT curto, e nenhuma trava fica
    aberta durante a chamada: primeiro toma posse do evento, depois chama, e
    só então trava de novo para gravar o resultado.
    """

    def __init__(self) -> None:
        super().__init__(__name__)
        self.outbox_repository = OutboxRepository(self.context)
        self.webhook_connector = WebhookConnector()

    def deliver_next(self) -> bool:
        """Entrega o próximo evento e devolve se havia algum."""
        now = now_utc()
        outbox = self.outbox_repository.take_next_due(now)
        if outbox is None:
            self.session.rollback()
            return False

        # A posse: se o worker cair no meio, ela vence, e outra réplica entrega
        # de novo, com o mesmo event_id. A webhook-api descarta o repetido.
        outbox.next_attempt_at = now + timedelta(seconds=EVENT_LEASE_SECONDS)
        event_id = outbox.event_id
        envelope = EventDTO.envelope(outbox)
        self.session.commit()

        delivered = self.webhook_connector.send_event(envelope)

        now = now_utc()
        outbox = self.outbox_repository.get_for_update(event_id)
        if delivered:
            outbox.status = OnboardingOutbox.SENT
            outbox.sent_at = now
            outbox.next_attempt_at = None
        else:
            outbox.attempts = outbox.attempts + 1
            outbox.next_attempt_at = now + self._retry_delay(outbox.attempts)

        self.session.commit()
        return True

    def _retry_delay(self, attempts: int) -> timedelta:
        """1, 5, 15 e 60 minutos, e depois a cada 6 horas."""
        position = min(attempts, len(EVENT_RETRY_MINUTES)) - 1
        return timedelta(minutes=EVENT_RETRY_MINUTES[position])
