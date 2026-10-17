class PixDTO:
    """O que sai: so `key`, `status` e `metadata`, como no contrato.

    O id interno, as contas e o hash do pedido nunca saem. O status vai em
    minusculas, que e como o contrato o escreve. O resultado do desafio,
    quando o cliente o informou, entra em `metadata.challenge` sem mudar a
    analise gravada.
    """

    @staticmethod
    def analysis(analysis, challenge=None) -> dict:
        metadata = dict(analysis.metadata_)
        if challenge is not None:
            metadata["challenge"] = {"result": challenge.result, "event_date": challenge.event_date.isoformat()}
        return {
            "key": analysis.analysis_key,
            "status": analysis.status.enumerator.lower(),
            "metadata": metadata,
        }
