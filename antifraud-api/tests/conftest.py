"""Testes de unidade da antifraud-api: importam o codigo de src direto.

Ficam fora de tests/antifraud_api, que e caixa-preta e fala so por HTTP
(R1). Rodam sem banco e sem API: pytest antifraud-api/tests.

O pacote `controllers` importa o database.py, que monta o engine no
import. Montar nao conecta: a URL abaixo so precisa ser valida.
"""
import os
import sys

os.environ.setdefault("DATABASE_URL", "postgresql+psycopg2://unit:unit@127.0.0.1:1/sem_banco")
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))
