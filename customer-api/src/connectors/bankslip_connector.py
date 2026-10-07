from connectors.rest_connector import BaseConnectorResponse, RestConnector
from constants import BANKSLIP_API_INTERNAL_TOKEN, BANKSLIP_API_TIMEOUT, BANKSLIP_API_URL


class BankSlipConnector(RestConnector):
    """Fala com a API de boletos — o serviço de cobrança.

    Este é o connector de exemplo do projeto. Ele conversa com um
    serviço que emite boletos: você pede a emissão com valor e vencimento
    e recebe de volta a chave do boleto criado.

    Repare no que ele NÃO tem: nenhum requests, nenhuma URL escrita no
    código. Isso mora no RestConnector, uma vez só. O que mora aqui é o
    que é específico DESTE serviço: quais endpoints existem e qual o
    formato de cada payload.

    Os métodos devolvem a resposta como veio (status e corpo) — quem
    decide o que fazer com um 404 ou um erro é a regra de negócio, no
    controller.

    Não existe uma API de boletos de verdade rodando na sua máquina —
    e não precisa: no sábado 4 a gente sobe um MOCK no lugar dela, e
    este arquivo não muda uma linha. Só muda a BANKSLIP_API_URL.
    """

    def __init__(self) -> None:
        super().__init__(
            class_name=__name__,
            base_url=BANKSLIP_API_URL,
            timeout=BANKSLIP_API_TIMEOUT,
            internal_token=BANKSLIP_API_INTERNAL_TOKEN,
        )

    def create_bank_slip(
        self, amount: int, expiration_date: str, payer_name: str, payer_document_number: str
    ) -> BaseConnectorResponse:
        """Pede a emissão de um boleto.

        O amount vai em CENTAVOS, inteiro: R$ 1.250,00 é 125000. Dinheiro
        nunca viaja como float — 0.1 + 0.2 explica por quê.
        """
        payload = {
            "amount": amount,
            "expiration_date": expiration_date,
            "payer_data": {
                "name": payer_name,
                "document_number": payer_document_number,
            },
        }

        return self.send(endpoint="/bank_slip", method="POST", payload=payload)

    def get_bank_slip_by_key(self, bank_slip_key: str) -> BaseConnectorResponse:
        """Busca um boleto pela chave. Um 404 na resposta é "não existe"."""
        return self.send(endpoint=f"/bank_slip/{bank_slip_key}", method="GET")
