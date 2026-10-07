"""Configuracao so dos testes da onboarding-api.

Registra os marcadores que eles usam, para a pasta funcionar sozinha em
qualquer repositorio, com ou sem pytest.ini.
"""


def pytest_configure(config):
    config.addinivalue_line("markers", "concurrency: dispara pedidos juntos de verdade contra a API")
    config.addinivalue_line("markers", "fault_injection: precisa da API e do pytest com FAULT_INJECTION_ENABLED=true")
    config.addinivalue_line("markers", "simulated_clock: precisa da API e do pytest com SIMULATED_CLOCK_ENABLED=true")
    config.addinivalue_line("markers", "slow: espera o worker (ate 90 s); no dia a dia, pytest -m \"not slow\"")
