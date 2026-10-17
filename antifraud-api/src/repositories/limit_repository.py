from datetime import timedelta

from database import Context
from models import AccountLimit


class LimitRepository:
    """O historico de limites da conta. Nada e sobrescrito: cada pedido e uma linha.

    O limite vigente num instante e, entre os pedidos que ja comecaram a
    valer, o pedido MAIS RECENTE. Assim uma reducao feita depois de um
    aumento pendente cancela o aumento: quando o aumento chegaria a valer,
    o pedido mais recente ja e a reducao.
    """

    def __init__(self, context: Context) -> None:
        self.session = context.db_session

    def effective(self, account_id: int, moment):
        return self.session.query(AccountLimit).filter(
            AccountLimit.account_id == account_id,
            AccountLimit.effective_from <= moment,
        ).order_by(AccountLimit.requested_at.desc(), AccountLimit.id.desc()).first()

    def latest_request(self, account_id: int, moment):
        return self.session.query(AccountLimit).filter(
            AccountLimit.account_id == account_id,
            AccountLimit.requested_at <= moment,
        ).order_by(AccountLimit.requested_at.desc(), AccountLimit.id.desc()).first()

    def pending_increase(self, account_id: int, moment, delay_hours: int):
        """O aumento pedido ha menos de 24h, que ainda nao vale, se for o pedido mais recente."""
        ultimo = self.latest_request(account_id, moment)
        if ultimo is None or ultimo.change_type != "increase" or ultimo.effective_from <= moment:
            return None
        if ultimo.requested_at < moment - timedelta(hours=delay_hours):
            return None
        return ultimo

    def create(self, account_id: int, amount: int, change_type: str, requested_at, effective_from) -> AccountLimit:
        limite = AccountLimit(account_id=account_id, amount=amount, change_type=change_type,
                              requested_at=requested_at, effective_from=effective_from)
        self.session.add(limite)
        self.session.flush()
        return limite
