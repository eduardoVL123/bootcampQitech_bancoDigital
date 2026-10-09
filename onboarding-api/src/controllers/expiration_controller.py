from datetime import datetime

from connectors import BucketConnector, BucketError
from constants import EXPIRATION_BATCH_SIZE
from controllers.base_controller import BaseController
from models import OnboardingStatus, OnboardingStatusEvent
from repositories import OnboardingRepository
from utils.clock import now_utc


class ExpirationController(BaseController):
    """O vencimento das aberturas paradas (RFC 05, Prazo de 20 minutos).

    Quem chama é o onboarding-worker, a cada minuto. Diferente dos
    controllers da API, este dá vários COMMIT curtos por passada, um por
    etapa de cada abertura: nenhuma trava fica aberta durante a chamada ao bucket.
    """

    def __init__(self) -> None:
        super().__init__(__name__)
        self.onboarding_repository = OnboardingRepository(self.context)
        self.bucket_connector = BucketConnector()

    def expire_overdue(self) -> int:
        """Vence as aberturas que passaram do prazo e devolve quantas tiveram os dados apagados.

        Se o bucket falha numa delas, ela fica EXPIRED com o cadastro, e a
        próxima passada tenta de novo. Nesta passada, cada uma é tentada uma
        vez só: cada lote começa depois do último, e a passada termina quando
        não há mais nenhuma.
        """
        now = now_utc()
        after = None
        erased = 0

        while True:
            rows = self.onboarding_repository.overdue(now, after, EXPIRATION_BATCH_SIZE)
            if not rows:
                return erased

            for row in rows:
                if self._expire(row.onboarding_key, now):
                    erased = erased + 1

            last = rows[-1]
            after = (last.expires_at, last.id)

    def _expire(self, onboarding_key: str, now: datetime) -> bool:
        """Três passos, nesta ordem: marca EXPIRED, apaga as fotos e só então
        apaga o cadastro. Marcar primeiro fecha a porta: um envio do RG que
        chegue no meio encontra a abertura vencida e recebe 410."""
        if not self._mark_expired(onboarding_key, now):
            return False

        try:
            self.bucket_connector.delete_prefix(f"rg/{onboarding_key}/")
        except BucketError:
            self.logger.warning("Fotos da abertura vencida nao apagadas: ela fica para a proxima passada")
            return False

        onboarding = self.onboarding_repository.get_by_key_for_update(onboarding_key)

        # Outro worker chegou primeiro e já apagou.
        if onboarding.customer_id is None:
            self.session.rollback()
            return False

        self.onboarding_repository.erase_personal_data(onboarding, now)
        self.session.commit()
        return True

    def _mark_expired(self, onboarding_key: str, now: datetime) -> bool:
        """Marca a abertura como EXPIRED, com o evento, num COMMIT curto.
        Devolve se ela ainda precisa ter os dados apagados."""
        onboarding = self.onboarding_repository.get_by_key_for_update_skip_locked(onboarding_key)

        # Um envio do RG está com ela agora: fica para a próxima passada.
        if onboarding is None:
            self.session.rollback()
            return False

        status = onboarding.status.enumerator

        if status == OnboardingStatus.DRAFT and onboarding.expires_at <= now:
            self.onboarding_repository.change_status(onboarding, OnboardingStatus.EXPIRED, OnboardingStatusEvent.WORKER, now)
        elif status != OnboardingStatus.EXPIRED or onboarding.customer_id is None:
            # Mudou desde a busca: o RG ficou completo a tempo, ou outro worker já apagou.
            self.session.rollback()
            return False

        self.session.commit()
        return True
