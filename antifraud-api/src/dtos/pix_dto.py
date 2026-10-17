class PixDTO:
    """O que sai: so `key`, `status` e `metadata`, como no contrato.

    O id interno, as contas e o hash do pedido nunca saem. O status vai em
    minusculas, que e como o contrato o escreve.
    """

    @staticmethod
    def analysis(analysis) -> dict:
        return {
            "key": analysis.analysis_key,
            "status": analysis.status.enumerator.lower(),
            "metadata": analysis.metadata_,
        }
