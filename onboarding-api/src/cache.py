"""O cliente do Redis, criado uma vez, como o engine do src/database.py.

O Redis aqui só guarda dado pequeno, que pode ser perdido (RFC 00). Por
isso o cliente desiste rápido: timeout curto e nenhuma retentativa. O
padrão do redis-py é tentar 10 vezes, e com o Redis fora cada pedido da
API levaria segundos para responder.
"""
import redis
from redis.backoff import NoBackoff
from redis.retry import Retry

from constants import REDIS_URL


redis_client = redis.Redis.from_url(
    REDIS_URL,
    socket_timeout=0.5,
    socket_connect_timeout=0.5,
    retry=Retry(NoBackoff(), 0),
    decode_responses=True,
)
