"""O circuit breaker dos birôs (RFC 05, Birô fora do ar; decisões D15 e D27).

Um birô que caiu não melhora com mais pedidos. Depois de 5 consultas
seguidas sem resposta, o circuito abre: por 30 s, nenhuma réplica chama o
birô, e a abertura espera a próxima tentativa. Passados os 30 s, ele fica
meio aberto: a próxima consulta passa, como teste, e as outras continuam
esperando. Se ela tem resposta, o circuito fecha; se falha, abre de novo.

O estado mora no Redis, nas chaves cb:{birô}:..., para as réplicas pararem
juntas. Sem Redis, cada processo guarda o seu (RFC 05), e o worker continua.
"""
import time

from redis.exceptions import RedisError

from cache import redis_client
from constants import CIRCUIT_FAILURES_TO_OPEN, CIRCUIT_OPEN_SECONDS, CIRCUIT_TRIAL_SECONDS
from utils.logger import get_logger


# Depois de uma falha do Redis, o processo passa este tempo sem tentar o
# Redis, como nos limites de pedidos (src/repositories/rate_limit_repository.py).
SECONDS_WITHOUT_REDIS_AFTER_FAILURE = 30


class RedisCircuitState:
    """O estado no Redis, dividido pelas réplicas:
      - cb:{birô}:failures: consultas seguidas sem resposta;
      - cb:{birô}:open: existe enquanto o circuito está aberto (some sozinha em 30 s);
      - cb:{birô}:trial: a consulta de teste do meio aberto, uma por vez."""

    def __init__(self, name: str) -> None:
        self.failures_key = f"cb:{name}:failures"
        self.open_key = f"cb:{name}:open"
        self.trial_key = f"cb:{name}:trial"

    def is_open(self) -> bool:
        return redis_client.exists(self.open_key) == 1

    def failures(self) -> int:
        return int(redis_client.get(self.failures_key) or 0)

    def take_trial(self) -> bool:
        return bool(redis_client.set(self.trial_key, 1, nx=True, ex=CIRCUIT_TRIAL_SECONDS))

    def add_failure(self) -> int:
        return redis_client.incr(self.failures_key)

    def open(self) -> None:
        pipeline = redis_client.pipeline()
        pipeline.set(self.open_key, 1, ex=CIRCUIT_OPEN_SECONDS)
        pipeline.delete(self.trial_key)
        pipeline.execute()

    def close(self) -> None:
        redis_client.delete(self.failures_key, self.trial_key)


class MemoryCircuitState:
    """O mesmo estado na memória do processo, para quando o Redis não responde."""

    def __init__(self) -> None:
        self.failure_count = 0
        self.open_until = 0.0
        self.trial_until = 0.0

    def is_open(self) -> bool:
        return time.monotonic() < self.open_until

    def failures(self) -> int:
        return self.failure_count

    def take_trial(self) -> bool:
        now = time.monotonic()
        if now < self.trial_until:
            return False
        self.trial_until = now + CIRCUIT_TRIAL_SECONDS
        return True

    def add_failure(self) -> int:
        self.failure_count = self.failure_count + 1
        return self.failure_count

    def open(self) -> None:
        self.open_until = time.monotonic() + CIRCUIT_OPEN_SECONDS
        self.trial_until = 0.0

    def close(self) -> None:
        self.failure_count = 0
        self.trial_until = 0.0


class CircuitBreaker:
    """O circuito de um birô: fechado, aberto ou meio aberto."""

    # Um estado em memória por birô, para o processo inteiro.
    memory_states = {}

    # Até quando este processo não tenta o Redis (relógio monotônico).
    skip_redis_until = 0.0

    def __init__(self, name: str) -> None:
        self.name = name
        self.logger = get_logger(__name__)
        self.redis_state = RedisCircuitState(name)
        self.memory_state = CircuitBreaker.memory_states.setdefault(name, MemoryCircuitState())

    def allows_call(self) -> bool:
        """Fechado: a consulta passa. Aberto: não passa. Meio aberto (passaram
        os 30 s e as falhas continuam lá): só a consulta de teste passa."""
        def allows(state) -> bool:
            if state.is_open():
                return False
            if state.failures() < CIRCUIT_FAILURES_TO_OPEN:
                return True
            return state.take_trial()

        return self._run(allows)

    def record_success(self) -> None:
        """O birô respondeu dentro do contrato: a contagem zera e o circuito fecha."""
        self._run(lambda state: state.close())

    def record_failure(self) -> None:
        """Uma consulta sem resposta, depois das retentativas. Na quinta seguida,
        ou na consulta de teste que falhou, o circuito abre por 30 s."""
        def add(state) -> None:
            if state.add_failure() >= CIRCUIT_FAILURES_TO_OPEN:
                state.open()
                self.logger.warning(f"Circuito do biro {self.name} aberto por {CIRCUIT_OPEN_SECONDS} s")

        self._run(add)

    def _run(self, operation):
        if time.monotonic() >= CircuitBreaker.skip_redis_until:
            try:
                return operation(self.redis_state)
            except RedisError as error:
                CircuitBreaker.skip_redis_until = time.monotonic() + SECONDS_WITHOUT_REDIS_AFTER_FAILURE
                self.logger.warning(
                    f"Redis indisponivel ({type(error).__name__}): circuito dos biros na memoria deste "
                    f"processo por {SECONDS_WITHOUT_REDIS_AFTER_FAILURE} s"
                )

        return operation(self.memory_state)
