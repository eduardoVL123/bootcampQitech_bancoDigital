import hashlib
import time
from typing import Callable

from redis.exceptions import RedisError

from cache import redis_client
from utils.logger import get_logger


SECONDS_WITHOUT_REDIS_AFTER_FAILURE = 30


# Uma tentativa por documento é uma chave idempotente nova. Repetir a mesma
# chave não conta de novo: é o mesmo pedido, e não outra tentativa. Por
# isso as chaves ficam num conjunto, e não num contador.
#
# Conferir e gravar no mesmo script garante que dois pedidos juntos não
# passem os dois pela última vaga. Devolve 0 se pode seguir, ou quantos
# segundos esperar.
DOCUMENT_ATTEMPT_SCRIPT = """
if redis.call('SISMEMBER', KEYS[1], ARGV[1]) == 1 then
    return 0
end
if redis.call('SCARD', KEYS[1]) >= tonumber(ARGV[2]) then
    return math.max(redis.call('TTL', KEYS[1]), 1)
end
redis.call('SADD', KEYS[1], ARGV[1])
redis.call('EXPIRE', KEYS[1], ARGV[3], 'NX')
return 0
"""


class RateLimitRepository:
    """Os contadores dos limites, no Redis (RFC 05, Limites de pedidos).

    Se o Redis não responde, cada método devolve o valor de "sem limite" e
    escreve no log: o limite desliga, e a API continua funcionando.

    Depois de uma falha, o processo passa 30 segundos sem nem tentar o
    Redis. Sem isso, cada pedido pagaria de novo o tempo de descobrir que
    ele está fora (medido no compose: 4 segundos só para resolver o nome).
    """

    # Até quando este processo não tenta o Redis (relógio monotônico).
    skip_redis_until = 0.0

    def __init__(self, available: bool = True) -> None:
        self.logger = get_logger(__name__)
        self.client = redis_client if available else None
        self.document_attempt = redis_client.register_script(DOCUMENT_ATTEMPT_SCRIPT)

    def register_document_attempt(self, document_number: str, attempt_key: str, limit: int, window_seconds: int) -> int:
        # A chave guarda o SHA-256 do documento, nunca o CPF puro.
        key = f"rl:document:{hashlib.sha256(document_number.encode('utf-8')).hexdigest()}"

        return self._run(lambda: int(self.document_attempt(keys=[key], args=[attempt_key, limit, window_seconds])), 0)

    def seconds_blocked(self, origin: str) -> int:
        return self._run(lambda: max(self.client.ttl(f"rl:blocked:{origin}"), 0), 0)

    def count_refusal(self, origin: str, window_seconds: int) -> int:
        def count() -> int:
            key = f"rl:refusal:{origin}"
            pipeline = self.client.pipeline()
            pipeline.incr(key)
            pipeline.expire(key, window_seconds, nx=True)
            refusals, _ = pipeline.execute()
            return refusals

        return self._run(count, 0)

    def block_origin(self, origin: str, seconds: int) -> None:
        self._run(lambda: self.client.set(f"rl:blocked:{origin}", 1, ex=seconds), None)

    def _run(self, operation: Callable, value_without_redis):
        if self.client is None:
            self.logger.warning("Redis indisponivel (falha simulada): limites desligados neste pedido")
            return value_without_redis

        if time.monotonic() < RateLimitRepository.skip_redis_until:
            return value_without_redis

        try:
            return operation()
        except RedisError as error:
            RateLimitRepository.skip_redis_until = time.monotonic() + SECONDS_WITHOUT_REDIS_AFTER_FAILURE
            self.logger.warning(
                f"Redis indisponivel ({type(error).__name__}): limites desligados por "
                f"{SECONDS_WITHOUT_REDIS_AFTER_FAILURE} s neste processo"
            )
            return value_without_redis
