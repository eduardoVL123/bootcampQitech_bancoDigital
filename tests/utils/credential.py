from datetime import datetime, timedelta, timezone
from os import environ
from uuid import uuid4

import jwt

# O mesmo valor que a API usa. Ele vem do ambiente; o padrao e o do
# .env.example, que serve so para estudo.
AUTH_SECRET = environ.get(
    "AUTH_SECRET", "auth_secret_de_estudo_troque_em_producao_0123456789"
)

CUSTOMER_SCOPE = "onboarding"
OPERATOR_SCOPE = "operator"


def _claims(subject: str, scope: str, vida_em_minutos: int = 15) -> dict:
    agora = datetime.now(timezone.utc)
    return {
        "sub": subject,
        "scope": scope,
        "iat": int(agora.timestamp()),
        "exp": int((agora + timedelta(minutes=vida_em_minutos)).timestamp()),
        "jti": str(uuid4()),
    }


def token_de_cliente(customer_key: str) -> str:
    """A credencial que a onboarding-api emite: sub e a customer_key.

    O teste assina a sua, em vez de atravessar a abertura de conta
    inteira. Nao e olhar para dentro da aplicacao: o segredo vem do
    ambiente, e e assim que os testes da onboarding tambem fazem.
    """
    return jwt.encode(_claims(customer_key, CUSTOMER_SCOPE), AUTH_SECRET, algorithm="HS256")


def token_de_operador() -> str:
    return jwt.encode(_claims("operador-de-teste", OPERATOR_SCOPE), AUTH_SECRET, algorithm="HS256")


def token_com_outro_segredo(customer_key: str) -> str:
    """Assinado com um segredo que nao e o nosso: a assinatura nao fecha."""
    return jwt.encode(_claims(customer_key, CUSTOMER_SCOPE), "segredo-de-quem-nao-e-o-banco-e-nao-devia-assinar", algorithm="HS256")


def token_vencido(customer_key: str) -> str:
    return jwt.encode(_claims(customer_key, CUSTOMER_SCOPE, vida_em_minutos=-5), AUTH_SECRET, algorithm="HS256")


def token_com_alg_none(customer_key: str) -> str:
    """O ataque classico: trocar o algoritmo por none e mandar sem assinatura.

    Quem decodifica sem fixar algorithms=["HS256"] aceita este token e
    confia no sub que o atacante escreveu.
    """
    return jwt.encode(_claims(customer_key, CUSTOMER_SCOPE), None, algorithm="none")
