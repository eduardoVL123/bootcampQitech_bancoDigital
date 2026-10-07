"""Ferramentas dos testes da onboarding-api (plano em docs/testes/onboarding-api.md).

O teste fala com a onboarding-api sozinha, sem o gateway na frente. Por isso
ele manda o que o gateway mandaria: o INTERNAL-TOKEN, a X-Idempotency-Key e o
X-Forwarded-For com o IP de quem chamou.

O que tem aqui:
  - Onboarding: uma funcao por rota da API;
  - pessoa_fisica() e pessoa_juridica(): um cadastro valido, com documento novo;
  - cabecalhos_do_gateway(): o que o gateway manda em todo pedido;
  - credenciais: a do cliente vem da API; as outras o teste fabrica;
  - imagens do RG: JPEG, PNG e PDF de qualquer tamanho, feitos na hora;
  - datas: "hoje" e o dia de Sao Paulo, como na API, e o relogio simulado;
  - espera_ate e espera_etapa: esperam o efeito do worker, que nao tem rota;
"""
import base64
import json
import random
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta, timezone
from os import environ
from threading import Barrier
from uuid import uuid4
from zoneinfo import ZoneInfo

import jwt
import requests

from tests.utils.random_generator import RandomGenerator


TOKEN_DO_APLICATIVO = environ.get("INTERNAL_TOKEN", "default_token")

# O mesmo segredo que a API usa para assinar a credencial (RFC 05). O teste
# precisa dele para conferir a assinatura e para fabricar credenciais.
SEGREDO_DA_CREDENCIAL = environ.get("AUTH_SECRET", "auth_secret_de_estudo_troque_em_producao_0123456789")

# "Hoje" e o dia em Sao Paulo, na API e no teste (decisao D18). Sem isso, o
# teste da borda dos 18 anos falharia entre 21h e meia-noite.
FUSO_DO_BANCO = ZoneInfo("America/Sao_Paulo")

# Os testes de falha simulada so rodam com a variavel ligada na API e no pytest.
FALHA_SIMULADA_LIGADA = environ.get("FAULT_INJECTION_ENABLED") == "true"

# O relogio simulado (decisao D16) tambem: com ele, o teste diz que o pedido
# aconteceu no passado, pelo cabecalho X-Simulated-Now.
RELOGIO_SIMULADO_LIGADO = environ.get("SIMULATED_CLOCK_ENABLED") == "true"

# O worker vence as aberturas a cada minuto. O teste espera uma passada
# inteira e mais um pouco.
ESPERA_PELO_WORKER_SEGUNDOS = 90

PRAZO_DA_ABERTURA_MINUTOS = 20
VALIDADE_DA_CREDENCIAL_SEGUNDOS = 3600

API_FORA_DO_AR = (
    "Nao consegui falar com a onboarding-api em {endereco}.\n"
    "Ela precisa estar de pe pros testes rodarem. Suba com:  docker compose up -d --build --wait"
)


# ----------------------------------------------------------------------
# A API: uma funcao por rota
# ----------------------------------------------------------------------

def endereco_da_api() -> str:
    host = environ.get("SERVER_LOCALHOST", "127.0.0.1")
    porta = environ.get("ONBOARDING_API_PORT", "3005")
    return f"http://{host}:{porta}"


class Onboarding:
    """Cada funcao devolve a resposta inteira (status, corpo e cabecalhos),
    porque varios testes conferem cabecalhos, e nao so o corpo."""

    @staticmethod
    def envia(metodo: str, caminho: str, cabecalhos: dict = None, **extras) -> requests.Response:
        endereco = endereco_da_api()

        try:
            return requests.request(metodo, f"{endereco}{caminho}", headers=cabecalhos, timeout=30, **extras)
        except requests.exceptions.ConnectionError:
            raise RuntimeError(API_FORA_DO_AR.format(endereco=endereco)) from None

    @staticmethod
    def pagina_inicial() -> requests.Response:
        """GET /"""
        return Onboarding.envia("GET", "/")

    @staticmethod
    def health_check() -> requests.Response:
        """GET /health_check"""
        return Onboarding.envia("GET", "/health_check")

    @staticmethod
    def cadastra(dados, cabecalhos: dict = None) -> requests.Response:
        """POST /onboarding: cadastra o cliente e comeca a abertura."""
        if cabecalhos is None:
            cabecalhos = cabecalhos_do_gateway()

        return Onboarding.envia("POST", "/onboarding", cabecalhos, json=dados)

    @staticmethod
    def consulta_abertura(chave_da_abertura: str, credencial: str) -> requests.Response:
        """GET /onboarding/{onboarding_key}"""
        return Onboarding.envia("GET", f"/onboarding/{chave_da_abertura}", cabecalhos_com_credencial(credencial))

    @staticmethod
    def consulta_cliente(chave_do_cliente: str, credencial: str) -> requests.Response:
        """GET /customer/{customer_key}"""
        return Onboarding.envia("GET", f"/customer/{chave_do_cliente}", cabecalhos_com_credencial(credencial))

    @staticmethod
    def envia_rg(chave_da_abertura: str, credencial: str, arquivos: list, cabecalhos: dict = None) -> requests.Response:
        """PUT /onboarding/{onboarding_key}/document: manda as imagens do RG.

        `arquivos` é uma lista de imagem(...). Lista vazia manda o pedido sem
        corpo nenhum. Sem `cabecalhos`, vai o que o gateway mandaria."""
        if cabecalhos is None:
            cabecalhos = cabecalhos_do_gateway()

        if credencial is not None:
            cabecalhos["Authorization"] = f"Bearer {credencial}"

        return Onboarding.envia("PUT", f"/onboarding/{chave_da_abertura}/document", cabecalhos, files=arquivos)

    @staticmethod
    def comeca_abertura(dados: dict = None, cabecalhos: dict = None) -> dict:
        """Prepara o mundo do teste: uma abertura nova em DRAFT, criada pela
        propria API (nunca por INSERT no banco). Devolve o corpo do 201."""
        if dados is None:
            dados = pessoa_fisica()

        resposta = Onboarding.cadastra(dados, cabecalhos)
        assert resposta.status_code == 201, resposta.text
        return resposta.json()


# ----------------------------------------------------------------------
# Cabecalhos
# ----------------------------------------------------------------------

def nova_chave() -> str:
    """Uma X-Idempotency-Key nova: um UUID."""
    return str(uuid4())


def ip_aleatorio() -> str:
    """Um IP de origem por teste, para os contadores de um teste nao atrapalharem outro."""
    return f"10.{random.randrange(256)}.{random.randrange(256)}.{random.randrange(1, 255)}"


def cabecalhos_do_gateway(chave: str = None, ip: str = None, extras: dict = None) -> dict:
    """O que o gateway manda para a onboarding-api em todo pedido."""
    cabecalhos = {
        "INTERNAL-TOKEN": TOKEN_DO_APLICATIVO,
        "X-Idempotency-Key": chave if chave is not None else nova_chave(),
        "X-Forwarded-For": ip if ip is not None else ip_aleatorio(),
    }

    if extras:
        cabecalhos.update(extras)

    return cabecalhos


def cabecalhos_com_credencial(credencial: str = None) -> dict:
    """Cabecalhos de uma leitura: o token do aplicativo e, se houver, a credencial."""
    cabecalhos = {"INTERNAL-TOKEN": TOKEN_DO_APLICATIVO}

    if credencial is not None:
        cabecalhos["Authorization"] = f"Bearer {credencial}"

    return cabecalhos


# ----------------------------------------------------------------------
# Dados do cadastro
# ----------------------------------------------------------------------

def pessoa_fisica(**trocas) -> dict:
    """Uma PF valida, com CPF novo a cada chamada. O teste troca o campo que quer provocar."""
    dados = {
        "type": "PF",
        "name": "Ana Souza",
        "document_number": RandomGenerator.generate_cpf(),
        "birth_date": "1990-05-17",
        "declared_monthly_income_cents": 500000,
        "occupation": "Analista de sistemas",
        "pep_self_declared": False,
    }
    dados.update(trocas)
    return dados


def pessoa_juridica(**trocas) -> dict:
    """Uma PJ valida, com CNPJ novo a cada chamada."""
    dados = {
        "type": "PJ",
        "name": "Padaria Souza Ltda",
        "document_number": RandomGenerator.generate_cnpj(),
        "opening_date": "2015-03-10",
        "declared_monthly_income_cents": 8000000,
        "pep_self_declared": False,
    }
    dados.update(trocas)
    return dados


def sem(dados: dict, campo: str) -> dict:
    """Os mesmos dados, sem um campo."""
    copia = dict(dados)
    copia.pop(campo)
    return copia


def com_digito_errado(documento: str) -> str:
    """O mesmo CPF ou CNPJ com o ultimo digito trocado: formato certo, numero que nao existe."""
    ultimo = int(documento[-1])
    return documento[:-1] + str((ultimo + 1) % 10)


def so_digitos(documento: str) -> str:
    return documento.replace(".", "").replace("-", "").replace("/", "")


def novo_cpf() -> str:
    return RandomGenerator.generate_cpf()


def novo_cnpj() -> str:
    return RandomGenerator.generate_cnpj()


# ----------------------------------------------------------------------
# Imagens do RG
# ----------------------------------------------------------------------

LIMITE_DA_IMAGEM_BYTES = 5 * 1024 * 1024

# Os primeiros bytes de cada formato. É por eles que a API reconhece o tipo,
# e não pelo nome do arquivo nem pelo Content-Type que o cliente declara.
INICIO_DO_JPEG = b"\xff\xd8\xff\xe0\x00\x10JFIF\x00"
INICIO_DO_PNG = b"\x89PNG\r\n\x1a\n"
INICIO_DO_PDF = b"%PDF-1.4\n"


def com_tamanho(inicio: bytes, tamanho: int) -> bytes:
    """O começo do formato, completado com zeros até o tamanho pedido."""
    return inicio + b"\x00" * (tamanho - len(inicio))


def bytes_de_jpeg(tamanho: int = 2048) -> bytes:
    return com_tamanho(INICIO_DO_JPEG, tamanho)


def bytes_de_png(tamanho: int = 2048) -> bytes:
    return com_tamanho(INICIO_DO_PNG, tamanho)


def bytes_de_pdf(tamanho: int = 2048) -> bytes:
    return com_tamanho(INICIO_DO_PDF, tamanho)


def imagem(lado: str, conteudo: bytes = None, nome: str = None, tipo: str = "image/jpeg") -> tuple:
    """Um arquivo do envio do RG, no formato do requests: (campo, (nome, bytes, tipo)).

    `lado` é o campo do formulário: front, back ou both. Sem `conteudo`, vai
    um JPEG pequeno e válido."""
    if conteudo is None:
        conteudo = bytes_de_jpeg()

    if nome is None:
        nome = f"rg-{lado}.jpg"

    return (lado, (nome, conteudo, tipo))


def imagens(*lados: str) -> list:
    """Um JPEG válido para cada lado pedido: imagens("front", "back")."""
    return [imagem(lado) for lado in lados]


# ----------------------------------------------------------------------
# Datas
# ----------------------------------------------------------------------

def hoje() -> date:
    return datetime.now(FUSO_DO_BANCO).date()


def anos_antes(dia: date, anos: int) -> date:
    """O mesmo dia, `anos` anos antes. Quem faria aniversario num 29 de
    fevereiro que nao existe naquele ano fica com o dia 28."""
    try:
        return dia.replace(year=dia.year - anos)
    except ValueError:
        return dia.replace(year=dia.year - anos, day=28)


def nascido_para_completar_hoje(anos: int) -> str:
    """A data de nascimento de quem completa `anos` anos hoje."""
    return anos_antes(hoje(), anos).isoformat()


def nascido_para_completar_amanha(anos: int) -> str:
    """A data de nascimento de quem so completa `anos` anos amanha."""
    return (anos_antes(hoje(), anos) + timedelta(days=1)).isoformat()


def amanha() -> str:
    return (hoje() + timedelta(days=1)).isoformat()


def aberta_ha_dias(dias: int) -> str:
    """A data de abertura de uma empresa aberta há `dias` dias, no dia de São Paulo."""
    return (hoje() - timedelta(days=dias)).isoformat()


def no_passado(minutos: float) -> dict:
    """O cabecalho que faz o pedido acontecer `minutos` atras (decisao D16).
    So vale com SIMULATED_CLOCK_ENABLED=true na API."""
    momento = datetime.now(timezone.utc) - timedelta(minutes=minutos)
    return {"X-Simulated-Now": momento.isoformat()}


# ----------------------------------------------------------------------
# Esperar o worker
# ----------------------------------------------------------------------

def espera_ate(consulta, condicao, limite_segundos: float, intervalo_segundos: float = 0.5):
    """Repete a consulta ate a condicao valer e devolve o ultimo resultado.

    O worker roda em outro processo, sem rota para o teste chamar: o teste
    so ve o efeito dele, consultando a API de novo ate o efeito aparecer.
    Passou do limite, o teste falha mostrando o que viu por ultimo."""
    fim = time.monotonic() + limite_segundos

    while True:
        resultado = consulta()
        if condicao(resultado):
            return resultado
        if time.monotonic() > fim:
            raise AssertionError(f"Passaram {limite_segundos} s e a condicao nao valeu. Ultimo resultado: {resultado}")
        time.sleep(intervalo_segundos)


# A análise do KYC acontece no worker. O teste repete o GET até a abertura
# chegar a uma das etapas esperadas (o wait_for_status do plano).
ESPERA_PELA_ANALISE_SEGUNDOS = float(environ.get("ESPERA_PELA_ANALISE_SEGUNDOS", "20"))


def espera_etapa(abertura: dict, etapas: set, limite_segundos: float = ESPERA_PELA_ANALISE_SEGUNDOS) -> dict:
    """Consulta a abertura até ela chegar a uma das `etapas` e devolve o corpo do GET."""
    def consulta():
        resposta = Onboarding.consulta_abertura(abertura["onboarding_key"], abertura["access_token"])
        assert resposta.status_code == 200, resposta.text
        return resposta.json()

    return espera_ate(consulta, lambda corpo: corpo["status"] in etapas, limite_segundos)


# ----------------------------------------------------------------------
# Credenciais
# ----------------------------------------------------------------------

def le_credencial(credencial: str) -> dict:
    """Confere a assinatura com o segredo e devolve os campos do JWT."""
    return jwt.decode(credencial, SEGREDO_DA_CREDENCIAL, algorithms=["HS256"])


def fabrica_credencial(
    sub: str,
    escopo: str,
    validade_segundos: int = VALIDADE_DA_CREDENCIAL_SEGUNDOS,
    emitida_ha_segundos: int = 0,
    segredo: str = SEGREDO_DA_CREDENCIAL,
) -> str:
    """Fabrica uma credencial, como faria quem a emite. Serve para a de
    compliance (decisao D3) e para as vencidas e adulteradas."""
    emitida_em = int(datetime.now(FUSO_DO_BANCO).timestamp()) - emitida_ha_segundos
    campos = {
        "sub": sub,
        "scope": escopo,
        "iat": emitida_em,
        "exp": emitida_em + validade_segundos,
        "jti": str(uuid4()),
    }
    return jwt.encode(campos, segredo, algorithm="HS256")


def credencial_de_compliance() -> str:
    return fabrica_credencial("compliance:ana.oliveira", "compliance")


def credencial_vencida(chave_do_cliente: str) -> str:
    return fabrica_credencial(chave_do_cliente, "onboarding", emitida_ha_segundos=VALIDADE_DA_CREDENCIAL_SEGUNDOS + 60)


def credencial_com_outro_segredo(chave_do_cliente: str) -> str:
    return fabrica_credencial(chave_do_cliente, "onboarding", segredo="outro_segredo_que_ninguem_conhece_0123456789")


def credencial_sem_assinatura(chave_do_cliente: str) -> str:
    """Um JWT com alg none e sem assinatura: o ataque classico. Montado a mao,
    porque nenhuma biblioteca honesta assina com 'none'."""
    def codifica(parte: dict) -> str:
        return base64.urlsafe_b64encode(json.dumps(parte).encode()).rstrip(b"=").decode()

    agora = int(datetime.now(FUSO_DO_BANCO).timestamp())
    cabecalho = {"alg": "none", "typ": "JWT"}
    campos = {"sub": chave_do_cliente, "scope": "onboarding", "iat": agora, "exp": agora + 3600, "jti": str(uuid4())}
    return f"{codifica(cabecalho)}.{codifica(campos)}."


# ----------------------------------------------------------------------
# Pedidos ao mesmo tempo
# ----------------------------------------------------------------------

def ao_mesmo_tempo(chamadas: list) -> list:
    """Dispara todas as chamadas no mesmo instante e devolve as respostas na mesma ordem.

    Um laco comum mandaria um pedido depois do outro, e isso testa a regra,
    e nao a concorrencia. Aqui cada chamada roda na propria thread e espera
    na barreira ate todas estarem prontas; so entao saem juntas.
    """
    barreira = Barrier(len(chamadas))

    def espera_e_chama(chamada):
        barreira.wait()
        return chamada()

    with ThreadPoolExecutor(max_workers=len(chamadas)) as threads:
        futuros = [threads.submit(espera_e_chama, chamada) for chamada in chamadas]
        return [futuro.result() for futuro in futuros]


# ----------------------------------------------------------------------
# Leitura da resposta
# ----------------------------------------------------------------------

def campos_e_regras(corpo: dict) -> list:
    """Os pares (campo, regra) da lista `errors`, sem a mensagem."""
    return [(erro["field"], erro["rule"]) for erro in corpo["errors"]]
