"""O onboarding-worker (RFC 05): o mesmo código da API, num processo separado.

Ele não tem rota. A cada WORKER_TICK_SECONDS (1 s), olha a fila: analisa o
KYC das aberturas com o RG completo e pede a conta das aprovadas (F6). Com
um birô sem resposta, a abertura espera a próxima tentativa, e o circuit
breaker de cada birô fica no Redis, dividido pelas réplicas (F7). A cada
WORKER_INTERVAL_SECONDS (1 min), também vence as aberturas paradas (F5).
Nas próximas fatias, ele entrega os eventos (F9).

Cada tarefa abre o próprio contexto de banco e o fecha no fim, como o
middleware faz a cada requisição da API (src/middlewares/session_manager.py).
Podem rodar várias réplicas: o FOR UPDATE SKIP LOCKED faz cada abertura
cair numa só.
"""
import time

from constants import KYC_BATCH_SIZE, WORKER_INTERVAL_SECONDS, WORKER_REQUIRED_VARIABLES, WORKER_TICK_SECONDS, check_variables
from controllers.expiration_controller import ExpirationController
from controllers.kyc_controller import KycController
from database import clear_context, open_context
from utils.logger import get_logger, setup_logging


logger = get_logger(__name__)


def run_job(job) -> None:
    """Roda uma tarefa com o próprio contexto de banco, e sempre o fecha."""
    context = open_context()

    try:
        job()
    finally:
        # O que ficou pela metade é desfeito, e a conexão volta para o pool.
        if context.db_session is not None:
            context.db_session.rollback()
            context.db_session.close()
        clear_context()


def analyze_queue() -> None:
    """Analisa as aberturas da fila e depois pede a conta das aprovadas, até
    KYC_BATCH_SIZE de cada por vez, para o vencimento nunca ficar esperando."""
    controller = KycController()

    for _ in range(KYC_BATCH_SIZE):
        if not controller.analyze_next():
            break

    for _ in range(KYC_BATCH_SIZE):
        if not controller.open_next_account():
            break


def expire_overdue() -> None:
    erased = ExpirationController().expire_overdue()
    if erased:
        logger.info(f"Aberturas vencidas apagadas nesta passada: {erased}")


def main() -> None:
    check_variables(WORKER_REQUIRED_VARIABLES)
    setup_logging()
    logger.info(f"onboarding-worker de pe: fila a cada {WORKER_TICK_SECONDS} s, vencimento a cada {WORKER_INTERVAL_SECONDS} s")

    next_expiration = 0.0

    while True:
        jobs = [analyze_queue]
        if time.monotonic() >= next_expiration:
            jobs.append(expire_overdue)
            next_expiration = time.monotonic() + WORKER_INTERVAL_SECONDS

        for job in jobs:
            try:
                run_job(job)
            except Exception:
                # Uma tarefa que falha não derruba o worker: a próxima volta tenta de novo.
                logger.exception(f"Tarefa {job.__name__} do worker falhou")

        time.sleep(WORKER_TICK_SECONDS)


if __name__ == "__main__":
    main()
