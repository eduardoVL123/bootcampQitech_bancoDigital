import hashlib
import json
from datetime import date, timedelta
from typing import Optional, Tuple

from sqlalchemy.exc import IntegrityError

from constants import (
    DOCUMENT_ATTEMPTS_PER_HOUR,
    DOCUMENT_ATTEMPTS_WINDOW_SECONDS,
    ONBOARDING_TIMEOUT_MINUTES,
    ORIGIN_BLOCK_SECONDS,
    REFUSALS_TO_BLOCK_ORIGIN,
    REFUSALS_WINDOW_SECONDS,
)
from controllers.base_controller import BaseController
from dtos import OnboardingDTO
from errors import (
    DocumentAlreadyRegistered,
    IdempotencyKeyReused,
    InvalidDate,
    InvalidDocumentNumber,
    OnboardingNotFound,
    TooManyAttempts,
    UnderageCustomer,
)
from models import CustomerType, Onboarding
from repositories import CustomerRepository, OnboardingRepository, RateLimitRepository
from utils.access_token import issue_access_token
from utils.clock import bank_today, now_utc
from utils.credential import Credential
from utils.document_number import is_valid_cnpj, is_valid_cpf

MINIMUM_AGE = 18

# O nome que o PostgreSQL dá ao UNIQUE(document_number) do database.sql. É
# por ele que se sabe que a gravação parou num documento já cadastrado.
DOCUMENT_NUMBER_CONSTRAINT = "customer_document_number_key"


class OnboardingController(BaseController):
    """As regras da abertura de conta (RFC 05). Aqui mora o "pode" e o "não pode"."""

    def __init__(self, fault_injection: frozenset = frozenset()) -> None:
        super().__init__(__name__)
        self.customer_repository = CustomerRepository(self.context)
        self.onboarding_repository = OnboardingRepository(self.context)
        self.rate_limit_repository = RateLimitRepository(available="redis_unavailable" not in fault_injection)

    def start(self, onboarding_data: dict, idempotency_key: str, origin: str) -> Tuple[dict, bool]:
        """Cadastra o cliente e começa a abertura em DRAFT, num COMMIT só.

        Devolve a resposta e se a abertura é nova (201) ou repetida (200).
        O formato já foi conferido pelo schema; aqui se confere o que só se
        sabe olhando o mundo: se o número existe, que dia é hoje, quem já
        está cadastrado. Toda recusa acontece antes de qualquer gravação.
        """
        # Quem já errou demais não passa nem da porta, nem com um pedido certo.
        seconds_blocked = self.rate_limit_repository.seconds_blocked(origin)
        if seconds_blocked > 0:
            raise TooManyAttempts(seconds_blocked)

        self._check_document_number(onboarding_data)
        birth_date = self._parse_past_date(onboarding_data, "birth_date")
        opening_date = self._parse_past_date(onboarding_data, "opening_date")

        if birth_date is not None and self._age_in_years(birth_date) < MINIMUM_AGE:
            raise UnderageCustomer(MINIMUM_AGE)

        request_hash = self._request_hash(onboarding_data)

        existing = self.onboarding_repository.get_by_idempotency_key(idempotency_key)
        if existing is not None:
            return self._repeat(existing, request_hash), False

        seconds_to_wait = self.rate_limit_repository.register_document_attempt(
            onboarding_data["document_number"],
            idempotency_key,
            DOCUMENT_ATTEMPTS_PER_HOUR,
            DOCUMENT_ATTEMPTS_WINDOW_SECONDS,
        )
        if seconds_to_wait > 0:
            raise TooManyAttempts(seconds_to_wait)

        now = now_utc()
        expires_at = now + timedelta(minutes=ONBOARDING_TIMEOUT_MINUTES)

        onboarding_key = OnboardingRepository.new_key()

        try:
            # O cliente guarda, no request_key, a abertura que o criou (bancos.md).
            customer = self.customer_repository.create(onboarding_data, onboarding_key, birth_date, opening_date)
            onboarding = self.onboarding_repository.create(
                onboarding_key, customer, onboarding_data, idempotency_key, request_hash, expires_at, now
            )
            self.session.flush()
        except IntegrityError as error:
            # Outro pedido gravou primeiro. Quem decide o que responder é o
            # UNIQUE que barrou, e nunca uma consulta feita antes de gravar.
            self.session.rollback()
            return self._resolve_conflict(error, idempotency_key, request_hash, origin), False

        onboarding_dto = OnboardingDTO.started(onboarding, issue_access_token(customer.customer_key, now))

        self.session.commit()
        return onboarding_dto, True

    def get(self, onboarding_key: str, credential: Credential) -> dict:
        """A abertura, para o dono dela ou para compliance. Para qualquer outra
        pessoa, responde igual a uma abertura que não existe (R8)."""
        onboarding = self.onboarding_repository.get_by_key(onboarding_key)

        if onboarding is None or not self._can_read(onboarding, credential):
            raise OnboardingNotFound()

        return OnboardingDTO.detail(onboarding)

    def _can_read(self, onboarding: Onboarding, credential: Credential) -> bool:
        if credential.is_compliance:
            return True

        return onboarding.customer is not None and credential.is_customer(onboarding.customer.customer_key)

    def _resolve_conflict(self, error: IntegrityError, idempotency_key: str, request_hash: str, origin: str) -> dict:
        constraint = getattr(getattr(error.orig, "diag", None), "constraint_name", None)

        # Um pedido com a mesma chave chegou junto e gravou primeiro: é a
        # mesma abertura, e quem perdeu recebe a do vencedor.
        existing = self.onboarding_repository.get_by_idempotency_key(idempotency_key)
        if existing is not None:
            return self._repeat(existing, request_hash)

        if constraint == DOCUMENT_NUMBER_CONSTRAINT:
            self._count_refusal(origin)
            raise DocumentAlreadyRegistered()

        raise error

    def _count_refusal(self, origin: str) -> None:
        """Documento que já é cliente conta como recusa da origem (decisão D5).
        Vinte em dez minutos é alguém testando CPFs para descobrir quem é cliente."""
        refusals = self.rate_limit_repository.count_refusal(origin, REFUSALS_WINDOW_SECONDS)

        if refusals >= REFUSALS_TO_BLOCK_ORIGIN:
            self.rate_limit_repository.block_origin(origin, ORIGIN_BLOCK_SECONDS)
            self.logger.warning("Origem bloqueada por excesso de recusas de documento ja cadastrado")

    def _repeat(self, onboarding: Onboarding, request_hash: str) -> dict:
        """A mesma chave de novo. Mesmo pedido: a mesma abertura, com uma
        credencial nova. Outro pedido: recusa, sem tocar em nada."""
        if onboarding.request_hash != request_hash:
            raise IdempotencyKeyReused()

        access_token = issue_access_token(onboarding.customer.customer_key, now_utc())
        return OnboardingDTO.started(onboarding, access_token)

    def _check_document_number(self, onboarding_data: dict) -> None:
        document_number = onboarding_data["document_number"]

        if onboarding_data["type"] == CustomerType.PF:
            if not is_valid_cpf(document_number):
                raise InvalidDocumentNumber("cpf_check_digit")
        elif not is_valid_cnpj(document_number):
            raise InvalidDocumentNumber("cnpj_check_digit")

    def _parse_past_date(self, onboarding_data: dict, field: str) -> Optional[date]:
        """Converte a data e recusa com 422 a que não existe ou está no futuro."""
        raw_date = onboarding_data.get(field)
        if raw_date is None:
            return None

        try:
            parsed = date.fromisoformat(raw_date)
        except ValueError:
            raise InvalidDate(field)

        if parsed > bank_today():
            raise InvalidDate(field)

        return parsed

    def _age_in_years(self, birth_date: date) -> int:
        today = bank_today()
        age = today.year - birth_date.year
        if (today.month, today.day) < (birth_date.month, birth_date.day):
            age = age - 1
        return age

    def _request_hash(self, onboarding_data: dict) -> str:
        """SHA-256 do pedido, com os campos em ordem fixa: o mesmo conteúdo
        dá o mesmo hash, e o banco guarda o hash, nunca os dados."""
        canonical = json.dumps(onboarding_data, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()
