from models import Posting


class PostingDTO:
    @staticmethod
    def applied_response(posting: Posting) -> dict:
        return {
            "posting_key": posting.posting_key.strip(),
            "type": posting.type.enumerator,
            "entries": [
                {
                    "entry_key": entry.entry_key.strip(),
                    "account_key": entry.account.account_key.strip(),
                    "amount": entry.amount,
                    "balance_after": entry.balance_after,
                    "sequence": entry.sequence,
                }
                for entry in posting.entries
            ],
        }
