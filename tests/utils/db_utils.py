from os import environ
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.exc import OperationalError


RESET_QUERIES = [
    "DROP SCHEMA public CASCADE;",
    "CREATE SCHEMA public;",
    "GRANT ALL ON SCHEMA public TO CURRENT_USER;",
    "GRANT ALL ON SCHEMA public TO public;",
]

PROJECT_ROOT = Path(__file__).resolve().parents[2]
SCHEMA_FILE = PROJECT_ROOT / "database" / "database.sql"

DEFAULT_DATABASE_URL = "postgresql+psycopg2://bootcamp:bootcamp@localhost:5432/bootcamp"

DATABASE_OFFLINE = (
    "Não consegui falar com o banco em {host}:{port}.\n"
    "Ele precisa estar de pé pros testes rodarem. Suba com:  docker compose up\n"
    "Se ele já está de pé, confira a porta na DATABASE_URL do seu .env.\n"
    "\n"
    "O que o banco respondeu, literalmente:\n"
    "  {causa}"
)


class DbUtils:
    """Apaga o banco inteiro e o recria do zero — quando alguém chama.

    Não existe limpeza automática neste projeto. O `rollback()` roda no
    teste que o chamar, na linha em que for chamado, e em mais lugar
    nenhum. Todos os testes dividem o mesmo banco, e cada um enxerga o
    que os anteriores deixaram pra trás.

    O nome engana um pouco: isto não desfaz uma transação. Ele derruba
    o schema `public` com tudo que estiver dentro e roda o
    `database/database.sql` de novo — tabelas vazias e os quatro status
    do INSERT de volta.

    Quando o seu teste precisa chamar: sempre que alguma asserção
    depender de QUANTAS linhas existem no banco — contar, listar,
    paginar, filtrar. Nesses casos `DbUtils.rollback()` é a primeira
    linha do teste, antes de criar qualquer coisa (o exemplo está em
    `tests/integration/test_sample_entities.py`). Um teste que só olha
    as entidades que ele mesmo criou, pela chave que recebeu de volta,
    não precisa de limpeza nenhuma — e fica mais rápido sem ela.

    A limpeza acontece pela mesma conexão que a aplicação usa (a
    DATABASE_URL), e não por um programa externo: quem tem Docker
    rodando já tem tudo que precisa.
    """

    @staticmethod
    def database_url() -> str:
        return environ.get("DATABASE_URL", DEFAULT_DATABASE_URL)

    @staticmethod
    def rollback() -> None:
        engine = create_engine(DbUtils.database_url(), isolation_level="AUTOCOMMIT")

        try:
            with engine.connect() as connection:
                for query in RESET_QUERIES:
                    connection.exec_driver_sql(query)

                connection.exec_driver_sql(SCHEMA_FILE.read_text())
        except OperationalError as erro:
            # A mensagem do Postgres vai junto, e nao e detalhe.
            #
            # "Nao consegui falar com o banco" cobre coisas muito
            # diferentes: o container nao subiu, a porta esta errada,
            # acabaram as conexoes ("too many clients"), ou o servidor
            # fechou a conexao no meio. O texto fixo sugere so as duas
            # primeiras, e manda conferir o .env mesmo quando o .env
            # esta certo.
            #
            # Isto custou tempo de verdade: um erro desses no CI mandou
            # o time procurar porta e container, quando a resposta
            # estava na linha que esta funcao jogava fora.
            message = DATABASE_OFFLINE.format(
                host=engine.url.host,
                port=engine.url.port,
                causa=str(getattr(erro, "orig", erro)).strip() or type(erro).__name__,
            )
            raise RuntimeError(message) from None
        finally:
            engine.dispose()
