from models import Account


class AccountDTO:
    """O que sai na resposta. Nunca o model direto, nunca o id interno (R5)."""

    @staticmethod
    def created_response(account: Account) -> dict:
        return {
            "account_key": account.account_key.strip(),
            "balance": account.balance,
            "status": account.status.enumerator,
        }

    @staticmethod
    def full_response(account: Account) -> dict:
        resposta = AccountDTO.created_response(account)
        resposta["status_events"] = [
            {
                "status": evento.status.enumerator,
                "reason": evento.reason.enumerator if evento.reason else None,
                "event_datetime": evento.event_datetime.isoformat(),
            }
            for evento in account.status_events
        ]
        return resposta
