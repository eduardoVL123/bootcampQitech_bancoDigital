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


class StatementDTO:
    @staticmethod
    def page(linhas: list, next_cursor: str) -> dict:
        return {
            "data": [
                {
                    "entry_key": linha.entry_key.strip(),
                    "amount": linha.amount,
                    "balance_after": linha.balance_after,
                    "sequence": linha.sequence,
                    "created_at": linha.created_at.isoformat(),
                }
                for linha in linhas
            ],
            "next_cursor": next_cursor,
            "is_last_page": next_cursor is None,
        }
