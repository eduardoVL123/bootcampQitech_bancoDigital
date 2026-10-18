from datetime import datetime, timezone
from types import SimpleNamespace

from sqlalchemy import text

from connectors.dict_connector import DictConnector
from database import Context

SINAIS_DO_DICT = ("mule_accounts", "scammer_accounts", "application_frauds")


class ReputationRepository:
    """O mock de reputacao externa, o mock de cadastro de CNPJ e as ancoras da rede.

    O mock de reputacao imita o `destination_statistics` da API Pix da QI. Ele
    fornece evidencias; quem decide e o motor (controllers/rules/reputacao_externa.py).
    O de cadastro faz as vezes dos dados abertos do CNPJ da Receita: a atividade
    principal (CNAE) de quem recebe.
    """

    def __init__(self, context: Context) -> None:
        self.session = context.db_session
        self.dict = DictConnector()

    def fixtures(self, document: str) -> list:
        """As evidencias do documento: as do mock local e, se houver sinal, a do DICT.

        A do DICT entra primeiro na lista: a regra usa a ultima vigente, e uma
        evidencia local (o seed) continua valendo por cima dela.
        """
        locais = self.session.execute(text(
            "SELECT document, scope, statistics, entity_role, evidence_id, available_from, expires_at, "
            "fixture_version FROM reputation_fixture WHERE document = :doc ORDER BY available_from"
        ), {"doc": document}).all()
        do_dict = self._do_dict(document)
        return ([do_dict] if do_dict else []) + list(locais)

    def _do_dict(self, document: str):
        resposta = self.dict.security_information(document)
        if not resposta:
            return None
        estatisticas = resposta["statistics"]
        com_sinal = int(estatisticas.get("open_reports", 0)) > 0 or any(
            int(v) for campo in SINAIS_DO_DICT for v in (estatisticas.get(campo) or {}).values())
        if not com_sinal:
            return None
        golpista = any(int(v) for campo in ("mule_accounts", "scammer_accounts")
                       for v in (estatisticas.get(campo) or {}).values()) or int(estatisticas.get("open_reports", 0)) > 0
        return SimpleNamespace(
            document=document, scope="person", statistics=estatisticas,
            entity_role="suspected_perpetrator" if golpista else "none",
            evidence_id=resposta.get("evidence_id") or f"dict-{document[-4:]}",
            available_from=datetime(1970, 1, 1, tzinfo=timezone.utc),
            expires_at=datetime(9999, 1, 1, tzinfo=timezone.utc),
            fixture_version="dict", provider="dict",
        )

    def company(self, document: str):
        """O cadastro do CNPJ no mock (a atividade principal), ou None."""
        return self.session.execute(text(
            "SELECT document, cnae, fixture_version FROM cnpj_fixture WHERE document = :doc"
        ), {"doc": document}).first()

    def anchors(self, moment) -> set:
        """Os documentos com fraude CONFIRMADA e vigente: as ancoras da rede.

        So a fraude confirmada espalha suspeita para os vizinhos. A palavra de
        uma fonte so nao espalha: nem a cautelar de um "nao fui eu"
        (`creator = client`), nem a denuncia que ainda nao foi analisada
        (`open_reports`). Sem esse corte, um cliente so fazia a loja que o
        denunciado pagou perder todos os clientes novos por 30 dias.

        Do mock, quem tem papel de suspeito e contadores de golpe ou laranja
        (a marcacao que a instituicao do recebedor ja confirmou). Da lista
        interna, o caso semeado e o confirmado por duas fontes. Vitima nunca
        e ancora.
        """
        externas = self.session.execute(text(
            "SELECT document FROM reputation_fixture WHERE entity_role = 'suspected_perpetrator' "
            "AND available_from <= :momento AND expires_at > :momento AND ("
            "(statistics->'mule_accounts'->>'m12')::int > 0 OR (statistics->'scammer_accounts'->>'m12')::int > 0)"
        ), {"momento": moment}).all()
        internas = self.session.execute(text(
            "SELECT value FROM watchlist WHERE kind = 'document' AND creator IN ('external', 'confirmed') "
            "AND available_from <= :momento AND expires_at > :momento"
        ), {"momento": moment}).all()
        return {linha[0] for linha in externas} | {linha[0] for linha in internas}

    def suspected(self, document: str, moment):
        """A evidencia externa vigente de que o documento e de golpista, ou None.

        E a segunda fonte que confirma a cautelar: o titular disse "nao fui
        eu" e outra instituicao (o DICT ou o mock) ja tinha denuncia ou
        marcacao de golpe ou laranja contra o mesmo documento.
        """
        for registro in reversed(self.fixtures(document)):
            if not registro.available_from <= moment < registro.expires_at:
                continue
            if registro.entity_role != "suspected_perpetrator":
                continue
            estatisticas = registro.statistics
            marcas = sum(int((estatisticas.get(campo) or {}).get("m12", 0)) for campo in ("mule_accounts", "scammer_accounts"))
            if marcas or int(estatisticas.get("open_reports", 0)) > 0:
                return registro.evidence_id
        return None
