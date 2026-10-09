from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import List, Optional

from connectors import AccountApiError, AccountConnector, BureauError, PepConnector, ReceitaConnector, SanctionsConnector
from constants import (
    ACCOUNT_RETRY_SECONDS,
    ANALYSIS_RETRY_MINUTES,
    BUREAU_WAIT_LIMIT_HOURS,
    PLD_MAX_INCOME,
    PLD_NEW_COMPANY_DAYS,
    PLD_NEW_COMPANY_MAX_INCOME,
    PLD_YOUNG_AGE,
    PLD_YOUNG_MAX_INCOME,
    WORKER_LEASE_SECONDS,
)
from controllers.base_controller import BaseController
from models import CustomerType, Onboarding, OnboardingCheck, OnboardingStatus, OnboardingStatusEvent
from repositories import OnboardingRepository
from utils.clock import age_in_years, bank_today, now_utc
from utils.person_name import normalize_name


# A situação que a Receita dá a quem está em dia, por tipo de cliente.
REGULAR_SITUATION = {CustomerType.PF: "REGULAR", CustomerType.PJ: "ATIVA"}
NOT_FOUND = "NAO_ENCONTRADO"

# Os motivos de recusa e de revisão (RFC 05, reason_codes).
RECEITA_NOT_FOUND = "RECEITA_NAO_ENCONTRADO"
RECEITA_DIVERGENT_DATA = "RECEITA_DADOS_DIVERGENTES"
SANCTIONS_MATCH = "SANCTIONS_MATCH"
PEP_MATCH = "PEP_MATCH"
PEP_SELF_DECLARED = "PEP_SELF_DECLARED"
INCOME_PROFILE = "INCOME_PROFILE"
BUREAU_UNAVAILABLE = "BUREAU_UNAVAILABLE"

RISK_LOW = "LOW"
RISK_MEDIUM = "MEDIUM"
RISK_HIGH = "HIGH"


@dataclass(frozen=True)
class Applicant:
    """O que a análise precisa saber, lido do banco e guardado só em memória
    enquanto os birôs respondem: nenhuma transação fica aberta nesse tempo."""

    onboarding_key: str
    customer_type: str
    name: str
    document_number: str
    birth_date: Optional[date]
    opening_date: Optional[date]
    monthly_income: int
    pep_self_declared: bool
    # Quando a abertura entrou na fila: as 24 horas de espera pelo birô contam daqui.
    queued_at: datetime


@dataclass(frozen=True)
class CheckResult:
    check_type: str
    result: str
    reason_code: Optional[str] = None
    provider_reference: Optional[str] = None


@dataclass(frozen=True)
class Verdict:
    """O que a análise decidiu: a etapa, as verificações, os motivos e o risco."""

    status: str
    checks: List[CheckResult]
    reason_codes: List[str]
    risk_level: Optional[str]


class KycController(BaseController):
    """A análise do KYC e do PLD, e a abertura da conta (RFC 05, Analisar o
    KYC no worker). Quem chama é o onboarding-worker.

    Cada etapa é um COMMIT curto, e nenhuma trava fica aberta durante os
    birôs nem durante a account-api: primeiro toma posse e grava, depois
    chama, e só então trava de novo para gravar o resultado.

    Com um birô sem resposta (RFC 05, Birô fora do ar), a análise para ali,
    sem gravar nada dela, e a abertura espera a próxima tentativa.
    """

    def __init__(self) -> None:
        super().__init__(__name__)
        self.onboarding_repository = OnboardingRepository(self.context)

    def analyze_next(self) -> bool:
        """Analisa a próxima abertura da fila e devolve se havia alguma."""
        applicant = self._take_for_analysis()
        if applicant is None:
            return False

        try:
            verdict = self._analyze(applicant)
        except BureauError:
            self._wait_for_bureau(applicant)
            return True

        self._record(applicant.onboarding_key, verdict)
        return True

    def open_next_account(self) -> bool:
        """Pede a conta da próxima abertura aprovada e devolve se havia alguma."""
        now = now_utc()
        onboarding = self.onboarding_repository.take_for_account(now)
        if onboarding is None:
            self.session.rollback()
            return False

        onboarding.lease_until = now + timedelta(seconds=WORKER_LEASE_SECONDS)
        onboarding_key = onboarding.onboarding_key
        customer_key = onboarding.customer_key
        customer_type = onboarding.customer.type.enumerator
        self.session.commit()

        try:
            account_key = AccountConnector().open_account(customer_key, customer_type, onboarding_key)
        except AccountApiError:
            self._retry_account_later(onboarding_key)
            return True

        self._activate(onboarding_key, account_key)
        return True

    def _take_for_analysis(self) -> Optional[Applicant]:
        """Toma posse da próxima abertura da fila: ANALYSIS, com o evento, e a
        posse por um tempo, num COMMIT curto. Devolve os dados que a análise usa."""
        now = now_utc()
        onboarding = self.onboarding_repository.take_for_analysis(now)
        if onboarding is None:
            self.session.rollback()
            return None

        # Uma abertura que volta para a fila porque a posse venceu já está em ANALYSIS.
        if onboarding.status.enumerator == OnboardingStatus.PENDING_KYC:
            self.onboarding_repository.change_status(onboarding, OnboardingStatus.ANALYSIS, OnboardingStatusEvent.WORKER, now)
        onboarding.lease_until = now + timedelta(seconds=WORKER_LEASE_SECONDS)

        customer = onboarding.customer
        applicant = Applicant(
            onboarding_key=onboarding.onboarding_key,
            customer_type=customer.type.enumerator,
            name=customer.name,
            document_number=customer.document_number,
            birth_date=customer.birth_date,
            opening_date=customer.opening_date,
            monthly_income=onboarding.declared_monthly_income,
            pep_self_declared=onboarding.pep_self_declared,
            queued_at=self._queued_at(onboarding),
        )

        self.session.commit()
        return applicant

    def _analyze(self, applicant: Applicant) -> Verdict:
        """Receita, sanções e PEP, nesta ordem, e depois as regras de PLD. Uma
        recusa encerra a análise ali: ninguém mais recebe o documento."""
        checks = []
        reasons = []

        receita = ReceitaConnector().consult_document(applicant.document_number)
        refusal = self._receita_refusal(applicant, receita["situacao"])
        if refusal is not None:
            checks.append(CheckResult(OnboardingCheck.RECEITA, OnboardingCheck.FAIL, refusal, receita.get("protocol")))
            return Verdict(OnboardingStatus.REJECTED, checks, [refusal], None)

        if self._same_data(applicant, receita):
            checks.append(CheckResult(OnboardingCheck.RECEITA, OnboardingCheck.PASS, None, receita.get("protocol")))
        else:
            checks.append(CheckResult(OnboardingCheck.RECEITA, OnboardingCheck.REVIEW, RECEITA_DIVERGENT_DATA, receita.get("protocol")))
            reasons.append(RECEITA_DIVERGENT_DATA)

        sanctions = SanctionsConnector().consult_person(applicant.document_number, applicant.name)
        if sanctions["match"] is True:
            checks.append(CheckResult(OnboardingCheck.SANCTIONS, OnboardingCheck.FAIL, SANCTIONS_MATCH, sanctions.get("protocol")))
            return Verdict(OnboardingStatus.REJECTED, checks, reasons + [SANCTIONS_MATCH], None)
        checks.append(CheckResult(OnboardingCheck.SANCTIONS, OnboardingCheck.PASS, None, sanctions.get("protocol")))

        pep = PepConnector().consult_document(applicant.document_number)
        pep_reason = None
        if pep["pep"] is True:
            pep_reason = PEP_MATCH
        elif applicant.pep_self_declared:
            pep_reason = PEP_SELF_DECLARED

        if pep_reason is None:
            checks.append(CheckResult(OnboardingCheck.PEP, OnboardingCheck.PASS, None, pep.get("protocol")))
        else:
            checks.append(CheckResult(OnboardingCheck.PEP, OnboardingCheck.REVIEW, pep_reason, pep.get("protocol")))
            reasons.append(pep_reason)

        income_rules = self._income_rules_triggered(applicant)
        if income_rules == 0:
            checks.append(CheckResult(OnboardingCheck.PLD, OnboardingCheck.PASS))
        else:
            checks.append(CheckResult(OnboardingCheck.PLD, OnboardingCheck.REVIEW, INCOME_PROFILE))
            reasons.append(INCOME_PROFILE)

        status = OnboardingStatus.MANUAL_REVIEW if reasons else OnboardingStatus.APPROVED
        return Verdict(status, checks, reasons, self._risk_level(pep_reason is not None, income_rules))

    def _receita_refusal(self, applicant: Applicant, situation: str) -> Optional[str]:
        """O motivo da recusa, ou None se a situação é regular."""
        if situation == REGULAR_SITUATION[applicant.customer_type]:
            return None

        if situation == NOT_FOUND:
            return RECEITA_NOT_FOUND

        if applicant.customer_type == CustomerType.PJ:
            return f"RECEITA_CNPJ_{situation}"

        return f"RECEITA_{situation}"

    def _same_data(self, applicant: Applicant, receita: dict) -> bool:
        """Nome e data iguais aos da Receita. O nome é comparado sem acento, sem
        diferença de maiúscula e sem espaço sobrando (decisão D13)."""
        if applicant.customer_type == CustomerType.PF:
            expected_date = applicant.birth_date.isoformat()
            receita_date = receita.get("birth_date")
        else:
            expected_date = applicant.opening_date.isoformat()
            receita_date = receita.get("opening_date")

        same_name = normalize_name(receita.get("name", "")) == normalize_name(applicant.name)
        return same_name and receita_date == expected_date

    def _income_rules_triggered(self, applicant: Applicant) -> int:
        """Quantas regras de renda do PLD dispararam (RFC 05, Regras de PLD)."""
        income = applicant.monthly_income
        triggered = 0

        if applicant.customer_type == CustomerType.PF:
            if age_in_years(applicant.birth_date) < PLD_YOUNG_AGE and income > PLD_YOUNG_MAX_INCOME:
                triggered = triggered + 1
            if income > PLD_MAX_INCOME:
                triggered = triggered + 1
        else:
            company_age_days = (bank_today() - applicant.opening_date).days
            if company_age_days < PLD_NEW_COMPANY_DAYS and income > PLD_NEW_COMPANY_MAX_INCOME:
                triggered = triggered + 1

        return triggered

    def _risk_level(self, is_pep: bool, income_rules: int) -> str:
        """Alto para PEP ou duas regras ou mais; médio para uma regra de renda; baixo sem nenhuma."""
        if is_pep or income_rules >= 2:
            return RISK_HIGH

        if income_rules == 1:
            return RISK_MEDIUM

        return RISK_LOW

    def _record(self, onboarding_key: str, verdict: Verdict) -> None:
        """Grava as verificações, os motivos, o risco e a nova etapa, num COMMIT."""
        now = now_utc()
        onboarding = self.onboarding_repository.get_by_key_for_update(onboarding_key)

        # A posse venceu no meio e outra réplica já decidiu: esta análise é descartada.
        if onboarding.status.enumerator != OnboardingStatus.ANALYSIS:
            self.session.rollback()
            return

        for check in verdict.checks:
            self.onboarding_repository.add_check(
                onboarding, check.check_type, check.result, check.reason_code, check.provider_reference, now
            )

        onboarding.reason_codes = ",".join(verdict.reason_codes) or None
        onboarding.risk_level = verdict.risk_level
        onboarding.lease_until = None
        onboarding.next_attempt_at = None
        onboarding.updated_at = now
        self.onboarding_repository.change_status(onboarding, verdict.status, OnboardingStatusEvent.WORKER, now)
        self.session.commit()

    def _queued_at(self, onboarding: Onboarding) -> datetime:
        """Quando a abertura entrou na fila pela última vez: o RG completo ou a
        retentativa em lote, que recomeça a contagem das 24 horas (decisão D28)."""
        queued = [event for event in onboarding.status_events if event.status.enumerator == OnboardingStatus.PENDING_KYC]
        return queued[-1].event_datetime

    def _wait_for_bureau(self, applicant: Applicant) -> None:
        """Um birô não respondeu: na dúvida, não aprova nem recusa, e nada da
        análise é gravado (decisão D28). A abertura espera em ANALYSIS, sem
        posse, e tenta de novo em 1, 5, 15 e 60 minutos, e depois de hora em
        hora. Com 24 horas na fila, a decisão passa a compliance."""
        now = now_utc()
        onboarding = self.onboarding_repository.get_by_key_for_update(applicant.onboarding_key)

        # A posse venceu no meio e outra réplica já decidiu: nada a fazer aqui.
        if onboarding.status.enumerator != OnboardingStatus.ANALYSIS:
            self.session.rollback()
            return

        onboarding.analysis_attempts = onboarding.analysis_attempts + 1
        onboarding.lease_until = None
        onboarding.updated_at = now

        if now - applicant.queued_at >= timedelta(hours=BUREAU_WAIT_LIMIT_HOURS):
            onboarding.next_attempt_at = None
            onboarding.reason_codes = BUREAU_UNAVAILABLE
            self.onboarding_repository.change_status(onboarding, OnboardingStatus.MANUAL_REVIEW, OnboardingStatusEvent.WORKER, now)
            self.logger.warning("Biro sem resposta ha 24 horas: a abertura vai para compliance")
        else:
            delay = self._retry_delay(onboarding.analysis_attempts)
            onboarding.next_attempt_at = now + delay
            self.logger.warning(f"Biro sem resposta: nova tentativa da abertura em {delay}")

        self.session.commit()

    def _retry_delay(self, attempts: int) -> timedelta:
        """1, 5, 15 e 60 minutos, e depois de hora em hora."""
        position = min(attempts, len(ANALYSIS_RETRY_MINUTES)) - 1
        return timedelta(minutes=ANALYSIS_RETRY_MINUTES[position])

    def _retry_account_later(self, onboarding_key: str) -> None:
        """A account-api não respondeu: a abertura espera em APPROVED e o
        worker tenta de novo depois de ACCOUNT_RETRY_SECONDS, com a mesma chave."""
        now = now_utc()
        onboarding = self.onboarding_repository.get_by_key_for_update(onboarding_key)
        onboarding.next_attempt_at = now + timedelta(seconds=ACCOUNT_RETRY_SECONDS)
        onboarding.lease_until = None
        self.session.commit()

    def _activate(self, onboarding_key: str, account_key: str) -> None:
        """A conta existe: a abertura fica ACTIVE com a account_key."""
        now = now_utc()
        onboarding = self.onboarding_repository.get_by_key_for_update(onboarding_key)

        if onboarding.status.enumerator != OnboardingStatus.APPROVED:
            self.session.rollback()
            return

        onboarding.account_key = account_key
        onboarding.lease_until = None
        onboarding.next_attempt_at = None
        onboarding.updated_at = now
        self.onboarding_repository.change_status(onboarding, OnboardingStatus.ACTIVE, OnboardingStatusEvent.WORKER, now)
        self.session.commit()
