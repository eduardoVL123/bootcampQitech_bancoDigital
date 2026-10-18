"""Testes de unidade da antifraud-api: importam o codigo de src direto.

Ficam fora de tests/antifraud_api, que e caixa-preta e fala so por HTTP
(R1). Rodam sem banco e sem API: pytest antifraud-api/tests.

O pacote `controllers` importa o database.py, que monta o engine no
import. Montar nao conecta: a URL abaixo so precisa ser valida.

A URL falsa vale so durante esse import e sai do ambiente logo depois. O
`pytest` da raiz carrega este arquivo junto com a suite de caixa-preta, e o
tests/utils/db_utils.py le a DATABASE_URL para zerar o banco de verdade.
Sem `.env` (o CI, e a banca seguindo o README), a URL falsa sobrava no
ambiente e todo teste da fase 1 que zera o banco tentava a porta 1: foi o
vermelho do CI completo no PR #30, em 18/10/2026.
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))

_sem_url = "DATABASE_URL" not in os.environ
os.environ.setdefault("DATABASE_URL", "postgresql+psycopg2://unit:unit@127.0.0.1:1/sem_banco")
import controllers.engine.flow  # noqa: E402,F401  monta o engine agora, com a URL acima
if _sem_url:
    del os.environ["DATABASE_URL"]
