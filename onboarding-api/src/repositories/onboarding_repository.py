from datetime import datetime
from typing import Optional, Tuple
from uuid import uuid4

from sqlalchemy import and_, func, or_, tuple_

from database import Context
from models import Customer, Onboarding, OnboardingCheck, OnboardingDocument, OnboardingStatus, OnboardingStatusEvent


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

    def change_status(
        self,
        onboarding: Onboarding,
        enumerator: str,
        actor: str,
        now: datetime,
        justification: Optional[str] = None,
        decided_by: Optional[str] = None,
    ) -> None:
        """Muda a etapa e grava o evento junto: as duas coisas entram no mesmo
        COMMIT. Quando quem muda é compliance, o evento guarda também a
        justificativa e quem decidiu."""
        status = self.get_status(enumerator)
        onboarding.status = status

        event = OnboardingStatusEvent()
        event.status = status
        event.actor = actor
        event.justification = justification
        event.decided_by = decided_by
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

    def take_for_analysis(self, now: datetime) -> Optional[Onboarding]:
        """A próxima abertura da fila da análise, travada até o COMMIT, ou None.

        Na fila: PENDING_KYC na hora de tentar; ANALYSIS sem posse, na hora da
        nova tentativa depois de um birô sem resposta; ou ANALYSIS com a posse
        vencida (o worker que a pegou caiu no meio). SKIP LOCKED: duas réplicas
        nunca pegam a mesma. O `of` trava só a linha da abertura: sem ele, o
        Postgres travaria também a linha da etapa na onboarding_status, e a
        segunda réplica pularia a fila inteira."""
        waiting = and_(
            OnboardingStatus.enumerator == OnboardingStatus.PENDING_KYC,
            or_(Onboarding.next_attempt_at.is_(None), Onboarding.next_attempt_at <= now),
        )
        retry_due = and_(
            OnboardingStatus.enumerator == OnboardingStatus.ANALYSIS,
            Onboarding.lease_until.is_(None),
            Onboarding.next_attempt_at <= now,
        )
        abandoned = and_(OnboardingStatus.enumerator == OnboardingStatus.ANALYSIS, Onboarding.lease_until < now)
        return self._take(or_(waiting, retry_due, abandoned))

    def queue_page(self, status: str, reason_code: Optional[str], limit: int, offset: int) -> list:
        """Uma página da fila de compliance, da abertura mais antiga para a mais
        nova, com um item a mais para saber se há próxima página. Com
        `reason_code`, só as que têm esse motivo entre os delas: os motivos
        ficam separados por vírgula, e a vírgula nas duas pontas faz achar o
        motivo inteiro, e nunca um pedaço de outro. O strpos procura o texto
        exato (no LIKE, o _ dos motivos valeria qualquer letra)."""
        query = (
            self.session.query(Onboarding)
            .join(OnboardingStatus, Onboarding.status_id == OnboardingStatus.id)
            .filter(OnboardingStatus.enumerator == status)
        )

        if reason_code is not None:
            query = query.filter(func.strpos(func.concat(",", Onboarding.reason_codes, ","), f",{reason_code},") > 0)

        return query.order_by(Onboarding.id).limit(limit + 1).offset(offset).all()

    def in_review_only_for(self, reason_code: str, onboarding_keys: Optional[list]) -> list:
        """As aberturas em MANUAL_REVIEW só por este motivo, travadas até o
        COMMIT, em ordem de id: duas retentativas juntas travam na mesma ordem
        e nunca uma esperando a outra. Com `onboarding_keys`, só entre elas."""
        query = (
            self.session.query(Onboarding)
            .join(OnboardingStatus, Onboarding.status_id == OnboardingStatus.id)
            .filter(OnboardingStatus.enumerator == OnboardingStatus.MANUAL_REVIEW, Onboarding.reason_codes == reason_code)
        )

        if onboarding_keys is not None:
            query = query.filter(Onboarding.onboarding_key.in_(onboarding_keys))

        return query.order_by(Onboarding.id).with_for_update(of=Onboarding).populate_existing().all()

    def take_for_account(self, now: datetime) -> Optional[Onboarding]:
        """A próxima abertura APPROVED que espera a conta, travada até o COMMIT,
        ou None: na hora de tentar de novo e sem outro worker com a posse."""
        due = and_(
            OnboardingStatus.enumerator == OnboardingStatus.APPROVED,
            or_(Onboarding.next_attempt_at.is_(None), Onboarding.next_attempt_at <= now),
            or_(Onboarding.lease_until.is_(None), Onboarding.lease_until < now),
        )
        return self._take(due)

    def _take(self, condition) -> Optional[Onboarding]:
        return (
            self.session.query(Onboarding)
            .join(OnboardingStatus, Onboarding.status_id == OnboardingStatus.id)
            .filter(condition)
            .order_by(Onboarding.id)
            .with_for_update(skip_locked=True, of=Onboarding)
            .populate_existing()
            .first()
        )

    def add_check(
        self,
        onboarding: Onboarding,
        check_type: str,
        result: str,
        reason_code: Optional[str],
        provider_reference: Optional[str],
        consulted_at: datetime,
    ) -> None:
        """O resultado de uma verificação, sem os dados consultados."""
        check = OnboardingCheck()
        check.check_type = check_type
        check.result = result
        check.reason_code = reason_code
        check.provider_reference = provider_reference
        check.consulted_at = consulted_at
        onboarding.checks.append(check)

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
