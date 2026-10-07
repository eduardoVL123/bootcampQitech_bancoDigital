import requests

from connectors.rest_connector import RestConnector
from constants import BUREAU_TIMEOUT_SECONDS, INTERNAL_TOKEN, PEP_URL, RECEITA_URL, SANCTIONS_URL


class BureauError(Exception):
    """O birô não respondeu como o contrato diz (timeout, conexão recusada ou
    status diferente de 200). Quem decide o que fazer é o controller."""


class BureauConnector(RestConnector):
    """O que os três birôs têm em comum (plano de testes, seção 2.2): um POST
    com o documento, timeout de 2 s e a resposta em JSON. Os dados pessoais
    vão só no corpo, nunca no endereço nem no log."""

    def __init__(self, class_name: str, base_url: str, endpoint: str, answer_field: str) -> None:
        super().__init__(class_name, base_url, BUREAU_TIMEOUT_SECONDS, INTERNAL_TOKEN)
        self.endpoint = endpoint
        # O campo que o contrato promete na resposta. Sem ele, não há resposta.
        self.answer_field = answer_field

    def consult(self, payload: dict) -> dict:
        try:
            response = self.send(self.endpoint, "POST", payload)
        except requests.exceptions.RequestException as error:
            self.logger.warning(f"Biro sem resposta ({type(error).__name__}) em {self.endpoint}")
            raise BureauError() from error

        if response.status != 200 or not isinstance(response.json, dict) or self.answer_field not in response.json:
            self.logger.warning(f"Biro respondeu {response.status} em {self.endpoint}, fora do contrato")
            raise BureauError()

        return response.json


class ReceitaConnector(BureauConnector):
    def __init__(self) -> None:
        super().__init__(__name__, RECEITA_URL, "/receita/v1/consulta", "situacao")

    def consult_document(self, document_number: str) -> dict:
        """A situação do CPF ou CNPJ, com nome, data e protocolo."""
        return self.consult({"document_number": document_number})


class SanctionsConnector(BureauConnector):
    def __init__(self) -> None:
        super().__init__(__name__, SANCTIONS_URL, "/sancoes/v1/consulta", "match")

    def consult_person(self, document_number: str, name: str) -> dict:
        """Se o nome ou o documento estão numa lista de sanções (match)."""
        return self.consult({"document_number": document_number, "name": name})


class PepConnector(BureauConnector):
    def __init__(self) -> None:
        super().__init__(__name__, PEP_URL, "/pep/v1/consulta", "pep")

    def consult_document(self, document_number: str) -> dict:
        """Se é pessoa exposta politicamente (pep). Na PJ, pelo CNPJ (decisão D14)."""
        return self.consult({"document_number": document_number})
