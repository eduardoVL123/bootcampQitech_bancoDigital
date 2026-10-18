"""O aviso ao pagador, junto da verificacao que o motor pede.

O 2FA responde "e o dono da conta mesmo?". Contra o golpe em que o dono,
enganado, faz o Pix (a falsa central da "conta segura", o falso parente com
numero novo), ele passa na facial: o que protege e a informacao na hora. O
app mostra o aviso junto da verificacao, em `metadata.authentication`.

So vai com `two_factor_required`: o Pix aprovado nao tem tela de
verificacao, e o recusado nao precisa. O texto e generico de proposito e
nao expoe dado do recebedor (idade da conta, quantos pagaram), por causa do
sigilo bancario. Os motivos detalhados ficam em `metadata.rules`, para uso
interno. Vale o primeiro que casar, do mais especifico ao mais geral.
"""
from typing import Optional

from constants import OWN_PARTICIPANT
from controllers.engine.context import DESTINO
from models import PixStatus

SAFE_ACCOUNT = (
    "safe_account",
    "Nenhum banco, central de atendimento ou autoridade pede para você transferir dinheiro para uma "
    "\"conta segura\", nem em seu nome. Se alguém pediu isso por telefone ou mensagem, é golpe: não continue.",
)
NEW_PAYEE_ACCOUNT = (
    "new_payee_account",
    "Se quem pediu este Pix disse ser parente ou amigo com número novo, ligue para o número que você já "
    "conhecia e confirme antes. Só continue se tiver certeza de quem vai receber.",
)
DESTINATION_RISK = (
    "destination_risk",
    "Identificamos sinais de risco no recebedor deste Pix. Só continue se você conhece quem vai receber e "
    "confirmou a cobrança por outro canal.",
)


def payer_warning(ctx, decisao, params) -> Optional[dict]:
    if decisao.status != PixStatus.TWO_FACTOR_REQUIRED:
        return None
    novo = params["DESTINO_NOVO"]
    idade = ctx.moment - ctx.destination_account.opening_date
    mesmo_titular = ctx.source_document == ctx.destination_document
    if mesmo_titular and ctx.destination_account.participant != OWN_PARTICIPANT and idade.days < novo["days"]:
        return _aviso(SAFE_ACCOUNT)
    if (not mesmo_titular and idade.total_seconds() < novo["very_new_hours"] * 3600
            and not ctx.history.approved_to_document(ctx.source_document, ctx.destination_document, ctx.moment)):
        return _aviso(NEW_PAYEE_ACCOUNT)
    minimo = params["decision"].get("destination_warning_min")
    if minimo is not None and decisao.axes.get(DESTINO, 0) >= minimo:
        return _aviso(DESTINATION_RISK)
    return None


def _aviso(aviso) -> dict:
    codigo, mensagem = aviso
    return {"code": codigo, "message": mensagem}
