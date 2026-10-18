from sqlalchemy import text

from database import Context


class ReputationRepository:
    """O mock de reputacao externa, o mock de cadastro de CNPJ e as ancoras da rede.

    O mock de reputacao imita o `destination_statistics` da API Pix da QI. Ele
    fornece evidencias; quem decide e o motor (controllers/rules/reputacao_externa.py).
    O de cadastro faz as vezes dos dados abertos do CNPJ da Receita: a atividade
    principal (CNAE) de quem recebe.
    """

    def __init__(self, context: Context) -> None:
        self.session = context.db_session

    def fixtures(self, document: str) -> list:
        return self.session.execute(text(
            "SELECT document, scope, statistics, entity_role, evidence_id, available_from, expires_at, "
            "fixture_version FROM reputation_fixture WHERE document = :doc ORDER BY available_from"
        ), {"doc": document}).all()

    def company(self, document: str):
        """O cadastro do CNPJ no mock (a atividade principal), ou None."""
        return self.session.execute(text(
            "SELECT document, cnae, fixture_version FROM cnpj_fixture WHERE document = :doc"
        ), {"doc": document}).first()

    def anchors(self, moment) -> set:
        """Os documentos com evidencia qualificada e vigente: as ancoras da rede.

        Do mock, so quem tem papel de suspeito e contadores de golpe ou
        laranja, ou denuncia aberta. Da lista interna, os documentos
        vigentes. Vitima nunca e ancora.
        """
        externas = self.session.execute(text(
            "SELECT document FROM reputation_fixture WHERE entity_role = 'suspected_perpetrator' "
            "AND available_from <= :momento AND expires_at > :momento AND ("
            "(statistics->'mule_accounts'->>'m12')::int > 0 OR (statistics->'scammer_accounts'->>'m12')::int > 0 "
            "OR (statistics->>'open_reports')::int > 0)"
        ), {"momento": moment}).all()
        internas = self.session.execute(text(
            "SELECT value FROM watchlist WHERE kind = 'document' AND available_from <= :momento AND expires_at > :momento"
        ), {"momento": moment}).all()
        return {linha[0] for linha in externas} | {linha[0] for linha in internas}
