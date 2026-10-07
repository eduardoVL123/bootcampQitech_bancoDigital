import hashlib
import json
from datetime import date, timedelta
from typing import List, NamedTuple, Optional, Tuple
from uuid import uuid4

from sqlalchemy.exc import IntegrityError

from connectors import BucketConnector, BucketError
from constants import (
    DOCUMENT_ATTEMPTS_PER_HOUR,
    DOCUMENT_ATTEMPTS_WINDOW_SECONDS,
    MAX_DOCUMENT_BYTES,
    ONBOARDING_TIMEOUT_MINUTES,
    ORIGIN_BLOCK_SECONDS,
    REFUSALS_TO_BLOCK_ORIGIN,
    REFUSALS_WINDOW_SECONDS,
)
from controllers.base_controller import BaseController
from dtos import OnboardingDTO
from errors import (
    BucketUnavailable,
    DocumentAlreadyRegistered,
    FileTooLarge,
    IdempotencyKeyReused,
    InvalidDate,
    InvalidDocumentNumber,
    MissingRequiredFields,
    OnboardingNotDraft,
    OnboardingNotFound,
    RepeatedDocumentSide,
    TooManyAttempts,
    UnderageCustomer,
    UnsupportedFileType,
)
from models import CustomerType, Onboarding, OnboardingDocument, OnboardingStatus, OnboardingStatusEvent
from repositories import CustomerRepository, OnboardingRepository, RateLimitRepository
from utils.access_token import issue_access_token
from utils.clock import bank_today, now_utc
from utils.credential import Credential
from utils.document_number import is_valid_cnpj, is_valid_cpf
from utils.image_type import detect_image_type

MINIMUM_AGE = 18

# O nome que o PostgreSQL dá ao UNIQUE(document_number) do database.sql. É
# por ele que se sabe que a gravação parou num documento já cadastrado.
DOCUMENT_NUMBER_CONSTRAINT = "customer_document_number_key"

# O UNIQUE(onboarding_id, side): o mesmo lado do RG duas vezes na mesma abertura.
DOCUMENT_SIDE_CONSTRAINT = "onboarding_document_onboarding_id_side_key"

NO_DOCUMENT_ERROR = {
    "field": "front",
    "rule": "required",
    "message": "Mande a frente e o verso (front e back), ou uma imagem com os dois lados (both).",
}


class DocumentImage(NamedTuple):
    """Uma imagem do RG já conferida: o campo do envio, o lado, os bytes e o tipo que os bytes dizem."""

    field: str
    side: str
    content: bytes
    content_type: str


class OnboardingController(BaseController):
    """As regras da abertura de conta (RFC 05). Aqui mora o "pode" e o "não pode"."""

    def __init__(self, fault_injection: frozenset = frozenset()) -> None:
        super().__init__(__name__)
        self.customer_repository = CustomerRepository(self.context)
        self.onboarding_repository = OnboardingRepository(self.context)
        self.rate_limit_repository = RateLimitRepository(available="redis_unavailable" not in fault_injection)
        self.bucket_connector = BucketConnector(available="bucket_unavailable" not in fault_injection)

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

    def send_document(self, onboarding_key: str, credential: Credential, files: List[Tuple[str, bytes]]) -> Tuple[dict, bool]:
        """Guarda as imagens do RG (RFC 05, Mandar o RG).

        Devolve a resposta e se o RG ficou completo (202) ou se ainda falta
        um lado (200). Tudo é conferido antes de gastar o bucket. Depois,
        primeiro o bucket e só então o banco: o pior caso é uma foto sem
        linha, invisível, e nunca uma linha apontando para uma foto que não existe.
        """
        onboarding = self.onboarding_repository.get_by_key(onboarding_key)

        # Só o dono manda o RG. Compliance lê a abertura, mas não envia
        # documento. Para qualquer outro, a abertura não existe (R8).
        if onboarding is None or not self._is_owner(onboarding, credential):
            raise OnboardingNotFound()

        self._check_waiting_for_document(onboarding)
        images = self._check_images(files)
        self._check_sides(onboarding, images)

        # Nada foi gravado até aqui. Encerrar a leitura devolve a conexão ao
        # pool e garante que nenhuma trava fica aberta durante a chamada ao bucket.
        self.session.rollback()

        object_keys = self._store_in_bucket(onboarding_key, images)

        # Agora a trava: dois envios da mesma abertura passam daqui um de cada
        # vez, e o segundo confere de novo, já vendo o que o primeiro gravou.
        # Sem ela, a frente e o verso chegando juntos veriam só o próprio lado,
        # e a abertura ficaria presa em DRAFT com o RG completo.
        onboarding = self.onboarding_repository.get_by_key_for_update(onboarding_key)
        self._check_waiting_for_document(onboarding)
        self._check_sides(onboarding, images)

        now = now_utc()
        for image, object_key in zip(images, object_keys):
            self.onboarding_repository.add_document(
                onboarding, image.side, object_key, image.content_type, len(image.content), now
            )

        try:
            self.session.flush()
        except IntegrityError as error:
            # O UNIQUE(onboarding_id, side) é a garantia final, se a trava faltar.
            # Qualquer outra restrição que barrar é defeito, e não lado repetido.
            self.session.rollback()
            if self._constraint_name(error) == DOCUMENT_SIDE_CONSTRAINT:
                raise RepeatedDocumentSide(images[0].field)
            raise

        sides_shown = OnboardingDocument.sides_shown(document.side for document in onboarding.documents)
        complete = sides_shown == OnboardingDocument.COMPLETE_RG

        # RG completo: a parte da pessoa acabou, e a abertura entra na fila da análise.
        if complete:
            self.onboarding_repository.change_status(
                onboarding, OnboardingStatus.PENDING_KYC, OnboardingStatusEvent.API, now
            )

        onboarding_dto = OnboardingDTO.document_received(onboarding)

        self.session.commit()
        return onboarding_dto, complete

    def get_document_url(self, onboarding_key: str, side: str, credential: Credential) -> str:
        """Devolve o link assinado (presigned URL) de 5 minutos do S3 para a imagem,
        apenas para o time de compliance."""
        if not credential.is_compliance:
            raise OnboardingNotFound()
            
        onboarding = self.onboarding_repository.get_by_key(onboarding_key)
        if onboarding is None:
            raise OnboardingNotFound()
            
        document = next((doc for doc in onboarding.documents if doc.side == side.upper()), None)
        if not document:
            from errors import DocumentNotFound
            raise DocumentNotFound()
            
        return self.bucket_connector.get_presigned_url(document.object_key, 300)

    def _check_waiting_for_document(self, onboarding: Onboarding) -> None:
        if onboarding.status.enumerator != OnboardingStatus.DRAFT:
            raise OnboardingNotDraft()

    def _check_images(self, files: List[Tuple[str, bytes]]) -> List[DocumentImage]:
        """Pelo menos uma imagem, cada uma com até 5 MB e JPEG ou PNG pelos primeiros bytes."""
        if not files:
            raise MissingRequiredFields([NO_DOCUMENT_ERROR])

        images = []
        for field, content in files:
            if len(content) > MAX_DOCUMENT_BYTES:
                raise FileTooLarge(field, MAX_DOCUMENT_BYTES // (1024 * 1024))

            content_type = detect_image_type(content)
            if content_type is None:
                raise UnsupportedFileType(field)

            images.append(DocumentImage(field, field.upper(), content, content_type))

        return images

    def _check_sides(self, onboarding: Onboarding, images: List[DocumentImage]) -> None:
        """Cada lado do RG chega uma vez só, contando os já guardados e os do
        mesmo envio. A imagem BOTH mostra os dois lados. Como o RG só tem dois
        lados, uma terceira imagem sempre repete um, e assim a mesma conferência
        garante o máximo de duas imagens."""
        shown = OnboardingDocument.sides_shown(document.side for document in onboarding.documents)

        for image in images:
            image_sides = OnboardingDocument.SIDES_SHOWN[image.side]
            if shown & image_sides:
                raise RepeatedDocumentSide(image.field)
            shown = shown | image_sides

    def _store_in_bucket(self, onboarding_key: str, images: List[DocumentImage]) -> List[str]:
        """Manda cada imagem para o bucket e devolve os caminhos. O caminho tem
        a chave da abertura e nenhum dado pessoal, e é novo a cada envio: dois
        envios juntos nunca escrevem um por cima do outro."""
        object_keys = []

        for image in images:
            object_key = f"rg/{onboarding_key}/{image.field}-{uuid4()}"
            try:
                self.bucket_connector.put_object(object_key, image.content, image.content_type)
            except BucketError:
                raise BucketUnavailable()
            object_keys.append(object_key)

        return object_keys

    def _can_read(self, onboarding: Onboarding, credential: Credential) -> bool:
        if credential.is_compliance:
            return True

        return self._is_owner(onboarding, credential)

    def _is_owner(self, onboarding: Onboarding, credential: Credential) -> bool:
        return onboarding.customer is not None and credential.is_customer(onboarding.customer.customer_key)

    def _constraint_name(self, error: IntegrityError) -> Optional[str]:
        return getattr(getattr(error.orig, "diag", None), "constraint_name", None)

    def _resolve_conflict(self, error: IntegrityError, idempotency_key: str, request_hash: str, origin: str) -> dict:
        constraint = self._constraint_name(error)

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
