"""As perguntas que as regras fazem ao historico, e as travas que as protegem.

Toda janela e ancorada no instante do Pix (`moment`, a transaction_date),
nunca no relogio do servidor: `moment - janela < transaction_date <= moment`.
O Pix em analise ainda nao foi gravado quando estas consultas rodam, entao
nenhuma delas o conta; a regra que precisa dele soma +1.

"Aprovado" e dinheiro que saiu: status APPROVED, ou um desafio que o
cliente confirmou depois (approved_by_client). `two_factor_required` sem
confirmacao nao aconteceu.
"""
from datetime import timedelta

from sqlalchemy import text

from database import Context

APPROVED = (
    "(a.status_id = (SELECT id FROM pix_status WHERE enumerator = 'APPROVED') "
    "OR EXISTS (SELECT 1 FROM pix_challenge_result c WHERE c.analysis_id = a.id AND c.result = 'approved_by_client'))"
)

RESTRICTIVE = (
    "(a.status_id <> (SELECT id FROM pix_status WHERE enumerator = 'APPROVED') "
    "AND NOT EXISTS (SELECT 1 FROM pix_challenge_result c WHERE c.analysis_id = a.id AND c.result = 'approved_by_client'))"
)


class HistoryRepository:
    def __init__(self, context: Context) -> None:
        self.session = context.db_session
        self._cache = {}

    def _remember(self, key, consulta):
        if key not in self._cache:
            self._cache[key] = consulta()
        return self._cache[key]

    def _all(self, sql: str, **params):
        return self.session.execute(text(sql), params).all()

    def _scalar(self, sql: str, **params):
        return self.session.execute(text(sql), params).scalar()

    # ------------------------------------------------------------------
    # As travas
    # ------------------------------------------------------------------

    def lock(self, keys: list) -> None:
        """Trava, ate o commit, o pagador, o recebedor e o aparelho (o IP nao: ver o controller).

        Sao travas consultivas (pg_advisory_xact_lock): nao prendem linha
        nenhuma, so serializam quem pede a mesma chave. Dois Pix do mesmo
        pagador, ou para o mesmo recebedor, ou do mesmo aparelho, esperam um
        o outro, e cada um ve o historico que o anterior gravou. Sem isso,
        oito Pix simultaneos veriam todos "zero tentativas" e a velocity nao
        dispararia em nenhum.

        A ordem e sempre a mesma (a das chaves ordenadas), e e isso que
        impede o deadlock: A -> B e B -> A pedem as travas na mesma ordem.
        Elas se soltam sozinhas no commit ou no rollback. Nenhuma linha de
        conta e travada, entao o KEY SHARE da chave estrangeira (o deadlock
        de 07/10 da fase 1) nao tem com quem brigar.
        """
        for chave in sorted(set(keys)):
            self.session.execute(text("SELECT pg_advisory_xact_lock(hashtextextended(:k, 0))"), {"k": chave})

    # ------------------------------------------------------------------
    # Ritmo e montante da conta pagadora
    # ------------------------------------------------------------------

    def attempts(self, account_id: int, moment, minutes: int) -> int:
        return self._remember(("attempts", account_id, minutes), lambda: self._scalar(
            "SELECT count(*) FROM pix_analysis a WHERE a.source_account_id = :conta "
            "AND a.transaction_date > :inicio AND a.transaction_date <= :fim",
            conta=account_id, inicio=moment - timedelta(minutes=minutes), fim=moment,
        ))

    def approved_sum_and_count(self, account_id: int, moment, minutes: int) -> tuple:
        def consulta():
            linha = self.session.execute(text(
                f"SELECT coalesce(sum(a.amount), 0), count(*) FROM pix_analysis a WHERE a.source_account_id = :conta "
                f"AND a.transaction_date > :inicio AND a.transaction_date <= :fim AND {APPROVED}"
            ), {"conta": account_id, "inicio": moment - timedelta(minutes=minutes), "fim": moment}).first()
            return int(linha[0]), int(linha[1])
        return self._remember(("approved", account_id, minutes), consulta)

    def restrictive_attempts(self, account_id: int, moment, minutes: int) -> list:
        """As tentativas recentes que nao viraram dinheiro, em ordem."""
        return self._remember(("restrictive", account_id, minutes), lambda: self._all(
            f"SELECT a.transaction_date, a.amount, a.destination_document FROM pix_analysis a "
            f"WHERE a.source_account_id = :conta "
            f"AND a.transaction_date > :inicio AND a.transaction_date <= :fim AND {RESTRICTIVE} "
            "ORDER BY a.transaction_date",
            conta=account_id, inicio=moment - timedelta(minutes=minutes), fim=moment,
        ))

    def attempt_dates(self, account_id: int, moment) -> tuple:
        """A primeira e a ultima tentativa da conta antes deste Pix."""
        def consulta():
            linha = self.session.execute(text(
                "SELECT min(a.transaction_date), max(a.transaction_date) FROM pix_analysis a "
                "WHERE a.source_account_id = :conta AND a.transaction_date <= :fim"
            ), {"conta": account_id, "fim": moment}).first()
            return linha[0], linha[1]
        return self._remember(("attempt_dates", account_id), consulta)

    def latest_attempt(self, account_id: int):
        """A data mais nova ja analisada para a conta, SEM limite superior.

        E a unica consulta que olha depois do instante do Pix: serve para
        ver que ele chegou com data anterior a Pix que ja aconteceram.
        """
        return self._remember(("latest", account_id), lambda: self._scalar(
            "SELECT max(a.transaction_date) FROM pix_analysis a WHERE a.source_account_id = :conta",
            conta=account_id,
        ))

    def last_attempt_before(self, account_id: int, before):
        return self._remember(("last_before", account_id), lambda: self._scalar(
            "SELECT max(a.transaction_date) FROM pix_analysis a WHERE a.source_account_id = :conta "
            "AND a.transaction_date <= :antes",
            conta=account_id, antes=before,
        ))

    def approved_amounts_of_payer(self, account_id: int, moment, days: int) -> list:
        return self._remember(("payer_amounts", account_id, days), lambda: self._all(
            f"SELECT a.amount, a.transaction_date FROM pix_analysis a WHERE a.source_account_id = :conta "
            f"AND a.transaction_date > :inicio AND a.transaction_date <= :fim AND {APPROVED}",
            conta=account_id, inicio=moment - timedelta(days=days), fim=moment,
        ))

    def approved_amounts_of_pair(self, source_document: str, destination_document: str, moment, days: int) -> list:
        return self._remember(("pair_amounts", source_document, destination_document, days), lambda: self._all(
            f"SELECT a.amount, a.transaction_date FROM pix_analysis a WHERE a.source_document = :origem "
            f"AND a.destination_document = :destino AND a.transaction_date > :inicio "
            f"AND a.transaction_date <= :fim AND {APPROVED}",
            origem=source_document, destino=destination_document,
            inicio=moment - timedelta(days=days), fim=moment,
        ))

    def approved_to_document(self, source_document: str, destination_document: str, moment) -> list:
        """Todos os pagamentos aprovados deste titular para aquele titular, antes do Pix."""
        return self._remember(("to_document", source_document, destination_document), lambda: self._all(
            f"SELECT a.amount, a.transaction_date FROM pix_analysis a WHERE a.source_document = :origem "
            f"AND a.destination_document = :destino AND a.transaction_date < :fim AND {APPROVED}",
            origem=source_document, destino=destination_document, fim=moment,
        ))

    def daily_approved_totals(self, account_id: int, day_start, days: int, timezone: str) -> list:
        """O total aprovado de cada dia com movimento, nos dias completos antes de hoje."""
        return self._remember(("daily_totals", account_id, days), lambda: [linha[0] for linha in self._all(
            f"SELECT sum(a.amount) FROM pix_analysis a WHERE a.source_account_id = :conta "
            f"AND a.transaction_date >= :inicio AND a.transaction_date < :fim AND {APPROVED} "
            "GROUP BY (a.transaction_date AT TIME ZONE :fuso)::date",
            conta=account_id, inicio=day_start - timedelta(days=days), fim=day_start, fuso=timezone,
        )])

    # ------------------------------------------------------------------
    # Acesso: aparelho, rede, IP e lugar
    # ------------------------------------------------------------------

    def prior_attempts_of_document(self, document: str, moment) -> int:
        return self._remember(("doc_attempts", document), lambda: self._scalar(
            "SELECT count(*) FROM pix_analysis a WHERE a.source_document = :doc AND a.transaction_date <= :fim",
            doc=document, fim=moment,
        ))

    def device_seen(self, document: str, device_id: str, moment) -> bool:
        return self._remember(("device_seen", document, device_id), lambda: self._scalar(
            "SELECT EXISTS (SELECT 1 FROM pix_analysis a WHERE a.source_document = :doc "
            "AND a.device_id = :aparelho AND a.transaction_date <= :fim)",
            doc=document, aparelho=device_id, fim=moment,
        ))

    def network_seen(self, document: str, network: str, moment) -> bool:
        return self._remember(("network_seen", document, network), lambda: self._scalar(
            "SELECT EXISTS (SELECT 1 FROM pix_analysis a WHERE a.source_document = :doc "
            "AND a.ip_network = CAST(:rede AS cidr) AND a.transaction_date <= :fim)",
            doc=document, rede=network, fim=moment,
        ))

    def documents_on_device(self, device_id: str, moment, days: int) -> set:
        return self._remember(("docs_device", device_id, days), lambda: {linha[0] for linha in self._all(
            "SELECT DISTINCT a.source_document FROM pix_analysis a WHERE a.device_id = :aparelho "
            "AND a.transaction_date > :inicio AND a.transaction_date <= :fim",
            aparelho=device_id, inicio=moment - timedelta(days=days), fim=moment,
        )})

    def documents_on_ip(self, ip: str, moment, minutes: int) -> set:
        return self._remember(("docs_ip", ip, minutes), lambda: {linha[0] for linha in self._all(
            "SELECT DISTINCT a.source_document FROM pix_analysis a WHERE a.ip = CAST(:ip AS inet) "
            "AND a.transaction_date > :inicio AND a.transaction_date <= :fim",
            ip=ip, inicio=moment - timedelta(minutes=minutes), fim=moment,
        )})

    def last_located(self, document: str, moment):
        """O ultimo ponto conhecido do titular: o GPS, ou o lugar do IP sem GPS."""
        return self._remember(("last_located", document), lambda: self.session.execute(text(
            "SELECT a.transaction_date, a.latitude, a.longitude, a.ip_latitude, a.ip_longitude "
            "FROM pix_analysis a WHERE a.source_document = :doc AND a.transaction_date <= :fim "
            "AND (a.latitude IS NOT NULL OR a.ip_latitude IS NOT NULL) "
            "ORDER BY a.transaction_date DESC LIMIT 1"
        ), {"doc": document, "fim": moment}).first())

    def approved_gps_points(self, document: str, moment, days: int) -> list:
        return self._remember(("gps_points", document, days), lambda: self._all(
            f"SELECT a.latitude, a.longitude, a.transaction_date FROM pix_analysis a "
            f"WHERE a.source_document = :doc AND a.latitude IS NOT NULL AND a.transaction_date > :inicio "
            f"AND a.transaction_date <= :fim AND {APPROVED}",
            doc=document, inicio=moment - timedelta(days=days), fim=moment,
        ))

    def coordinated_payers(self, device_id: str, destination_account_id: int, moment, minutes: int) -> set:
        return self._remember(("coordination", device_id, destination_account_id, minutes), lambda: {
            linha[0] for linha in self._all(
                "SELECT DISTINCT a.source_document FROM pix_analysis a WHERE a.device_id = :aparelho "
                "AND a.destination_account_id = :destino AND a.transaction_date > :inicio "
                "AND a.transaction_date <= :fim",
                aparelho=device_id, destino=destination_account_id,
                inicio=moment - timedelta(minutes=minutes), fim=moment,
            )
        })

    # ------------------------------------------------------------------
    # O recebedor: concentracao, repasse e rede
    # ------------------------------------------------------------------

    def payers_to_account(self, account_id: int, moment, minutes: int) -> set:
        """Documentos pagadores distintos para esta conta, de qualquer status."""
        return self._remember(("payers_to", account_id, minutes), lambda: {linha[0] for linha in self._all(
            "SELECT DISTINCT a.source_document FROM pix_analysis a WHERE a.destination_account_id = :conta "
            "AND a.transaction_date > :inicio AND a.transaction_date <= :fim",
            conta=account_id, inicio=moment - timedelta(minutes=minutes), fim=moment,
        )})

    def received_by_account(self, account_id: int, moment, minutes: int) -> tuple:
        """O que a conta recebeu (aprovado) na janela: total e quem pagou."""
        def consulta():
            linhas = self._all(
                f"SELECT a.source_document, a.amount FROM pix_analysis a WHERE a.destination_account_id = :conta "
                f"AND a.transaction_date > :inicio AND a.transaction_date <= :fim AND {APPROVED}",
                conta=account_id, inicio=moment - timedelta(minutes=minutes), fim=moment,
            )
            return sum(int(item[1]) for item in linhas), {item[0] for item in linhas}
        return self._remember(("received", account_id, minutes), consulta)

    # ------------------------------------------------------------------
    # Eventos para as reguas de cada cliente (controllers/engine/reference.py)
    # ------------------------------------------------------------------

    def outgoing_events(self, account_id: int, start, end) -> list:
        """(data, valor, aprovado) de cada saida da conta no periodo, em ordem."""
        return [(item[0], int(item[1]), bool(item[2])) for item in self._all(
            f"SELECT a.transaction_date, a.amount, {APPROVED} FROM pix_analysis a "
            "WHERE a.source_account_id = :conta AND a.transaction_date >= :inicio AND a.transaction_date < :fim "
            "ORDER BY a.transaction_date",
            conta=account_id, inicio=start, fim=end,
        )]

    def incoming_events(self, account_id: int, start, end) -> list:
        """(data, valor, documento pagador) de cada entrada na conta no periodo, em ordem."""
        return [(item[0], int(item[1]), item[2]) for item in self._all(
            "SELECT a.transaction_date, a.amount, a.source_document FROM pix_analysis a "
            "WHERE a.destination_account_id = :conta AND a.transaction_date >= :inicio AND a.transaction_date < :fim "
            "ORDER BY a.transaction_date",
            conta=account_id, inicio=start, fim=end,
        )]

    def network_path(self, anchors: set, destination_document: str, moment, days: int, min_amount: int = 1):
        """O caminho de ate dois saltos de uma ancora ate o destino, por Pix aprovados.

        Um salto: a ancora pagou o destino. Dois: a ancora pagou alguem que
        pagou o destino. So as ancoras espalham suspeita; o vizinho nao vira
        ancora nova, e a suspeita nao se propaga sem fim. Devolve (saltos,
        caminho) ou None.

        Aresta abaixo de `min_amount` nao conta: sem o corte, uma ancora que
        e cliente da casa contaminava qualquer conta com um Pix de R$ 0,01.
        """
        if not anchors:
            return None
        inicio, fim = moment - timedelta(days=days), moment
        um_salto = self._all(
            f"SELECT a.source_document FROM pix_analysis a WHERE a.source_document = ANY(:ancoras) "
            f"AND a.destination_document = :destino AND a.transaction_date > :inicio AND a.transaction_date <= :fim "
            f"AND a.amount >= :minimo AND {APPROVED} LIMIT 1",
            ancoras=list(anchors), destino=destination_document, inicio=inicio, fim=fim, minimo=min_amount,
        )
        if um_salto:
            return 1, [um_salto[0][0], destination_document]
        dois_saltos = self._all(
            f"SELECT a.source_document, b.source_document FROM pix_analysis a JOIN pix_analysis b "
            f"ON b.destination_document = a.source_document "
            f"WHERE a.destination_document = :destino AND b.source_document = ANY(:ancoras) "
            f"AND a.transaction_date > :inicio AND a.transaction_date <= :fim "
            f"AND b.transaction_date > :inicio AND b.transaction_date <= a.transaction_date "
            f"AND a.amount >= :minimo AND b.amount >= :minimo "
            f"AND {APPROVED} AND {APPROVED.replace('a.', 'b.')} LIMIT 1",
            ancoras=list(anchors), destino=destination_document, inicio=inicio, fim=fim, minimo=min_amount,
        )
        if dois_saltos:
            meio, ancora = dois_saltos[0]
            return 2, [ancora, meio, destination_document]
        return None
