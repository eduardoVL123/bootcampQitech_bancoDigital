from uuid import UUID

from fastapi import Request

from errors import InvalidIdempotencyKey


IDEMPOTENCY_KEY_HEADER = "X-Idempotency-Key"


def read_idempotency_key(request: Request) -> str:
    """Lê a X-Idempotency-Key repassada pelo gateway e exige que seja um UUID.

    Devolve a forma canônica (minúsculas, com hífens): a mesma chave escrita
    de outro jeito continua sendo a mesma chave, e não uma abertura nova.
    """
    idempotency_key = request.headers.get(IDEMPOTENCY_KEY_HEADER)

    if idempotency_key is None:
        raise InvalidIdempotencyKey("required")

    try:
        return str(UUID(idempotency_key))
    except ValueError:
        raise InvalidIdempotencyKey("format")
