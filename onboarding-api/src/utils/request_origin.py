from datetime import datetime

from fastapi import Request

from constants import FAULT_INJECTION_ENABLED, SIMULATED_CLOCK_ENABLED
from utils.clock import now_utc


def read_origin_ip(request: Request) -> str:
    """O IP de quem chamou, como o gateway informa no X-Forwarded-For (decisão D4).

    A onboarding-api só é alcançada pelo gateway, dentro da rede do compose.
    Por isso o primeiro IP do X-Forwarded-For é o do cliente. Sem o
    cabeçalho, vale o IP da conexão.
    """
    forwarded_for = request.headers.get("X-Forwarded-For")

    if forwarded_for:
        return forwarded_for.split(",")[0].strip()

    if request.client is not None:
        return request.client.host

    return "unknown"


def read_request_time(request: Request) -> datetime:
    """A hora do pedido. Com SIMULATED_CLOCK_ENABLED=true, o teste pode dizer
    que ele aconteceu no passado, pelo X-Simulated-Now (decisão D16): é assim
    que o teste do prazo de 20 minutos não espera 20 minutos de verdade."""
    simulated_now = request.headers.get("X-Simulated-Now")

    if SIMULATED_CLOCK_ENABLED and simulated_now:
        return datetime.fromisoformat(simulated_now)

    return now_utc()


def read_fault_injection(request: Request) -> frozenset:
    """As falhas que o teste pediu para simular, só com FAULT_INJECTION_ENABLED=true."""
    if not FAULT_INJECTION_ENABLED:
        return frozenset()

    header = request.headers.get("X-Fault-Injection", "")
    return frozenset(name.strip() for name in header.split(",") if name.strip())
