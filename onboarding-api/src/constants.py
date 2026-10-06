import os


SERVICE_ROOT = os.path.abspath(os.path.dirname(__file__))

# Onde moram os arquivos de schema: os .json que descrevem o formato de
# cada requisicao. Quem le essa pasta e o src/utils/schema_handler.py.
SCHEMA_PATH = os.path.join(SERVICE_ROOT, "schemas")

APP_ENV = os.environ.get("APP_ENV", "local")
SERVICE_NAME = os.environ.get("SERVICE_NAME", "onboarding-api")

DATABASE_URL = os.environ.get("DATABASE_URL")
INTERNAL_TOKEN = os.environ.get("INTERNAL_TOKEN")

# O segredo que assina o access_token (HMAC-SHA256). Todas as APIs conhecem
# o mesmo valor e conferem a credencial sozinhas (RFC 00).
AUTH_SECRET = os.environ.get("AUTH_SECRET")
ACCESS_TOKEN_LIFETIME_SECONDS = 3600

# A pessoa tem 20 minutos para terminar a parte dela (RFC 05, Prazo).
ONBOARDING_TIMEOUT_MINUTES = int(os.environ.get("ONBOARDING_TIMEOUT_MINUTES", "20"))

# Limites que dependem do corpo do pedido (RFC 05, Limites de pedidos). O
# gateway limita por origem e por credencial; estes ficam aqui.
REDIS_URL = os.environ.get("REDIS_URL", "redis://localhost:6379/0")
DOCUMENT_ATTEMPTS_PER_HOUR = 5
DOCUMENT_ATTEMPTS_WINDOW_SECONDS = 60 * 60
REFUSALS_TO_BLOCK_ORIGIN = 20
REFUSALS_WINDOW_SECONDS = 10 * 60
ORIGIN_BLOCK_SECONDS = 30 * 60

# So o ambiente de teste liga. Com true, a API obedece ao cabecalho
# X-Fault-Injection e finge que o Redis (ou, depois, o bucket) caiu.
FAULT_INJECTION_ENABLED = os.environ.get("FAULT_INJECTION_ENABLED", "false").lower() == "true"

# Idade e datas no futuro sao conferidas no dia de Sao Paulo, e nao no do
# servidor, que roda em UTC (decisao D18 do plano de testes).
BANK_TIMEZONE = "America/Sao_Paulo"

# Rotas publicas: nao exigem o INTERNAL-TOKEN. A raiz diz quem e este
# servico, e o health check e o que o Docker consulta para saber se a API
# ja esta de pe.
BYPASS_ENDPOINTS = [
    "/",
    "/health_check",
]

REQUIRED_VARIABLES = ["DATABASE_URL", "INTERNAL_TOKEN", "AUTH_SECRET"]


def check_variables():
    missing = []
    for name in REQUIRED_VARIABLES:
        if not globals().get(name):
            missing.append(name)

    if missing:
        raise EnvironmentError(
            f"Faltam variáveis de ambiente: {', '.join(missing)}. "
            "Rodando com 'docker compose up' elas já vêm preenchidas."
        )
