import os

SERVICE_ROOT = os.path.abspath(os.path.dirname(__file__))
SCHEMA_PATH = os.path.join(SERVICE_ROOT, "schemas")

APP_ENV = os.environ.get("APP_ENV", "local")
SERVICE_NAME = os.environ.get("SERVICE_NAME", "antifraud-api")

# O banco proprio do antifraude (database/antifraud.sql), no mesmo
# container do Postgres da fase 1, mas sem nenhuma tabela dela.
DATABASE_URL = os.environ.get("DATABASE_URL")
INTERNAL_TOKEN = os.environ.get("INTERNAL_TOKEN")

# Folga para relogios dessincronizados: uma transaction_date mais de cinco
# minutos a frente do relogio do servidor e dado impossivel, e vira 422.
TIME_SKEW_SECONDS = int(os.environ.get("TIME_SKEW_SECONDS", "300"))

# O ISPB da instituicao que usa o motor. A conta pagadora chega sem
# `participant`, e e com ele que o motor a reconhece quando ela aparece
# primeiro como destino de outro Pix e depois como origem. Ficticio.
OWN_PARTICIPANT = os.environ.get("OWN_PARTICIPANT", "99999999")
# Onde consultar as informacoes de seguranca do DICT. Vazio desliga a consulta.
DICT_URL = os.environ.get("DICT_URL", "")
DICT_TIMEOUT_SECONDS = float(os.environ.get("DICT_TIMEOUT_SECONDS", "0.3"))

BYPASS_ENDPOINTS = [
    "/",
    "/health_check",
]

REQUIRED_VARIABLES = ["DATABASE_URL", "INTERNAL_TOKEN"]


def check_variables():
    missing = []
    for name in REQUIRED_VARIABLES:
        if not globals().get(name):
            missing.append(name)

    if missing:
        raise EnvironmentError(
            f"Faltam variáveis de ambiente: {', '.join(missing)}. "
            "Rodando com 'docker compose up' elas já vêm preenchidas. "
            "Fora do Docker, copie o .env.example para .env."
        )
