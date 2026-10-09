"""Como as outras APIs publicam um evento, sem acoplar nada.

A funcao grava na MESMA sessao de quem chamou, entao o evento entra no
mesmo COMMIT da mudanca de negocio. Ou as duas coisas acontecem, ou
nenhuma: e isso que impede o parceiro de ser avisado de uma
transferencia que deu rollback, e impede a transferencia de acontecer
sem ninguem ser avisado.

SQL cru de proposito: assim quem chama nao precisa importar o model
nem conhecer a tabela, e a unica coisa compartilhada entre os
servicos e o nome de quatro colunas.
"""
import json
from uuid import uuid4

from sqlalchemy import text

from webhook_api.src import config


INSERE = text(
    """
    INSERT INTO webhook_outbox (event_id, target_url, event_type, payload)
    VALUES (:event_id, :target_url, :event_type, :payload)
    """
)


def publish_webhook(db_session, event_type: str, payload: dict) -> str:
    """Poe um evento na caixa de saida. NAO da commit: quem chamou da.

    Devolve o event_id, que e o identificador do evento para quem
    recebe. O parceiro usa esse id para descartar repeticao, porque a
    entrega e "ao menos uma vez" e nao "exatamente uma vez".

    O destino e o segredo nao sao parametros: sao configuracao, e vem
    do ambiente. Quem publica um evento nao precisa saber para quem
    ele vai, e muito menos com que chave ele e assinado.
    """
    event_id = str(uuid4())

    db_session.execute(
        INSERE,
        {
            "event_id": event_id,
            "target_url": config.TARGET_URL,
            "event_type": event_type,
            "payload": json.dumps(payload),
        },
    )
    return event_id
