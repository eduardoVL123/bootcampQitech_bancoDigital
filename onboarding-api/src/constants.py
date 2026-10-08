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

# O bucket privado das fotos do RG (RFC 05). No compose, quem faz o papel
# do S3 e o LocalStack. Sem o endereco, o cliente do S3 iria para a AWS de
# verdade: por isso a API nao sobe sem ele.
S3_ENDPOINT_URL = os.environ.get("S3_ENDPOINT_URL")
S3_REGION = os.environ.get("AWS_DEFAULT_REGION", "us-east-1")
RG_BUCKET = os.environ.get("RG_BUCKET", "rg-documentos")
BUCKET_TIMEOUT_SECONDS = 10

# A fila de compliance (RFC 05, GET /onboardings): 10 por pagina, a partir da primeira.
QUEUE_DEFAULT_LIMIT = 10
QUEUE_DEFAULT_PAGE = 0

# Cada imagem do RG tem ate 5 MB (RFC 05, Rotas).
MAX_DOCUMENT_BYTES = 5 * 1024 * 1024

# So o ambiente de teste liga. Com true, a API obedece ao cabecalho
# X-Fault-Injection e finge que o Redis (ou, depois, o bucket) caiu.
FAULT_INJECTION_ENABLED = os.environ.get("FAULT_INJECTION_ENABLED", "false").lower() == "true"

# Tambem so no teste: com true, o POST /onboarding e o envio do RG aceitam o
# cabecalho X-Simulated-Now e acontecem "no passado" (decisao D16). Em
# producao, ninguem escolhe a hora do proprio pedido.
SIMULATED_CLOCK_ENABLED = os.environ.get("SIMULATED_CLOCK_ENABLED", "false").lower() == "true"

# O onboarding-worker passa a cada minuto (RFC 05, Prazo de 20 minutos). Em
# cada passada, vence as aberturas paradas, um lote de cada vez.
WORKER_INTERVAL_SECONDS = int(os.environ.get("WORKER_INTERVAL_SECONDS", "60"))
EXPIRATION_BATCH_SIZE = 50

# A fila da analise e olhada a cada segundo: quem mandou o RG nao espera um
# minuto para comecar a ser analisado.
WORKER_TICK_SECONDS = float(os.environ.get("WORKER_TICK_SECONDS", "1"))
KYC_BATCH_SIZE = 20

# Posse do worker sobre uma abertura (lease_until): se ele cair no meio da
# analise, outra replica pega a abertura quando a posse vence.
WORKER_LEASE_SECONDS = 60

# Os biros e a account-api (RFC 05, Contratos com as vizinhas). No
# compose, todos sao o Mockserver.
RECEITA_URL = os.environ.get("RECEITA_URL")
SANCTIONS_URL = os.environ.get("SANCTIONS_URL")
PEP_URL = os.environ.get("PEP_URL")
ACCOUNT_API_URL = os.environ.get("ACCOUNT_API_URL")
SERVICE_TOKEN = os.environ.get("SERVICE_TOKEN")
BUREAU_TIMEOUT_SECONDS = 2
ACCOUNT_API_TIMEOUT_SECONDS = 5

# Birô fora do ar (RFC 05). Cada consulta sem resposta é repetida na hora
# até 2 vezes, depois de 200 ms e de 400 ms, mais uma variação aleatória de
# até metade da espera: as réplicas não voltam todas juntas.
BUREAU_RETRY_DELAYS_SECONDS = (0.2, 0.4)
BUREAU_RETRY_JITTER = 0.5

# O circuit breaker de cada birô (decisão D27): 5 consultas seguidas sem
# resposta abrem o circuito por 30 s. Depois, uma consulta de teste por vez,
# com este prazo para terminar antes que outra possa tentar.
CIRCUIT_FAILURES_TO_OPEN = 5
CIRCUIT_OPEN_SECONDS = 30
CIRCUIT_TRIAL_SECONDS = 10

# A abertura que ficou sem resposta de um birô tenta de novo depois destes
# minutos, e depois de hora em hora. Com 24 horas na fila, compliance decide.
ANALYSIS_RETRY_MINUTES = (1, 5, 15, 60)
BUREAU_WAIT_LIMIT_HOURS = 24

# A webhook-api, que recebe os eventos da outbox (RFC 05, Eventos). No
# compose, e o Mockserver. O worker toma posse de um evento por 60 s antes de
# chamar, e um evento que falha tenta de novo em 1, 5, 15 e 60 minutos e
# depois a cada 6 horas, sempre com o mesmo event_id.
WEBHOOK_API_URL = os.environ.get("WEBHOOK_API_URL")
WEBHOOK_TIMEOUT_SECONDS = 3
EVENT_LEASE_SECONDS = 60
EVENT_RETRY_MINUTES = (1, 5, 15, 60, 360)
EVENT_BATCH_SIZE = 20

# A account-api nao respondeu: a abertura fica APPROVED e o worker tenta de
# novo depois deste tempo, com a mesma chave idempotente.
ACCOUNT_RETRY_SECONDS = 60

# Regras de PLD (RFC 05). Valores de exemplo, definidos pela area de
# compliance. Renda e faturamento em centavos, por mes.
PLD_YOUNG_AGE = 21
PLD_YOUNG_MAX_INCOME = 3000000
PLD_MAX_INCOME = 50000000
PLD_NEW_COMPANY_DAYS = 180
PLD_NEW_COMPANY_MAX_INCOME = 30000000

# Idade e datas no futuro sao conferidas no dia de Sao Paulo, e nao no do
# servidor, que roda em UTC (decisao D18 do plano de testes).
BANK_TIMEZONE = "America/Sao_Paulo"

# Os parametros da URL cujo valor pode ir para o log (RFC 05, Log sem dado
# pessoal, decisao D34). Sao os da fila de compliance, e nenhum e pessoal. O
# resto vira *** no log: um CPF mandado por engano na URL nao fica gravado.
LOGGED_QUERY_PARAMS = {"limit", "page", "status", "reason_code"}

# Rotas publicas: nao exigem o INTERNAL-TOKEN. A raiz diz quem e este
# servico, e o health check e o que o Docker consulta para saber se a API
# ja esta de pe.
BYPASS_ENDPOINTS = [
    "/",
    "/health_check",
]

# A API chama os biros na chamada de teste da retentativa em lote.
REQUIRED_VARIABLES = ["DATABASE_URL", "INTERNAL_TOKEN", "AUTH_SECRET", "S3_ENDPOINT_URL", "RECEITA_URL", "SANCTIONS_URL", "PEP_URL"]


# O worker precisa tambem da account-api e da webhook-api, que so ele chama.
WORKER_REQUIRED_VARIABLES = REQUIRED_VARIABLES + ["ACCOUNT_API_URL", "WEBHOOK_API_URL", "SERVICE_TOKEN"]


def check_variables(required=REQUIRED_VARIABLES):
    missing = []
    for name in required:
        if not globals().get(name):
            missing.append(name)

    if missing:
        raise EnvironmentError(
            f"Faltam variáveis de ambiente: {', '.join(missing)}. "
            "Rodando com 'docker compose up' elas já vêm preenchidas."
        )
