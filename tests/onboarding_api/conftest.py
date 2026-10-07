"""Configuracao so dos testes da onboarding-api.

Registra os marcadores que eles usam, para a pasta funcionar sozinha em
qualquer repositorio, com ou sem pytest.ini, e manda os testes global_state
para o fim da fila.
"""


def pytest_configure(config):
    config.addinivalue_line("markers", "concurrency: dispara pedidos juntos de verdade contra a API")
    config.addinivalue_line("markers", "fault_injection: precisa da API e do pytest com FAULT_INJECTION_ENABLED=true")
    config.addinivalue_line("markers", "simulated_clock: precisa da API e do pytest com SIMULATED_CLOCK_ENABLED=true")
    config.addinivalue_line("markers", "slow: espera o worker (ate 90 s); no dia a dia, pytest -m \"not slow\"")
    config.addinivalue_line(
        "markers", "global_state: mexe em algo que vale para todos (circuito aberto, chamada de teste dos biros); roda no fim"
    )


def pytest_collection_modifyitems(items):
    """Os testes global_state vao para o fim da fila, na ordem em que estavam.
    Um circuito aberto no meio da suite faria a analise de outro teste esperar
    a Receita, e ele falharia sem ter nada de errado."""
    items.sort(key=lambda item: item.get_closest_marker("global_state") is not None)
