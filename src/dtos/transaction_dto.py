from models import Transaction


class TransactionDTO:
    @staticmethod
    def response(transaction: Transaction) -> dict:
        return {
            "transaction_key": transaction.transaction_key.strip(),
            "type": transaction.type.enumerator,
            "status": transaction.status.enumerator,
            "amount": transaction.amount,
            "fee_amount": transaction.fee_amount,
            "fee_policy_key": (
                transaction.fee_policy.fee_policy_key.strip() if transaction.fee_policy else None
            ),
            "origin_account_key": (
                transaction.origin_account.account_key.strip()
                if transaction.origin_account
                else None
            ),
            "destination_account_key": (
                transaction.destination_account.account_key.strip()
                if transaction.destination_account
                else None
            ),
            "created_at": transaction.created_at.isoformat() if transaction.created_at else None,
        }


class FeePolicyDTO:
    @staticmethod
    def response(politica) -> dict:
        return {
            "fee_policy_key": politica.fee_policy_key.strip(),
            "transfer_fee_cents": politica.transfer_fee_cents,
            "valid_from": politica.valid_from.isoformat(),
        }
