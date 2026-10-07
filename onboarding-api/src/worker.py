"""O onboarding-worker (RFC 05): o mesmo código da API, num processo separado.

Ele não tem rota. Acorda a cada WORKER_INTERVAL_SECONDS, faz uma passada e
dorme de novo. Nesta fatia (F5), a passada vence as aberturas paradas; nas
próximas, ela também analisa o KYC (F6) e entrega os eventos (F9).

Cada passada abre o próprio contexto de banco e o fecha no fim, como o
middleware faz a cada requisição da API (src/middlewares/session_manager.py).
"""
import time

from constants import WORKER_INTERVAL_SECONDS, check_variables
from controllers.expiration_controller import ExpirationController
from database import clear_context, open_context
from utils.logger import get_logger, setup_logging


logger = get_logger(__name__)


def run_once() -> None:
    context = open_context()

    try:
        erased = ExpirationController().expire_overdue()
        if erased:
            logger.info(f"Aberturas vencidas apagadas nesta passada: {erased}")
    finally:
        # O que ficou pela metade é desfeito, e a conexão volta para o pool.
        if context.db_session is not None:
            context.db_session.rollback()
            context.db_session.close()
        clear_context()


def main() -> None:
    check_variables()
    setup_logging()
    logger.info(f"onboarding-worker de pe: uma passada a cada {WORKER_INTERVAL_SECONDS} s")

    while True:
        try:
            run_once()
        except Exception:
            # Uma passada que falha não derruba o worker: a próxima tenta de novo.
            logger.exception("Passada do worker falhou")

        time.sleep(WORKER_INTERVAL_SECONDS)


if __name__ == "__main__":
    main()
