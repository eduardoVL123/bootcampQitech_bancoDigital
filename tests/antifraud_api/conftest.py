"""Configuracao so dos testes da antifraud-api: os marcadores que eles usam."""


def pytest_configure(config):
    config.addinivalue_line("markers", "concurrency: dispara pedidos juntos de verdade contra a API")
