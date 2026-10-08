import base64
import hashlib
import hmac
import json

from constants import AUTH_SECRET
from errors import InvalidStatementCursor


def encode(account_key: str, sequence: int) -> str:
    """Um ponteiro OPACO e ASSINADO para a proxima pagina.

    Opaco porque o cliente nao precisa saber o que tem dentro, e nao
    deve construir um por conta propria: e a regra #137 da Zalando.

    Assinado porque sem assinatura daria para trocar o numero a mao e,
    pior, trocar a conta: o cursor carrega a conta a que pertence, e a
    assinatura e o que impede forjar um para espiar o livro alheio.

    Carrega o `sequence`, e nao um deslocamento. O livro e append-only
    e recebe escrita o tempo todo: com OFFSET, um lancamento novo
    empurraria a janela e o cliente veria o mesmo item duas vezes.
    """
    corpo = json.dumps({"a": account_key, "s": sequence}, separators=(",", ":"))
    dados = base64.urlsafe_b64encode(corpo.encode()).decode().rstrip("=")
    return f"{dados}.{_assina(dados)}"


def decode(cursor: str, account_key: str) -> int:
    """Devolve o `sequence` do cursor, ou recusa.

    Confere a assinatura com compare_digest, que leva o mesmo tempo
    acertando ou errando: comparar com == vazaria, pelo tempo de
    resposta, quantos caracteres do inicio estavam certos.
    """
    try:
        dados, assinatura = cursor.split(".")
    except (ValueError, AttributeError):
        raise InvalidStatementCursor()

    if not hmac.compare_digest(assinatura, _assina(dados)):
        raise InvalidStatementCursor()

    try:
        falta = "=" * (-len(dados) % 4)
        conteudo = json.loads(base64.urlsafe_b64decode(dados + falta).decode())
        sequence = int(conteudo["s"])
        dono = conteudo["a"]
    except (ValueError, KeyError, TypeError):
        raise InvalidStatementCursor()

    if dono != account_key:
        # Assinatura valida, mas de OUTRA conta. E a tentativa que a
        # assinatura sozinha nao pegaria: o cliente pediria o proprio
        # extrato, guardaria o cursor e o usaria na conta do vizinho.
        raise InvalidStatementCursor()

    return sequence


def _assina(dados: str) -> str:
    return hmac.new(AUTH_SECRET.encode(), dados.encode(), hashlib.sha256).hexdigest()[:32]
