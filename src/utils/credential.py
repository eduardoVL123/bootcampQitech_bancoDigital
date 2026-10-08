from dataclasses import dataclass

import jwt
from fastapi import Request

from constants import AUTH_SECRET
from errors import ExpiredCredential, InvalidCredential, MissingCredential, OperatorScopeRequired


CUSTOMER_SCOPE = "onboarding"
OPERATOR_SCOPE = "operator"

# Sem o exp o token nunca venceria; sem o jti nao haveria como
# identificar uma emissao. O require do PyJWT recusa o token que nao
# tenha todas elas, em vez de tratar a ausencia como "sem limite".
REQUIRED_CLAIMS = ["sub", "scope", "iat", "exp", "jti"]


@dataclass(frozen=True)
class Caller:
    """Quem esta pedindo, segundo a credencial.

    O INTERNAL-TOKEN diz QUE APLICACAO esta falando. Ele nao diz quem,
    e e por isso que esta classe existe: a R8 cobra decisao por titular.
    """

    subject: str
    scope: str

    @property
    def is_operator(self) -> bool:
        return self.scope == OPERATOR_SCOPE

    def owns(self, customer_key: str) -> bool:
        if not customer_key:
            return False
        return self.scope == CUSTOMER_SCOPE and self.subject == str(customer_key).strip()

    def require_operator(self) -> None:
        if not self.is_operator:
            raise OperatorScopeRequired()


def read_caller(request: Request) -> Caller:
    """Confere a credencial do cabecalho Authorization.

    A conta confere sozinha, sem chamar a onboarding-api: a assinatura
    com a AUTH_SECRET ja prova que a credencial saiu de dentro do
    ecossistema. Uma ida ao banco ou uma chamada HTTP por requisicao
    sairia caro e criaria um ponto de falha onde nao precisa existir.

    algorithms=["HS256"] nao e detalhe de estilo. Sem fixar o
    algoritmo, um token com "alg": "none" e sem assinatura nenhuma
    seria aceito, e o sub que o atacante escrever e em quem a API
    acreditaria. E o ataque classico de JWT, e o F7-07 cobra ele.
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

    return Caller(subject=str(claims["sub"]).strip(), scope=claims["scope"])
