import random
import time

import requests

from connectors.circuit_breaker import CircuitBreaker
from connectors.rest_connector import RestConnector
from constants import (
    BUREAU_RETRY_DELAYS_SECONDS,
    BUREAU_RETRY_JITTER,
    BUREAU_TIMEOUT_SECONDS,
    INTERNAL_TOKEN,
    PEP_URL,
    RECEITA_URL,
    SANCTIONS_URL,
)


class BureauError(Exception):
    """O birô não deu uma resposta do contrato: ficou sem responder, o circuito
    estava aberto, ou a resposta veio fora do contrato. Quem decide o que fazer
    é o controller: na dúvida, não aprova nem recusa."""


class BureauConnector(RestConnector):
    """O que os três birôs têm em comum (RFC 05, Contrato dos birôs): um POST
    com o documento, timeout de 2 s, 2 retentativas, circuit breaker e a
    resposta em JSON. Os dados pessoais vão só no corpo, nunca no endereço
    nem no log."""

    def __init__(self, class_name: str, base_url: str, name: str, endpoint: str, answer_field: str) -> None:
        super().__init__(class_name, base_url, BUREAU_TIMEOUT_SECONDS, INTERNAL_TOKEN)
        self.name = name
        self.endpoint = endpoint
        # A chamada de teste da retentativa em lote (decisão D29).
        self.health_endpoint = f"/{name}/v1/health"
        # O campo que o contrato promete na resposta. Sem ele, não há resposta.
        self.answer_field = answer_field
        self.circuit = CircuitBreaker(name)

    def consult(self, payload: dict) -> dict:
        """Devolve a resposta do contrato, ou levanta BureauError."""
        if not self.circuit.allows_call():
            self.logger.warning(f"Circuito do biro {self.name} aberto: a consulta fica para a proxima tentativa")
            raise BureauError()

        response = self._send_with_retries(payload)
        if response is None:
            self.circuit.record_failure()
            raise BureauError()

        if response.status != 200 or not isinstance(response.json, dict) or self.answer_field not in response.json:
            # O birô respondeu, mas a resposta não diz nada: não abre nem fecha
            # o circuito, e repetir não mudaria a resposta (decisão D15).
            self.logger.warning(f"Biro respondeu {response.status} em {self.endpoint}, fora do contrato")
            raise BureauError()

        self.circuit.record_success()
        return response.json

    def is_up(self) -> bool:
        """A chamada de teste: uma só, fora do circuito, esperando 200."""
        try:
            response = self.send(self.health_endpoint, "GET")
        except requests.exceptions.RequestException as error:
            self.logger.warning(f"Biro sem resposta ({type(error).__name__}) em {self.health_endpoint}")
            return False

        if response.status != 200:
            self.logger.warning(f"Biro respondeu {response.status} em {self.health_endpoint}")
            return False

        return True

    def _send_with_retries(self, payload: dict):
        """Uma chamada e até 2 retentativas, só quando a chamada falha (timeout,
        conexão recusada ou 5xx). Cada espera ganha uma variação aleatória,
        para as réplicas não voltarem todas juntas. Devolve a primeira
        resposta que não é falha, ou None."""
        for attempt in range(len(BUREAU_RETRY_DELAYS_SECONDS) + 1):
            if attempt > 0:
                delay = BUREAU_RETRY_DELAYS_SECONDS[attempt - 1]
                time.sleep(delay * (1 + random.uniform(0, BUREAU_RETRY_JITTER)))

            try:
                response = self.send(self.endpoint, "POST", payload)
            except requests.exceptions.RequestException as error:
                self.logger.warning(f"Biro sem resposta ({type(error).__name__}) em {self.endpoint}")
                continue

            if response.status < 500:
                return response

            self.logger.warning(f"Biro respondeu {response.status} em {self.endpoint}")

        return None


class ReceitaConnector(BureauConnector):
    def __init__(self) -> None:
        super().__init__(__name__, RECEITA_URL, "receita", "/receita/v1/consulta", "situacao")

    def consult_document(self, document_number: str) -> dict:
        """A situação do CPF ou CNPJ, com nome, data e protocolo."""
        return self.consult({"document_number": document_number})


class SanctionsConnector(BureauConnector):
    def __init__(self) -> None:
        super().__init__(__name__, SANCTIONS_URL, "sancoes", "/sancoes/v1/consulta", "match")

    def consult_person(self, document_number: str, name: str) -> dict:
        """Se o nome ou o documento estão numa lista de sanções (match)."""
        return self.consult({"document_number": document_number, "name": name})


class PepConnector(BureauConnector):
    def __init__(self) -> None:
        super().__init__(__name__, PEP_URL, "pep", "/pep/v1/consulta", "pep")

    def consult_document(self, document_number: str) -> dict:
        """Se é pessoa exposta politicamente (pep). Na PJ, pelo CNPJ (decisão D14)."""
        return self.consult({"document_number": document_number})
