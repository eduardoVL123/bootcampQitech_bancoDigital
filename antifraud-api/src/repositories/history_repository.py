"""As perguntas que as regras fazem ao historico, e as travas que as protegem.

Toda janela e ancorada no instante do Pix (`moment`, a transaction_date),
nunca no relogio do servidor: `moment - janela < transaction_date <= moment`.
O Pix em analise ainda nao foi gravado quando estas consultas rodam, entao
nenhuma delas o conta; a regra que precisa dele soma +1.

"Aprovado" e dinheiro que saiu ATE O INSTANTE CONSULTADO: status APPROVED,
ou um desafio que o cliente confirmou (approved_by_client) com event_date
ate aquele instante. O Pix das 10h confirmado as 10h05 era, as 10h03, um
desafio pendente, e ainda uma decisao restritiva, mesmo que a confirmacao
ja esteja gravada quando a consulta roda. `two_factor_required` sem
confirmacao nao aconteceu. O corte e a data do Pix sao coisas diferentes:
as janelas continuam pela transaction_date, e o corte so decide se a
confirmacao ja existia.

Os cortes: nas regras, o instante do Pix (`moment`); nas referencias
congeladas no inicio do dia (perfil, calendario, totais diarios, ticket do
recebedor, regua adaptativa), o inicio do dia em Sao Paulo, com a
transaction_date abaixo dele (exclusivo): o Pix da meia-noite e a
confirmacao de hoje entram so na regua de amanha. E corte de eventos, nao
snapshot: um Pix historico gravado depois ainda muda a amostra das
proximas consultas. A analise gravada nao muda.
"""
import re
from datetime import timedelta

from sqlalchemy import text

from database import Context

_IDENTIFIER = re.compile(r"[a-z_]+")
_APPROVED_STATUS = "(SELECT id FROM pix_status WHERE enumerator = 'APPROVED')"


def _confirmed_as_of(alias: str, cutoff: str) -> str:
    if not (_IDENTIFIER.fullmatch(alias) and _IDENTIFIER.fullmatch(cutoff)):
        raise ValueError(f"Identificador SQL invalido: {alias!r}, {cutoff!r}")
    confirmacao = f"c_{alias}"
    return (f"EXISTS (SELECT 1 FROM pix_challenge_result {confirmacao} WHERE {confirmacao}.analysis_id = {alias}.id "
            f"AND {confirmacao}.result = 'approved_by_client' AND {confirmacao}.event_date <= :{cutoff})")


def approved_as_of(alias: str, cutoff: str) -> str:
    """A analise `alias` virou dinheiro ate o instante do parametro `:cutoff`.

    `alias` e `cutoff` sao nomes do codigo (o alias da pix_analysis na
    consulta e o nome do parametro), nunca valores: o instante vai sempre
    como parametro SQL. O helper nao limita a data do Pix; cada consulta
    continua com o filtro da sua janela.
    """
    return f"({alias}.status_id = {_APPROVED_STATUS} OR {_confirmed_as_of(alias, cutoff)})"


def restrictive_as_of(alias: str, cutoff: str) -> str:
    """O complemento de approved_as_of, no mesmo corte: ainda nao era dinheiro naquele instante."""
    return f"({alias}.status_id <> {_APPROVED_STATUS} AND NOT {_confirmed_as_of(alias, cutoff)})"


def analysis_lock_keys(source_document: str, destination_document: str, source_account_id: int,
                       destination_account_id: int, device_id: str) -> list:
    """As chaves das travas de uma analise. O POST e o PATCH usam esta funcao, e so ela.

    A conta entra pelo id, com o mesmo prefixo nos dois papeis: a conta que
    recebe aqui e a mesma que paga ali, e quem a usa como origem espera
    quem a usa como destino. O IP fica de fora de proposito: atras de um
    CGNAT de operadora, milhares de clientes dividem o mesmo IP, e travar
    por ele enfileirava todos. A unica regra que conta por IP
    (IP_COMPARTILHADO, +15) aceita errar por um num pico simultaneo.
    """
    return [
        f"payer:{source_document}",
        f"payee:{destination_document}",
        f"account:{source_account_id}",
        f"account:{destination_account_id}",
        f"device:{device_id}",
    ]


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
        """Trava, ate o commit, as chaves pedidas (as de uma analise: ver analysis_lock_keys).

        Sao travas consultivas (pg_advisory_xact_lock): nao prendem linha
        nenhuma, so serializam quem pede a mesma chave. Dois Pix do mesmo
        pagador, ou para o mesmo recebedor, ou da mesma conta, ou do mesmo
        aparelho, esperam um o outro, e cada um ve o historico que o
        anterior gravou. Sem isso,
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

    def lock_analysis(self, source_document: str, destination_document: str, source_account_id: int,
                      destination_account_id: int, device_id: str) -> None:
        self.lock(analysis_lock_keys(source_document, destination_document, source_account_id,
                                     destination_account_id, device_id))

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
                f"AND a.transaction_date > :inicio AND a.transaction_date <= :fim AND {approved_as_of('a', 'fim')}"
            ), {"conta": account_id, "inicio": moment - timedelta(minutes=minutes), "fim": moment}).first()
            return int(linha[0]), int(linha[1])
        return self._remember(("approved", account_id, moment, minutes), consulta)

    def restrictive_attempts(self, account_id: int, moment, minutes: int) -> list:
        """As tentativas recentes que nao tinham virado dinheiro neste instante, em ordem."""
        return self._remember(("restrictive", account_id, moment, minutes), lambda: self._all(
            f"SELECT a.transaction_date, a.amount, a.destination_document FROM pix_analysis a "
            f"WHERE a.source_account_id = :conta "
            f"AND a.transaction_date > :inicio AND a.transaction_date <= :fim AND {restrictive_as_of('a', 'fim')} "
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

    def approved_amounts_of_payer(self, account_id: int, day_start, days: int) -> list:
        """Os aprovados da conta nos `days` dias antes do inicio de hoje: a referencia congelada."""
        return self._remember(("payer_amounts", account_id, day_start, days), lambda: self._all(
            f"SELECT a.amount, a.transaction_date FROM pix_analysis a WHERE a.source_account_id = :conta "
            f"AND a.transaction_date > :inicio AND a.transaction_date < :fim AND {approved_as_of('a', 'fim')}",
            conta=account_id, inicio=day_start - timedelta(days=days), fim=day_start,
        ))

    def approved_amounts_of_pair(self, source_document: str, destination_document: str, day_start, days: int) -> list:
        """Os aprovados do par nos `days` dias antes do inicio de hoje: a referencia congelada."""
        return self._remember(("pair_amounts", source_document, destination_document, day_start, days),
                              lambda: self._all(
            f"SELECT a.amount, a.transaction_date FROM pix_analysis a WHERE a.source_document = :origem "
            f"AND a.destination_document = :destino AND a.transaction_date > :inicio "
            f"AND a.transaction_date < :fim AND {approved_as_of('a', 'fim')}",
            origem=source_document, destino=destination_document,
            inicio=day_start - timedelta(days=days), fim=day_start,
        ))

    def approved_to_document(self, source_document: str, destination_document: str, moment) -> list:
        """Todos os pagamentos aprovados deste titular para aquele titular, antes do Pix."""
        return self._remember(("to_document", source_document, destination_document, moment), lambda: self._all(
            f"SELECT a.amount, a.transaction_date FROM pix_analysis a WHERE a.source_document = :origem "
            f"AND a.destination_document = :destino AND a.transaction_date < :fim AND {approved_as_of('a', 'fim')}",
            origem=source_document, destino=destination_document, fim=moment,
        ))

    def daily_approved_totals(self, account_id: int, day_start, days: int, timezone: str) -> list:
        """O total aprovado de cada dia com movimento, nos dias completos antes de hoje."""
        return self._remember(("daily_totals", account_id, day_start, days), lambda: [linha[0] for linha in self._all(
            f"SELECT sum(a.amount) FROM pix_analysis a WHERE a.source_account_id = :conta "
            f"AND a.transaction_date >= :inicio AND a.transaction_date < :fim AND {approved_as_of('a', 'fim')} "
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
        """(aparelho do primeiro Pix do titular, aparelho ja confirmado num desafio, aprovado hoje nele).

        O aparelho fica cadastrado no instante da confirmacao: uma
        confirmacao posterior a este Pix nao o cadastra retroativamente.
        """
        def consulta():
            linha = self.session.execute(text(
                "SELECT "
                "(SELECT a.device_id FROM pix_analysis a WHERE a.source_document = :doc AND a.transaction_date <= :fim "
                " ORDER BY a.transaction_date, a.id LIMIT 1), "
                "EXISTS (SELECT 1 FROM pix_analysis a JOIN pix_challenge_result c ON c.analysis_id = a.id "
                " WHERE a.source_document = :doc AND a.device_id = :aparelho AND c.result = 'approved_by_client' "
                " AND c.event_date <= :fim AND a.transaction_date <= :fim), "
                f"(SELECT coalesce(sum(a.amount), 0) FROM pix_analysis a WHERE a.source_document = :doc "
                f" AND a.device_id = :aparelho AND a.transaction_date >= :dia AND a.transaction_date <= :fim "
                f" AND {approved_as_of('a', 'fim')})"
            ), {"doc": document, "aparelho": device_id, "fim": moment, "dia": day_start}).first()
            return linha[0], bool(linha[1]), int(linha[2])
        return self._remember(("device_registration", document, device_id, moment), consulta)

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
        return self._remember(("gps_points", document, moment, days), lambda: self._all(
            f"SELECT a.latitude, a.longitude, a.transaction_date FROM pix_analysis a "
            f"WHERE a.source_document = :doc AND a.latitude IS NOT NULL AND a.transaction_date > :inicio "
            f"AND a.transaction_date <= :fim AND {approved_as_of('a', 'fim')}",
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
                f"AND {approved_as_of('b', 'fim')}) "
                "AND NOT EXISTS (SELECT 1 FROM pix_analysis b WHERE b.source_document = :dono "
                f"AND b.destination_document = a.source_document AND b.transaction_date <= :inicio "
                f"AND {approved_as_of('b', 'fim')})",
                conta=account_id, dono=document, inicio=inicio, fim=moment,
            )
            return {linha[0] for linha in linhas}, sum(int(linha[1]) for linha in linhas)
        return self._remember(("novos_pagadores", account_id, hours, moment), consulta)

    def received_before(self, account_id: int, moment, hours: int, days: int) -> int:
        """O que a conta recebeu (aprovado) nos `days` dias antes da janela de `hours` horas."""
        fim = moment - timedelta(hours=hours)
        return self._remember(("recebido_antes", account_id, hours, days, moment), lambda: int(self._scalar(
            f"SELECT COALESCE(SUM(a.amount), 0) FROM pix_analysis a WHERE a.destination_account_id = :conta "
            f"AND a.transaction_date > :inicio AND a.transaction_date <= :fim AND {approved_as_of('a', 'corte')}",
            conta=account_id, inicio=fim - timedelta(days=days), fim=fim, corte=moment,
        ) or 0))

    def flow_events(self, account_id: int, moment, minutes: int) -> list:
        """As entradas e saidas da conta que viraram dinheiro, por disponibilidade, na janela.

        E o insumo da projecao do repasse (controllers/engine/flow.py). Aqui
        o relogio e o da disponibilidade, nao o da data do Pix: o aprovado
        direto fica disponivel na transaction_date; o desafio confirmado, em
        max(transaction_date, event_date), e so se a confirmacao ja tinha
        acontecido no instante avaliado. Por isso o filtro nao pode ser so
        `transaction_date > inicio`: um Pix antigo confirmado dentro da
        janela entra nela, no instante da confirmacao.

        Tres ramos por lado, cada um no indice que serve a ele: os dois
        primeiros pela conta e data; o terceiro (Pix de antes da janela,
        confirmado dentro dela) pelo indice parcial das confirmacoes. Os
        ramos nao se sobrepoem: analise APPROVED nunca tem desafio. Devolve
        (disponivel, id, lado, valor, documento e conta da outra ponta), em
        ordem de (disponivel, id).
        """
        ramos = []
        for lado, conta, documento, outra in (("in", "destination_account_id", "source_document", "source_account_id"),
                                              ("out", "source_account_id", "destination_document",
                                               "destination_account_id")):
            colunas = f"'{lado}', a.amount, a.{documento}, a.{outra}"
            ramos += [
                f"SELECT a.transaction_date, a.id, {colunas} FROM pix_analysis a "
                f"WHERE a.{conta} = :conta AND a.transaction_date > :inicio AND a.transaction_date <= :fim "
                f"AND a.status_id = {_APPROVED_STATUS}",
                f"SELECT greatest(a.transaction_date, c.event_date), a.id, {colunas} FROM pix_analysis a "
                "JOIN pix_challenge_result c ON c.analysis_id = a.id AND c.result = 'approved_by_client' "
                f"WHERE a.{conta} = :conta AND a.transaction_date > :inicio AND a.transaction_date <= :fim "
                "AND c.event_date <= :fim",
                f"SELECT c.event_date, a.id, {colunas} FROM pix_challenge_result c "
                "JOIN pix_analysis a ON a.id = c.analysis_id "
                "WHERE c.result = 'approved_by_client' AND c.event_date > :inicio AND c.event_date <= :fim "
                f"AND a.{conta} = :conta AND a.transaction_date <= :inicio",
            ]
        return self._remember(("flow", account_id, moment, minutes), lambda: self._all(
            " UNION ALL ".join(ramos) + " ORDER BY 1, 2",
            conta=account_id, inicio=moment - timedelta(minutes=minutes), fim=moment,
        ))

    def approved_credits_from_others(self, account_id: int, payer_document: str, day_start, days: int) -> list:
        """(valor, data, pagador) dos creditos aprovados na conta, de quem nao e o pagador de agora.

        E a regua de ticket do recebedor, congelada no inicio do dia. O
        proprio pagador fica de fora: o que ele costuma pagar ali e o par do
        PERFIL, e contaria duas vezes.
        """
        return self._remember(("credits_from_others", account_id, payer_document, day_start, days), lambda: self._all(
            f"SELECT a.amount, a.transaction_date, a.source_document FROM pix_analysis a "
            f"WHERE a.destination_account_id = :conta AND a.source_document <> :pagador "
            f"AND a.transaction_date > :inicio AND a.transaction_date < :fim AND {approved_as_of('a', 'fim')}",
            conta=account_id, pagador=payer_document, inicio=day_start - timedelta(days=days), fim=day_start,
        ))

    # ------------------------------------------------------------------
    # Eventos para as reguas de cada cliente (controllers/engine/reference.py)
    # ------------------------------------------------------------------

    def outgoing_events(self, account_id: int, start, end) -> list:
        """(data, valor, aprovado ate `end`) de cada saida da conta no periodo, em ordem."""
        return [(item[0], int(item[1]), bool(item[2])) for item in self._all(
            f"SELECT a.transaction_date, a.amount, {approved_as_of('a', 'fim')} FROM pix_analysis a "
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
        """O caminho de ate dois saltos de uma ancora ate o destino, por Pix aprovados ate o instante.

        Um salto: a ancora pagou o destino. Dois: a ancora pagou alguem que
        pagou o destino. So as ancoras espalham suspeita; o vizinho nao vira
        ancora nova, e a suspeita nao se propaga sem fim. As duas arestas
        (`a`, a que chega no destino, e `b`, a que sai da ancora) precisam
        ser dinheiro no instante do Pix. Devolve (saltos, caminho) ou None.

        Aresta abaixo de `min_amount` nao conta: sem o corte, uma ancora que
        e cliente da casa contaminava qualquer conta com um Pix de R$ 0,01.
        """
        if not anchors:
            return None
        inicio, fim = moment - timedelta(days=days), moment
        um_salto = self._all(
            f"SELECT a.source_document FROM pix_analysis a WHERE a.source_document = ANY(:ancoras) "
            f"AND a.destination_document = :destino AND a.transaction_date > :inicio AND a.transaction_date <= :fim "
            f"AND a.amount >= :minimo AND {approved_as_of('a', 'fim')} LIMIT 1",
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
            f"AND {approved_as_of('a', 'fim')} AND {approved_as_of('b', 'fim')} LIMIT 1",
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
                f"AND e.transaction_date > :inicio AND e.transaction_date < :fim AND {approved_as_of('e', 'corte')} "
                "AND NOT EXISTS (SELECT 1 FROM pix_analysis b WHERE b.source_document = e.source_document "
                f"AND b.destination_document = :doc AND b.transaction_date <= :inicio AND {approved_as_of('b', 'corte')}) "
                "AND NOT EXISTS (SELECT 1 FROM pix_analysis b WHERE b.source_document = :doc "
                f"AND b.destination_document = e.source_document AND b.transaction_date <= :inicio "
                f"AND {approved_as_of('b', 'corte')})"
            ), {"doc": document, "ancora": ancora, "inicio": data - timedelta(hours=hours), "fim": data,
                "corte": moment}).first()
            if pagadores >= min_payers and recebido >= share * int(enviado):
                return ancora, int(pagadores), int(recebido), int(enviado)
        return None
