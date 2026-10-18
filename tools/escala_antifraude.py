"""Mede se a antifraud-api fica mais lenta quando o banco cresce.

Roda contra a antifraud-api de pe, de preferencia com o pg_stat_statements
ligado (tools/escala/compose.escala.yml), e responde quatro perguntas:

1. Volume total: com 0, 100 mil, 1 milhao de Pix no banco, o Pix de um
   cliente comum demora mais?
2. Entidade pesada: e se o volume estiver concentrado num pagador, numa
   loja que recebe de muita gente ou num IP de operadora (CGNAT)?
3. Concorrencia: quantos Pix por segundo a API aguenta com 1, 4, 8, 16
   chamadores, pagando destinos diferentes ou a mesma loja?
4. Quais consultas pesam, e quanto disco cada Pix gasta.

O banco e enchido por SQL, direto no Postgres, e a medicao e sempre por
HTTP. Encher pela API custaria uns 60 ms por Pix: um milhao levaria 17
horas. As linhas semeadas tem pix_id comecando por "escala-", vao na
pix_analysis (e nas contas) e carregam o metadata de um Pix de verdade,
para ocupar o mesmo espaco em disco. As tabelas sao append-only: para
limpar, docker compose down -v.

Uso:
    python tools/escala_antifraude.py --tamanhos 0,100000,1000000
"""
import argparse
import os
import random
import statistics
import sys
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path

import psycopg2
import requests

RAIZ = Path(__file__).resolve().parents[1]
CASA = "99999999"
OUTRA = "00000002"
SP_GPS = {"latitude": -23.56, "longitude": -46.65}
FUSO = timezone(timedelta(hours=-3))

COLUNAS = (
    "analysis_key, pix_id, request_hash, status_id, risk_score, authentication_level, scenario, reason, "
    "source_account_id, destination_account_id, source_document, destination_document, amount, transaction_date, "
    "device_id, channel, ip, ip_network, latitude, longitude, ip_latitude, ip_longitude, ip_location_source, "
    "policy_id, metadata"
)


# ----------------------------------------------------------------------
# Documentos validos (o motor confere o digito verificador do payload)
# ----------------------------------------------------------------------

def _digito(numeros: list, pesos: list) -> int:
    resto = sum(n * p for n, p in zip(numeros, pesos)) % 11
    return 0 if resto < 2 else 11 - resto


def cpf(rng: random.Random) -> str:
    while True:
        base = [rng.randint(0, 9) for _ in range(9)]
        if len(set(base)) > 1:
            break
    base.append(_digito(base, list(range(10, 1, -1))))
    base.append(_digito(base, list(range(11, 1, -1))))
    return "".join(map(str, base))


def cnpj(rng: random.Random) -> str:
    base = [rng.randint(0, 9) for _ in range(8)] + [0, 0, 0, 1]
    base.append(_digito(base, [5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2]))
    base.append(_digito(base, [6, 5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2]))
    return "".join(map(str, base))


# ----------------------------------------------------------------------
# O relogio dos Pix de medicao
# ----------------------------------------------------------------------

class Relogio:
    """Datas sempre crescentes, no passado recente.

    Todo Pix de medicao ganha uma data maior que a do anterior: assim
    nenhum cai na DATA_RETROATIVA e nenhum passa da tolerancia de futuro.
    Comeca duas horas atras e anda meio segundo por Pix.
    """

    def __init__(self) -> None:
        self._agora = datetime.now(FUSO) - timedelta(hours=2)
        self._trava = threading.Lock()

    def agora(self) -> datetime:
        with self._trava:
            return self._agora

    def proximo(self) -> str:
        with self._trava:
            self._agora += timedelta(milliseconds=500)
            return self._agora.isoformat(timespec="seconds")


# ----------------------------------------------------------------------
# O banco: encher e medir
# ----------------------------------------------------------------------

class Banco:
    def __init__(self, url: str) -> None:
        self.conexao = psycopg2.connect(url)
        self.conexao.autocommit = True
        self.status = dict(self._todas("SELECT enumerator, id FROM pix_status"))
        self.politica = self._uma("SELECT max(id) FROM fraud_policy")
        self.stats = self._liga_stats()

    def _uma(self, sql: str, params=None):
        with self.conexao.cursor() as cur:
            cur.execute(sql, params)
            linha = cur.fetchone()
            return linha[0] if linha else None

    def _todas(self, sql: str, params=None) -> list:
        with self.conexao.cursor() as cur:
            cur.execute(sql, params)
            return cur.fetchall()

    def executa(self, sql: str, params=None) -> None:
        with self.conexao.cursor() as cur:
            cur.execute(sql, params)

    def _liga_stats(self) -> bool:
        try:
            self.executa("CREATE EXTENSION IF NOT EXISTS pg_stat_statements")
            self.executa("SELECT pg_stat_statements_reset()")
            return True
        except psycopg2.Error:
            return False

    def linhas(self) -> int:
        return self._uma("SELECT count(*) FROM pix_analysis")

    def tamanhos(self) -> dict:
        return dict(self._todas(
            "SELECT relname, pg_total_relation_size(oid) FROM pg_class "
            "WHERE relname IN ('pix_analysis', 'pix_rule_result', 'pix_account')"
        ))

    def amostra_metadata(self) -> str:
        """O metadata de um Pix de verdade, para o semeado ter o mesmo tamanho em disco."""
        return self._uma("SELECT metadata::text FROM pix_analysis WHERE pix_id NOT LIKE 'escala-%' ORDER BY id DESC LIMIT 1")

    def conta(self, participante: str, numero: str, abertura: datetime, documento: str) -> int:
        return self._uma(
            "INSERT INTO pix_account (participant, branch, account_number, opening_date, owner_document) "
            "VALUES (%s, '0001', %s, %s, %s) ON CONFLICT (participant, branch, account_number) "
            "DO UPDATE SET participant = EXCLUDED.participant RETURNING id",
            (participante, numero, abertura, documento),
        )

    def _insere(self, origem_sql: str, params: dict) -> None:
        """Um INSERT ... SELECT com as colunas da analise; origem_sql devolve as linhas prontas."""
        self.executa(f"INSERT INTO pix_analysis ({COLUNAS}) {origem_sql}", params)

    def fundo(self, alvo: int, meta: str, lote: int = 100_000) -> float:
        """Enche o banco ate `alvo` Pix de clientes que a medicao nao usa.

        Cerca de 30 Pix por pagador em 180 dias, um terco para lojas e o resto
        para pessoas, cada pagador com o seu aparelho e o seu IP.
        """
        atual = self.linhas()
        inicio = time.perf_counter()
        pagadores = max(1000, alvo // 30)
        pessoas = max(500, pagadores // 2)
        lojas = max(100, alvo // 2000)
        abertura = datetime(2022, 1, 1, tzinfo=FUSO)
        contas = (("EP", pagadores, CASA, 11), ("ED", pessoas, OUTRA, 11), ("EM", lojas, OUTRA, 14))
        for prefixo, quantos, participante, tamanho in contas:
            self.executa(
                "INSERT INTO pix_account (participant, branch, account_number, opening_date, owner_document) "
                "SELECT %(part)s, '0001', %(pre)s || g, %(abre)s, %(dig)s || lpad(g::text, %(tam)s - 1, '0') "
                "FROM generate_series(0, %(n)s - 1) g ON CONFLICT DO NOTHING",
                {"part": participante, "pre": prefixo, "abre": abertura, "n": quantos, "tam": tamanho,
                 "dig": "7" if prefixo == "EP" else ("6" if prefixo == "ED" else "8")},
            )
        if atual >= alvo:
            return 0.0
        primeiro = self._uma("SELECT coalesce(max(id), 0) FROM pix_analysis") + 1
        falta = alvo - atual
        for comeco in range(0, falta, lote):
            fim = min(falta, comeco + lote)
            self._insere(
                """
                SELECT gen_random_uuid()::text, 'escala-fundo-' || (%(base)s + s.g), encode(sha256((%(base)s + s.g)::text::bytea), 'hex'),
                       CASE WHEN s.r < 0.9 THEN %(aprovado)s ELSE %(dois)s END, CASE WHEN s.r < 0.9 THEN 0 ELSE 40 END,
                       CASE WHEN s.r < 0.9 THEN 'none' ELSE 'facial' END, 'sem_alerta_relevante', 'SEM_ALERTA',
                       p.id, d.id, p.owner_document, d.owner_document, (1000 + floor(random() * random() * 200000))::bigint,
                       now() - random() * interval '180 days', 'escala-dev-' || s.pi, 'app', s.ip, network(set_masklen(s.ip, 24)),
                       -23.6 + random() * 0.1, -46.7 + random() * 0.1, NULL, NULL, 'unknown', %(politica)s, %(meta)s::jsonb
                FROM (
                    SELECT g, g %% %(pagadores)s AS pi, random() AS r,
                           CASE WHEN g %% 3 = 0 THEN 'EM' || (g %% %(lojas)s) ELSE 'ED' || ((g * 7) %% %(pessoas)s) END AS dnum,
                           ('10.' || ((g %% %(pagadores)s) / 65536 %% 256) || '.' || ((g %% %(pagadores)s) / 256 %% 256) || '.'
                            || ((g %% %(pagadores)s) %% 256))::inet AS ip
                    FROM generate_series(%(ini)s, %(fim)s - 1) g
                ) s
                JOIN pix_account p ON p.participant = %(casa)s AND p.branch = '0001' AND p.account_number = 'EP' || s.pi
                JOIN pix_account d ON d.participant = %(outra)s AND d.branch = '0001' AND d.account_number = s.dnum
                """,
                {"base": primeiro, "ini": comeco, "fim": fim, "pagadores": pagadores, "pessoas": pessoas, "lojas": lojas,
                 "aprovado": self.status["APPROVED"], "dois": self.status["TWO_FACTOR_REQUIRED"],
                 "politica": self.politica, "meta": meta, "casa": CASA, "outra": OUTRA},
            )
            print(f"    {atual + fim:>10,} Pix no banco".replace(",", "."), flush=True)
        self.executa("ANALYZE pix_analysis")
        self.executa("ANALYZE pix_account")
        return time.perf_counter() - inicio

    def historico(self, origem: dict, destinos: list, quantos: int, dias: int, meta: str, rotulo: str) -> None:
        """Da a um titular de medicao `quantos` Pix aprovados nos ultimos `dias`, terminando ontem."""
        if quantos <= 0:
            return
        self._insere(
            """
            SELECT gen_random_uuid()::text, 'escala-' || %(rotulo)s || '-' || g || '-' || %(sufixo)s, encode(sha256(random()::text::bytea), 'hex'),
                   %(aprovado)s, 0, 'none', 'pagamento_recorrente', 'SEM_ALERTA',
                   %(conta)s, (%(dids)s)[1 + g %% %(nd)s], %(doc)s, (%(ddocs)s)[1 + g %% %(nd)s],
                   (5000 + floor(random() * 25000))::bigint,
                   now() - interval '1 day' - random() * (%(dias)s * interval '1 day'), %(aparelho)s, 'app',
                   %(ip)s::inet, network(set_masklen(%(ip)s::inet, 24)), -23.56, -46.65, -23.56, -46.65, 'mock',
                   %(politica)s, %(meta)s::jsonb
            FROM generate_series(1, %(n)s) g
            """,
            {"rotulo": rotulo, "sufixo": uuid.uuid4().hex[:8], "aprovado": self.status["APPROVED"],
             "conta": origem["id"], "doc": origem["doc"], "dids": [d["id"] for d in destinos],
             "ddocs": [d["doc"] for d in destinos], "nd": len(destinos), "n": quantos, "dias": dias,
             "aparelho": origem["aparelho"], "ip": origem["ip"], "politica": self.politica, "meta": meta},
        )

    def recebimentos(self, destino: dict, quantos: int, dias: int, meta: str, ate: datetime, ultima_hora: bool = False,
                     ip: str = None) -> None:
        """`quantos` Pix aprovados de pagadores do fundo para `destino`, terminando em `ate`.

        `ate` e o relogio da medicao: as janelas do motor olham para tras a
        partir da data do Pix, entao o que foi semeado depois dela nao conta.
        """
        if quantos <= 0:
            return
        janela = "interval '55 minutes'" if ultima_hora else f"interval '{dias} days'"
        self._insere(
            f"""
            SELECT gen_random_uuid()::text, 'escala-recebe-' || g || '-' || %(sufixo)s, encode(sha256(random()::text::bytea), 'hex'),
                   %(aprovado)s, 0, 'none', 'sem_alerta_relevante', 'SEM_ALERTA',
                   p.id, %(did)s, p.owner_document, %(ddoc)s, (1000 + floor(random() * 30000))::bigint,
                   %(ate)s - random() * {janela}, 'escala-dev-r' || g, 'app',
                   coalesce(%(ip)s::inet, ('10.200.' || (g / 256 %% 256) || '.' || (g %% 256))::inet),
                   network(set_masklen(coalesce(%(ip)s::inet, ('10.200.' || (g / 256 %% 256) || '.' || (g %% 256))::inet), 24)),
                   -23.56, -46.65, NULL, NULL, 'unknown', %(politica)s, %(meta)s::jsonb
            FROM generate_series(1, %(n)s) g
            JOIN pix_account p ON p.participant = %(casa)s AND p.branch = '0001'
                 AND p.account_number = 'EP' || (g %% (SELECT count(*) FROM pix_account WHERE account_number LIKE 'EP%%'))
            """,
            {"sufixo": uuid.uuid4().hex[:8], "aprovado": self.status["APPROVED"], "did": destino["id"],
             "ddoc": destino["doc"], "n": quantos, "ip": ip, "ate": ate, "politica": self.politica, "meta": meta, "casa": CASA},
        )
        self.executa("ANALYZE pix_analysis")

    def zera_stats(self) -> None:
        if self.stats:
            self.executa("SELECT pg_stat_statements_reset()")

    def tempo_no_banco(self):
        """Milissegundos que o Postgres gastou executando consultas desde o ultimo zera_stats."""
        if not self.stats:
            return None
        return float(self._uma(
            "SELECT coalesce(sum(total_exec_time), 0) FROM pg_stat_statements "
            "WHERE dbid = (SELECT oid FROM pg_database WHERE datname = current_database())"
        ))

    def consultas_que_pesam(self, quantas: int = 6) -> list:
        if not self.stats:
            return []
        return self._todas(
            "SELECT calls, round(mean_exec_time::numeric, 2), round(total_exec_time::numeric, 1), "
            "regexp_replace(query, '\\s+', ' ', 'g') FROM pg_stat_statements "
            "WHERE dbid = (SELECT oid FROM pg_database WHERE datname = current_database()) "
            "AND query ILIKE '%%pix_analysis%%' AND query NOT ILIKE 'INSERT%%' AND query NOT ILIKE '%%generate_series%%' "
            "AND query NOT ILIKE 'ANALYZE%%' AND query <> 'SELECT count(*) FROM pix_analysis' "
            "ORDER BY total_exec_time DESC LIMIT %s",
            (quantas,),
        )

    def disco_por_pix(self) -> tuple:
        """Bytes por Pix de verdade: a linha da analise e, se a tabela existir, as linhas de regra dele."""
        analise = self._uma(
            "SELECT avg(pg_column_size(a.*)) FROM pix_analysis a WHERE pix_id NOT LIKE 'escala-%%'"
        )
        if self._uma("SELECT to_regclass('pix_rule_result')") is None:
            return float(analise or 0), 0.0, 0.0
        regra = self._uma(
            "SELECT pg_total_relation_size('pix_rule_result')::numeric / nullif((SELECT count(DISTINCT analysis_id) "
            "FROM pix_rule_result), 0)"
        )
        por_analise = self._uma("SELECT count(*)::numeric / nullif(count(DISTINCT analysis_id), 0) FROM pix_rule_result")
        return float(analise or 0), float(regra or 0), float(por_analise or 0)


# ----------------------------------------------------------------------
# A API
# ----------------------------------------------------------------------

class Api:
    def __init__(self, url: str, token: str, relogio: Relogio) -> None:
        self.url = url.rstrip("/")
        self.token = token
        self.relogio = relogio
        self._local = threading.local()

    def _sessao(self) -> requests.Session:
        if not hasattr(self._local, "sessao"):
            sessao = requests.Session()
            sessao.headers.update({"INTERNAL-TOKEN": self.token, "Content-Type": "application/json"})
            self._local.sessao = sessao
        return self._local.sessao

    def pix(self, origem: dict, destino: dict, valor: int, ip: str = None) -> tuple:
        """Manda um Pix e devolve (ms ponta a ponta, ms do motor, status HTTP)."""
        corpo = {
            "id": "medicao-" + uuid.uuid4().hex,
            "amount": valor,
            "transaction_date": self.relogio.proximo(),
            "source_account": {"branch": "0001", "account_number": origem["numero"], "opening_date": origem["abertura"],
                               "owner": {"document_number": origem["doc"]}},
            "destination_account": {"participant": destino["participante"], "branch": "0001",
                                    "account_number": destino["numero"], "opening_date": destino["abertura"],
                                    "owner": {"document_number": destino["doc"]}},
            "source": {"device_id": origem["aparelho"], "channel": "app", "ip": ip or origem["ip"], "geolocation": SP_GPS},
        }
        inicio = time.perf_counter()
        resposta = self._sessao().post(self.url + "/pix/transaction", json=corpo, timeout=60)
        ponta = (time.perf_counter() - inicio) * 1000
        motor = None
        if resposta.status_code in (200, 201):
            motor = resposta.json().get("metadata", {}).get("latency_ms")
        return ponta, motor, resposta.status_code


# ----------------------------------------------------------------------
# Os personagens da medicao
# ----------------------------------------------------------------------

class Elenco:
    """Titulares e destinos com documento valido, gravados no banco antes de pagar."""

    def __init__(self, banco: Banco, semente: int) -> None:
        self.banco = banco
        self.rng = random.Random(semente)
        self._n = 0
        # O numero da conta do contrato so tem digitos. A rodada entra no
        # numero para duas rodadas no mesmo banco nao pegarem a mesma conta.
        self._rodada = int(time.time()) % 100000

    def _numero(self, tipo: str) -> str:
        self._n += 1
        return f"{tipo}{self._rodada:05d}{self._n:06d}"

    def destino(self, pj: bool = False, dias_de_conta: int = 900) -> dict:
        abertura = datetime.now(FUSO) - timedelta(days=dias_de_conta)
        doc = cnpj(self.rng) if pj else cpf(self.rng)
        numero = self._numero("4")
        conta = self.banco.conta(OUTRA, numero, abertura, doc)
        return {"id": conta, "doc": doc, "numero": numero, "participante": OUTRA,
                "abertura": abertura.isoformat(timespec="seconds")}

    def titular(self, ip: str = None) -> dict:
        abertura = datetime.now(FUSO) - timedelta(days=800)
        doc = cpf(self.rng)
        numero = self._numero("5")
        conta = self.banco.conta(CASA, numero, abertura, doc)
        n = self._n
        return {"id": conta, "doc": doc, "numero": numero, "abertura": abertura.isoformat(timespec="seconds"),
                "aparelho": f"medicao-dev-{n}", "ip": ip or f"198.51.100.{20 + n % 200}"}


# ----------------------------------------------------------------------
# As medicoes
# ----------------------------------------------------------------------

def resumo(amostras: list) -> dict:
    validas = sorted(a for a in amostras if a is not None)
    if not validas:
        return {"p50": None, "p95": None, "max": None, "n": 0}

    def pct(p):
        return validas[min(len(validas) - 1, int(round(p * (len(validas) - 1))))]

    return {"p50": statistics.median(validas), "p95": pct(0.95), "max": validas[-1], "n": len(validas)}


def mede(api: Api, banco: Banco, pedidos: list) -> dict:
    """Manda os pedidos em sequencia: (origem, destino, valor, ip).

    `banco` e o tempo medio que o Postgres gastou por Pix, somando todas as
    consultas e gravacoes: e o que separa "o banco ficou lento" de "o Python
    ficou lento".
    """
    antes = banco.tempo_no_banco()
    pontas, motores, erros = [], [], 0
    for origem, destino, valor, ip in pedidos:
        ponta, motor, http = api.pix(origem, destino, valor, ip)
        if http not in (200, 201):
            erros += 1
            continue
        pontas.append(ponta)
        motores.append(motor)
    depois = banco.tempo_no_banco()
    no_banco = None if antes is None or not pontas else (depois - antes) / len(pedidos)
    return {"ponta": resumo(pontas), "motor": resumo(motores), "erros": erros, "banco": no_banco}


def concorrencia(api: Api, pares: list, por_chamador: int) -> dict:
    """Cada chamador manda `por_chamador` Pix seguidos; todos ao mesmo tempo."""
    tempos, erros = [], []
    largada = threading.Barrier(len(pares))

    def chamador(par):
        origem, destino = par
        largada.wait()
        for _ in range(por_chamador):
            ponta, _motor, http = api.pix(origem, destino, 9000)
            (tempos if http in (200, 201) else erros).append(ponta)

    inicio = time.perf_counter()
    with ThreadPoolExecutor(max_workers=len(pares)) as pool:
        list(pool.map(chamador, pares))
    duracao = time.perf_counter() - inicio
    return {"pix_por_s": len(tempos) / duracao, "ponta": resumo(tempos), "erros": len(erros)}


def ms(valor) -> str:
    return "-" if valor is None else f"{valor:,.0f}".replace(",", ".")


def linha_tempo(r: dict) -> str:
    banco = "-" if r["banco"] is None else f"{r['banco']:.1f}".replace(".", ",")
    return (f"{ms(r['motor']['p50'])} | {ms(r['motor']['p95'])} | {ms(r['ponta']['p50'])} | {ms(r['ponta']['p95'])} | "
            f"{banco} | {r['erros']}")


def mb(valor) -> str:
    return f"{valor / 1024 / 1024:,.0f} MB".replace(",", ".")


def consultas(banco: Banco, saida: list, titulo: str) -> None:
    linhas = banco.consultas_que_pesam()
    if not linhas:
        return
    saida += ["", f"**Consultas que mais pesaram: {titulo}**", "",
              "| chamadas | media (ms) | total (ms) | consulta |", "|---:|---:|---:|---|"]
    for chamadas, media, total, texto in linhas:
        texto = texto.replace("|", "\\|")
        saida.append(f"| {chamadas} | {media} | {total} | `{texto[:150]}` |")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--tamanhos", default="0,100000,1000000",
                        help="Pix no banco em cada estagio (o fundo so cresce)")
    parser.add_argument("--pesados", default="1000,10000,50000",
                        help="tamanhos da entidade pesada, medidos no maior estagio")
    parser.add_argument("--amostras", type=int, default=30, help="Pix medidos por perfil em cada estagio")
    parser.add_argument("--chamadores", default="1,4,8,16", help="chamadores simultaneos no teste de concorrencia")
    parser.add_argument("--por-chamador", type=int, default=15)
    parser.add_argument("--url", default=f"http://127.0.0.1:{os.environ.get('ANTIFRAUD_API_PORT', '3020')}")
    parser.add_argument("--banco", default=None, help="URL do Postgres (padrao: DB_PORT do ambiente)")
    parser.add_argument("--semente", type=int, default=7)
    parser.add_argument("--secoes", default="volume,pagador,loja,ip,rede,concorrencia",
                        help="quais medicoes rodar, separadas por virgula")
    args = parser.parse_args()

    host = os.environ.get("SERVER_LOCALHOST", "127.0.0.1")
    url_banco = args.banco or f"postgresql://bootcamp:bootcamp@{host}:{os.environ.get('DB_PORT', '5432')}/antifraud"
    if not any(local in url_banco for local in ("@127.0.0.1:", "@localhost:", "@0.0.0.0:")):
        print("Recusado: esta ferramenta escreve direto no banco, e so roda contra um Postgres local.")
        return 2

    tamanhos = [int(t) for t in args.tamanhos.split(",")]
    secoes = set(args.secoes.split(","))
    pesados = [int(t) for t in args.pesados.split(",") if t]
    chamadores = [int(c) for c in args.chamadores.split(",")]
    relogio = Relogio()
    banco = Banco(url_banco)
    api = Api(args.url, os.environ.get("INTERNAL_TOKEN", "default_token"), relogio)
    elenco = Elenco(banco, args.semente)

    # Um Pix de verdade antes de tudo: da o metadata de referencia e a conta de disco.
    loja = elenco.destino(pj=True)
    aquecimento = elenco.titular()
    for _ in range(5):
        api.pix(aquecimento, loja, 9000)
    meta = banco.amostra_metadata()
    if meta is None:
        print("A API nao gravou nenhum Pix. Ela esta de pe em", args.url, "?")
        return 1

    saida = ["# Escala da antifraud-api", "",
             f"{datetime.now(FUSO):%d/%m/%Y %H:%M}, {args.amostras} Pix por perfil, pg_stat_statements "
             f"{'ligado' if banco.stats else 'desligado (use tools/escala/compose.escala.yml)'}.", "",
             "Tempos em ms. **motor** e o `latency_ms` que a API devolve (as regras e as consultas de historico); "
             "**ponta** e o Pix inteiro visto de fora, com HTTP, a gravacao e o commit. "
             "**no banco** e a media, por Pix, do tempo que o Postgres gastou em todas as consultas e gravacoes "
             "(pg_stat_statements).", "",
             "## 1. Volume total", "",
             "Cliente comum: 40 Pix em 90 dias para 3 destinos de sempre. Cliente novo: nenhum historico.", "",
             "| Pix no banco | tabela pix_analysis | encher levou | comum motor p50 | p95 | ponta p50 | p95 | no banco "
             "| erros | novo motor p50 | p95 | ponta p50 | p95 | no banco | erros |",
             "|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|"]

    if "volume" in secoes:
        for alvo in tamanhos:
            print(f"Estagio de {alvo:,} Pix".replace(",", "."), flush=True)
            levou = banco.fundo(alvo, meta)
            destinos = [elenco.destino() for _ in range(3)]
            comuns = [elenco.titular() for _ in range(args.amostras)]
            for t in comuns:
                banco.historico(t, destinos, 40, 90, meta, "comum")
            banco.executa("ANALYZE pix_analysis")
            novos = [elenco.titular() for _ in range(args.amostras)]
            banco.zera_stats()
            comum = mede(api, banco, [(t, destinos[i % 3], 15000, None) for i, t in enumerate(comuns)])
            novo = mede(api, banco, [(t, destinos[i % 3], 15000, None) for i, t in enumerate(novos)])
            tam = banco.tamanhos()
            saida.append(f"| {banco.linhas():,} | {mb(tam.get('pix_analysis', 0))} | {levou:,.0f} s | {linha_tempo(comum)} | "
                         f"{linha_tempo(novo)} |".replace(",", "."))
            ultimo_estagio = alvo
        consultas(banco, saida, f"cliente comum e novo com {ultimo_estagio:,} Pix no banco".replace(",", "."))

    if "volume" not in secoes:
        # As entidades pesadas recebem Pix das contas de fundo, que o estagio
        # de volume cria; sem ele, cria so as contas, sem encher.
        banco.fundo(0, meta)

    saida += ["", "## 2. Entidade pesada", "",
              f"Com o banco no maior estagio. Cada linha mede {args.amostras} Pix contra a mesma entidade.", "",
              "| entidade | tamanho | motor p50 | p95 | ponta p50 | p95 | no banco | erros |",
              "|---|---:|---:|---:|---:|---:|---:|---:|"]

    if "pagador" in secoes:
        # Pagador pesado: um titular so, com cada vez mais historico em 180 dias.
        destinos = [elenco.destino() for _ in range(20)]
        pesado = elenco.titular()
        tem = 0
        for tamanho in pesados:
            banco.historico(pesado, destinos, tamanho - tem, 170, meta, "pesado")
            tem = tamanho
            banco.executa("ANALYZE pix_analysis")
            banco.zera_stats()
            r = mede(api, banco, [(pesado, destinos[i % 20], 15000, None) for i in range(args.amostras)])
            saida.append(f"| pagador com historico | {tamanho:,} Pix | {linha_tempo(r)} |".replace(",", "."))
        consultas(banco, saida, f"pagador com {tem:,} Pix".replace(",", "."))

    if "loja" in secoes:
        # Loja quente: recebe de muitos pagadores em 30 dias; quem paga e cliente comum.
        loja = elenco.destino(pj=True)
        tem = 0
        for tamanho in pesados:
            banco.recebimentos(loja, tamanho - tem, 30, meta, relogio.agora())
            tem = tamanho
            banco.zera_stats()
            pagadores = [elenco.titular() for _ in range(args.amostras)]
            for t in pagadores:
                banco.historico(t, [loja], 10, 60, meta, "cliente-da-loja")
            r = mede(api, banco, [(t, loja, 15000, None) for t in pagadores])
            saida.append(f"| loja que recebe em 30 dias | {tamanho:,} Pix | {linha_tempo(r)} |".replace(",", "."))
        consultas(banco, saida, f"loja com {tem:,} Pix recebidos".replace(",", "."))

    if "ip" in secoes:
        # IP de operadora (CGNAT): muitos titulares no mesmo IP na ultima hora.
        ip_cgnat = "198.51.100.250"
        destino_cgnat = elenco.destino()
        tem = 0
        for tamanho in [p // 10 for p in pesados]:
            banco.recebimentos(elenco.destino(), tamanho - tem, 1, meta, relogio.agora(), ultima_hora=True, ip=ip_cgnat)
            tem = tamanho
            banco.zera_stats()
            pagadores = [elenco.titular(ip=ip_cgnat) for _ in range(args.amostras)]
            r = mede(api, banco, [(t, destino_cgnat, 15000, ip_cgnat) for t in pagadores])
            saida.append(f"| IP com Pix na ultima hora | {tamanho:,} Pix | {linha_tempo(r)} |".replace(",", "."))
        consultas(banco, saida, f"IP com {tem:,} Pix na ultima hora".replace(",", "."))

    if "rede" in secoes:
        # Rede desconhecida: o IP nao esta na tabela de faixas, e o motor aprende o
        # lugar pela mediana do GPS dos Pix da mesma /24 nos ultimos 30 dias.
        rede = "10.77.1"
        destino_rede = elenco.destino()
        tem = 0
        for tamanho in pesados:
            banco.recebimentos(elenco.destino(), tamanho - tem, 29, meta, relogio.agora(), ip=f"{rede}.7")
            tem = tamanho
            banco.zera_stats()
            pagadores = [elenco.titular(ip=f"{rede}.{20 + i}") for i in range(args.amostras)]
            r = mede(api, banco, [(t, destino_rede, 15000, None) for t in pagadores])
            saida.append(f"| rede /24 fora da tabela com GPS em 30 dias | {tamanho:,} Pix | {linha_tempo(r)} |".replace(",", "."))
        consultas(banco, saida, f"rede /24 fora da tabela com {tem:,} Pix com GPS".replace(",", "."))

    if "concorrencia" in secoes:
        # Concorrencia: destinos diferentes, e todos para a mesma loja (a trava do recebedor).
        saida += ["", "## 3. Concorrencia", "",
                  f"Cada chamador e um titular comum e manda {args.por_chamador} Pix seguidos; todos largam juntos.", "",
                  "| chamadores | destino | Pix por segundo | ponta p50 | p95 | erros |", "|---:|---|---:|---:|---:|---:|"]
        destinos_conc = [elenco.destino() for _ in range(max(chamadores))]
        loja_conc = elenco.destino(pj=True)
        for k in chamadores:
            for rotulo, mesma in (("um para cada", False), ("todos na mesma loja", True)):
                titulares = [elenco.titular() for _ in range(k)]
                for t in titulares:
                    banco.historico(t, destinos_conc, 20, 60, meta, "concorrencia")
                pares = [(t, loja_conc if mesma else destinos_conc[i]) for i, t in enumerate(titulares)]
                r = concorrencia(api, pares, args.por_chamador)
                saida.append(f"| {k} | {rotulo} | {r['pix_por_s']:.1f} | {ms(r['ponta']['p50'])} | {ms(r['ponta']['p95'])} | "
                             f"{r['erros']} |")

    analise, regra, por = banco.disco_por_pix()
    tam = banco.tamanhos()
    saida += ["", "## 4. Disco", "",
              f"Num Pix de verdade, a linha da analise ocupa {ms(analise)} bytes (sem indices)"
              + (f"; as {por:.0f} linhas de regra dele, com indices, {ms(regra)} bytes." if por else
                 "; nao ha mais linha por regra (pix_rule_result)."),
              f"Tamanho final: pix_analysis {mb(tam.get('pix_analysis', 0))}, pix_rule_result "
              f"{mb(tam.get('pix_rule_result', 0))}, pix_account {mb(tam.get('pix_account', 0))}."]

    texto = "\n".join(saida) + "\n"
    print()
    print(texto)
    pasta = RAIZ / "tools" / "resultados"
    pasta.mkdir(exist_ok=True)
    arquivo = pasta / f"escala-{datetime.now(FUSO):%Y%m%d-%H%M}.md"
    arquivo.write_text(texto, encoding="utf-8")
    print(f"Relatorio em {arquivo.relative_to(RAIZ)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
