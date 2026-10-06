from dataclasses import dataclass

import jwt
from fastapi import Request

from constants import AUTH_SECRET
from errors import ExpiredCredential, InvalidCredential, MissingCredential


ONBOARDING_SCOPE = "onboarding"
COMPLIANCE_SCOPE = "compliance"

REQUIRED_CLAIMS = ["sub", "scope", "iat", "exp", "jti"]


@dataclass(frozen=True)
class Credential:
    """Quem está pedindo, segundo a credencial: o cliente (escopo onboarding)
    ou um operador de compliance (escopo compliance, decisão D3)."""

    subject: str
    scope: str

    @property
    def is_compliance(self) -> bool:
        return self.scope == COMPLIANCE_SCOPE

    def is_customer(self, customer_key: str) -> bool:
        return self.scope == ONBOARDING_SCOPE and self.subject == customer_key


def read_credential(request: Request) -> Credential:
    """Confere a credencial do cabeçalho Authorization (RFC 05, Credencial).

    A API confere sozinha, sem chamar ninguém: a assinatura com a
    AUTH_SECRET prova que a credencial foi emitida aqui. Só HS256 é aceito,
    e por isso um token com alg none, sem assinatura, é recusado.
    """
    authorization = request.headers.get("Authorization")
    if not authorization:
        raise MissingCredential()

    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not token.strip():
        raise InvalidCredential()

    try:
        claims = jwt.decode(
            token.strip(),
            AUTH_SECRET,
            algorithms=["HS256"],
            options={"require": REQUIRED_CLAIMS},
        )
    except jwt.ExpiredSignatureError:
        raise ExpiredCredential()
    except jwt.InvalidTokenError:
        raise InvalidCredential()

    return Credential(subject=claims["sub"], scope=claims["scope"])
