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

    def gps_habit(self, document: str, moment, days: int) -> tuple:
        """(tentativas com GPS, tentativas no total) do titular na janela, antes deste Pix."""
        def consulta():
            linha = self.session.execute(text(
                "SELECT count(a.latitude), count(*) FROM pix_analysis a WHERE a.source_document = :doc "
                "AND a.transaction_date > :inicio AND a.transaction_date <= :fim"
            ), {"doc": document, "inicio": moment - timedelta(days=days), "fim": moment}).first()
            return int(linha[0]), int(linha[1])
        return self._remember(("gps_habit", document, days), consulta)

    def device_registration(self, document: str, device_id: str, moment, day_start) -> tuple:
        """(aparelho do primeiro Pix do titular, aparelho ja confirmado num desafio, aprovado hoje nele)."""
        def consulta():
            linha = self.session.execute(text(
                "SELECT "
                "(SELECT a.device_id FROM pix_analysis a WHERE a.source_document = :doc AND a.transaction_date <= :fim "
                " ORDER BY a.transaction_date, a.id LIMIT 1), "
                "EXISTS (SELECT 1 FROM pix_analysis a JOIN pix_challenge_result c ON c.analysis_id = a.id "
                " WHERE a.source_document = :doc AND a.device_id = :aparelho AND c.result = 'approved_by_client' "
                " AND a.transaction_date <= :fim), "
                f"(SELECT coalesce(sum(a.amount), 0) FROM pix_analysis a WHERE a.source_document = :doc "
                f" AND a.device_id = :aparelho AND a.transaction_date >= :dia AND a.transaction_date <= :fim "
                f" AND {APPROVED})"
            ), {"doc": document, "aparelho": device_id, "fim": moment, "dia": day_start}).first()
            return linha[0], bool(linha[1]), int(linha[2])
        return self._remember(("device_registration", document, device_id), consulta)

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

    def new_payers_to_account(self, account_id: int, document: str, moment, hours: int) -> tuple:
        """Quem pagou esta conta na janela sem vinculo anterior com ela: (documentos, soma).

        Vinculo e Pix aprovado antes da janela, nos dois sentidos: o pagador ja
        tinha pago esta conta, ou ja tinha recebido do dono dela. Amigo que
        racha a conta com o organizador tem vinculo; vitima de laranja nunca tem.
        Conta qualquer status dentro da janela: a tentativa barrada tambem e sinal.
        """
        def consulta():
            inicio = moment - timedelta(hours=hours)
            linhas = self._all(
                "SELECT a.source_document, a.amount FROM pix_analysis a WHERE a.destination_account_id = :conta "
                "AND a.transaction_date > :inicio AND a.transaction_date <= :fim "
                "AND NOT EXISTS (SELECT 1 FROM pix_analysis b WHERE b.destination_account_id = :conta "
                f"AND b.source_document = a.source_document AND b.transaction_date <= :inicio "
                f"AND {APPROVED.replace('a.', 'b.')}) "
                "AND NOT EXISTS (SELECT 1 FROM pix_analysis b WHERE b.source_document = :dono "
                f"AND b.destination_document = a.source_document AND b.transaction_date <= :inicio "
                f"AND {APPROVED.replace('a.', 'b.')})",
                conta=account_id, dono=document, inicio=inicio, fim=moment,
            )
            return {linha[0] for linha in linhas}, sum(int(linha[1]) for linha in linhas)
        return self._remember(("novos_pagadores", account_id, hours, moment), consulta)

    def received_before(self, account_id: int, moment, hours: int, days: int) -> int:
        """O que a conta recebeu (aprovado) nos `days` dias antes da janela de `hours` horas."""
        fim = moment - timedelta(hours=hours)
        return self._remember(("recebido_antes", account_id, hours, days, moment), lambda: int(self._scalar(
            f"SELECT COALESCE(SUM(a.amount), 0) FROM pix_analysis a WHERE a.destination_account_id = :conta "
            f"AND a.transaction_date > :inicio AND a.transaction_date <= :fim AND {APPROVED}",
            conta=account_id, inicio=fim - timedelta(days=days), fim=fim,
        ) or 0))

    def sent_by_account(self, account_id: int, moment, minutes: int, excluir: set) -> int:
        """O que a conta pagou (aprovado) na janela, sem contar o que voltou para quem pagou."""
        def consulta():
            linhas = self._all(
                f"SELECT a.destination_document, a.amount FROM pix_analysis a WHERE a.source_account_id = :conta "
                f"AND a.transaction_date > :inicio AND a.transaction_date < :fim AND {APPROVED}",
                conta=account_id, inicio=moment - timedelta(minutes=minutes), fim=moment,
            )
            return sum(int(valor) for destino, valor in linhas if destino not in excluir)
        return self._remember(("enviado", account_id, minutes, moment), consulta)

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

    def approved_credits_from_others(self, account_id: int, payer_document: str, moment, days: int) -> list:
        """(valor, data, pagador) dos creditos aprovados na conta, de quem nao e o pagador de agora.

        E a regua de ticket do recebedor. O proprio pagador fica de fora: o
        que ele costuma pagar ali e o par do PERFIL, e contaria duas vezes.
        """
        return self._remember(("credits_from_others", account_id, payer_document, days), lambda: self._all(
            f"SELECT a.amount, a.transaction_date, a.source_document FROM pix_analysis a "
            f"WHERE a.destination_account_id = :conta AND a.source_document <> :pagador "
            f"AND a.transaction_date > :inicio AND a.transaction_date <= :fim AND {APPROVED}",
            conta=account_id, pagador=payer_document, inicio=moment - timedelta(days=days), fim=moment,
        ))

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

    def forwarded_to_anchor(self, anchors: set, document: str, moment, days: int, min_amount: int,
                            hours: int, min_payers: int, share: float):
        """O documento mandou (ou tentou mandar) a uma ancora o dinheiro que tinha acabado de receber.

        E o outro sentido da rede: a laranja que repassa para o chefe. So
        pagar uma ancora nao separa ninguem, porque a vitima tambem pagou o
        golpista. O que separa a laranja da vitima e o repasse: nas `hours`
        horas antes de mandar, ela recebeu de `min_payers` ou mais pagadores
        sem vinculo com ela, e isso cobre pelo menos `share` do que mandou.
        Vinculo e o da CONTA_LARANJA: Pix aprovado antes, nos dois sentidos.
        O amigo que racha a conta com o organizador tem vinculo; a vitima da
        laranja nunca tem.

        A saida conta mesmo recusada: quando a ancora ja e conhecida, o
        repasse para ela e barrado, e a recusa mostra para onde o dinheiro
        ia. A entrada, nao: so conta o dinheiro que entrou de verdade. Devolve
        (ancora, pagadores, recebido, enviado) ou None.
        """
        if not anchors:
            return None
        saidas = self._all(
            "SELECT a.destination_document, a.amount, a.transaction_date FROM pix_analysis a "
            "WHERE a.source_document = :doc AND a.destination_document = ANY(:ancoras) "
            "AND a.transaction_date > :inicio AND a.transaction_date <= :fim AND a.amount >= :minimo "
            "ORDER BY a.transaction_date DESC",
            doc=document, ancoras=list(anchors), inicio=moment - timedelta(days=days), fim=moment, minimo=min_amount,
        )
        for ancora, enviado, data in saidas:
            pagadores, recebido = self.session.execute(text(
                f"SELECT count(DISTINCT e.source_document), coalesce(sum(e.amount), 0) FROM pix_analysis e "
                f"WHERE e.destination_document = :doc AND e.source_document NOT IN (:doc, :ancora) "
                f"AND e.transaction_date > :inicio AND e.transaction_date < :fim AND {APPROVED.replace('a.', 'e.')} "
                "AND NOT EXISTS (SELECT 1 FROM pix_analysis b WHERE b.source_document = e.source_document "
                f"AND b.destination_document = :doc AND b.transaction_date <= :inicio AND {APPROVED.replace('a.', 'b.')}) "
                "AND NOT EXISTS (SELECT 1 FROM pix_analysis b WHERE b.source_document = :doc "
                f"AND b.destination_document = e.source_document AND b.transaction_date <= :inicio "
                f"AND {APPROVED.replace('a.', 'b.')})"
            ), {"doc": document, "ancora": ancora, "inicio": data - timedelta(hours=hours), "fim": data}).first()
            if pagadores >= min_payers and recebido >= share * int(enviado):
                return ancora, int(pagadores), int(recebido), int(enviado)
        return None
