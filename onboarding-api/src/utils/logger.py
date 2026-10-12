import logging
import re
import sys

from psycopg2 import Error as DriverError
from sqlalchemy.exc import SQLAlchemyError

from constants import APP_ENV, SERVICE_NAME
from utils.request_context import get_request_id


# O "[%(request_id)s]" é o identificador da requisição que gerou a linha
# — quem o preenche é o filtro logo abaixo. Uma linha sai assim:
#
#   2026-09-01 12:00:00 [INFO] bootcamp-api.middlewares.request_logger
#   [8f3c1e42-...] - ENTROU GET /onboardings
LOG_FORMAT = "%(asctime)s [%(levelname)s] %(name)s [%(request_id)s] - %(message)s"

# CPF e CNPJ, com e sem pontuação. O \b não separa letra de número, então
# um trecho de UUID ou de hash, que mistura os dois, nunca casa.
PERSONAL_DOCUMENT = re.compile(
    r"\b\d{3}\.\d{3}\.\d{3}-\d{2}\b"
    r"|\b\d{2}\.\d{3}\.\d{3}/\d{4}-\d{2}\b"
    r"|\b\d{14}\b"
    r"|\b\d{11}\b"
)
HIDDEN = "***"


class RequestIdFilter(logging.Filter):
    """Carimba toda linha de log com o identificador da requisição.

    "Filter" é um nome infeliz do Python: esta classe não descarta nada
    — ela devolve True para tudo. O que ela faz é acrescentar um campo à
    linha antes de a formatação acontecer. É o gancho oficial do módulo
    de log para isso.

    A alternativa seria lembrar de escrever o identificador em cada
    chamada de logger.info do projeto. Uma hora alguém esquece, e é
    justamente na linha que você iria precisar.

    Quando não há requisição em andamento — a API subindo, por
    exemplo — o campo sai como "-", e nada quebra.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = get_request_id()
        return True


class PersonalDataFormatter(logging.Formatter):
    """Escreve a linha de log sem dado pessoal (RFC 05, Log sem dado pessoal; D35).

    Duas proteções, nesta ordem:

    • **A mensagem de um erro do banco não entra.** Quando uma restrição
      barra uma gravação, o PostgreSQL repete na mensagem a linha que
      tentou gravar ("Failing row contains (..., nome, CPF, nascimento)"),
      e o SQLAlchemy acrescenta os valores do comando ("[parameters: ...]").
      No lugar dela vai o SQLSTATE, a tabela e a restrição. O tipo do erro
      e o caminho no código continuam no traceback.

    • **CPF e CNPJ viram `***`** em toda a linha, com ou sem pontuação,
      venham de onde vierem: o caminho da URL, uma biblioteca, um traceback.

    Fica no formatador, e não num filtro, porque é aqui que o traceback
    vira texto: um filtro veria a exceção ainda como objeto.
    """

    def formatException(self, exc_info) -> str:
        text = super().formatException(exc_info)

        # A mensagem do SQLAlchemy contém a do driver: a mais longa sai
        # primeiro, senão sobraria o resto dela, com os parâmetros.
        database_errors = [error for error in exception_chain(exc_info[1]) if is_database_error(error)]
        for error in sorted(database_errors, key=lambda error: len(str(error)), reverse=True):
            message = str(error)
            if message:
                text = text.replace(message, describe_database_error(error))

        return text

    def format(self, record: logging.LogRecord) -> str:
        return PERSONAL_DOCUMENT.sub(HIDDEN, super().format(record))


def exception_chain(error: BaseException):
    """O erro e os que vieram antes dele (o "from" e o "durante o tratamento")."""
    seen = set()
    while error is not None and id(error) not in seen:
        seen.add(id(error))
        yield error
        error = error.__cause__ or error.__context__


def is_database_error(error: BaseException) -> bool:
    return isinstance(error, (SQLAlchemyError, DriverError))


def describe_database_error(error: BaseException) -> str:
    """O que se pode dizer de um erro do banco sem repetir os dados dele."""
    original = getattr(error, "orig", None) or error
    diag = getattr(original, "diag", None)

    parts = [f"SQLSTATE {getattr(original, 'pgcode', None) or '?'}"]
    if getattr(diag, "table_name", None):
        parts.append(f"tabela {diag.table_name}")
    if getattr(diag, "constraint_name", None):
        parts.append(f"restricao {diag.constraint_name}")

    return f"mensagem do banco fora do log, pode ter dado pessoal ({', '.join(parts)})"


def setup_logging() -> None:
    """Liga o log da aplicação. Chamada uma vez, quando a API sobe."""
    level = logging.INFO
    if APP_ENV.upper() in ("LOCAL", "TEST"):
        level = logging.DEBUG

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(PersonalDataFormatter(LOG_FORMAT))

    # O filtro fica no HANDLER, não num logger específico: assim toda
    # linha que passar por aqui ganha o campo, venha ela do nosso código
    # ou de qualquer biblioteca. Se ficasse num logger só, a primeira
    # linha vinda de outro lugar derrubaria a formatação.
    handler.addFilter(RequestIdFilter())

    root_logger = logging.getLogger()
    root_logger.setLevel(level)
    root_logger.handlers = [handler]

    # O uvicorn sobe com um handler próprio, e o Starlette repassa a ele todo
    # erro inesperado depois da nossa resposta 500: ele escreveria o traceback
    # inteiro, com a mensagem do banco, por fora do formatador acima. Sem o
    # handler, as linhas dele sobem para o nosso, como as de qualquer biblioteca.
    uvicorn_logger = logging.getLogger("uvicorn")
    uvicorn_logger.handlers = []
    uvicorn_logger.propagate = True

    # O urllib3 fala MUITO em modo debug, e nada disso e nosso: sao
    # detalhes de conexao HTTP das bibliotecas que usamos. O cliente do S3
    # (boto3, botocore e s3transfer) e pior: em debug ele escreve cabecalhos,
    # assinatura e os parametros de cada envio do RG. Quem registra a ida e a
    # volta ao bucket, sem dado pessoal, e o src/connectors/bucket_connector.py.
    for biblioteca_falante in ["urllib3", "boto3", "botocore", "s3transfer"]:
        logging.getLogger(biblioteca_falante).setLevel(logging.CRITICAL)


def get_logger(class_name: str) -> logging.Logger:
    """Devolve o log com o nome de quem está escrevendo.

    Assim, olhando a linha do log, você sabe de qual arquivo ela veio.
    """
    return logging.getLogger(f"{SERVICE_NAME}.{class_name}")
