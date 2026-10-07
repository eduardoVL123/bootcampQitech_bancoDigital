from datetime import datetime
from uuid import uuid4

import jwt

from constants import ACCESS_TOKEN_LIFETIME_SECONDS, AUTH_SECRET
from utils.credential import ONBOARDING_SCOPE


def issue_access_token(customer_key: str, issued_at: datetime) -> str:
    """Emite a credencial do cliente (RFC 05, Credencial).

    Um JWT assinado com HMAC-SHA256 e a AUTH_SECRET, com cinco campos e
    nenhum dado pessoal: quem é (sub), o que pode (scope), quando nasceu,
    quando vence (1 hora) e um identificador único (jti). A credencial não
    é guardada no banco: a assinatura prova que ela saiu daqui.
    """
    issued_at_seconds = int(issued_at.timestamp())

    claims = {
        "sub": customer_key,
        "scope": ONBOARDING_SCOPE,
        "iat": issued_at_seconds,
        "exp": issued_at_seconds + ACCESS_TOKEN_LIFETIME_SECONDS,
        "jti": str(uuid4()),
    }

    return jwt.encode(claims, AUTH_SECRET, algorithm="HS256")
