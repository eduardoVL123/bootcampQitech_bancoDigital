"""O worker que entrega os eventos aos parceiros.

Ele roda como um processo separado, igual ao onboarding-worker: um
laco que acorda, pega o que esta na hora de entregar, tenta, e volta a
dormir. Se morrer no meio, nada se perde: o que nao foi entregue
continua na tabela, com a hora da proxima tentativa.

Tres decisoes que ficam visiveis no codigo:

1. Qualquer 2xx e sucesso. Um parceiro que responde 201, 202 ou 204
   esta aceitando o evento, e tratar so o 200 como sucesso faria o
   mesmo evento ser entregue cinco vezes e depois dado como perdido.

2. Um COMMIT por evento. Com um commit so no fim do lote, o processo
   morrer no meio faz o lote inteiro voltar a PENDING, inclusive o que
   ja chegou ao parceiro: entrega dobrada de graca.

3. A trava e SKIP LOCKED. Assim duas replicas do worker nunca pegam o
   mesmo evento, e nenhuma fica esperando a outra.
"""
import hashlib
import hmac
import json
import logging
import time
from datetime import datetime, timedelta, timezone

import requests
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from webhook_api.src import config
from webhook_api.src.models.webhook_outbox import WebhookOutbox


logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] webhook-worker - %(message)s")
logger = logging.getLogger(__name__)

PENDENTES = ("PENDING", "QUEUED_FOR_RETRY")


def agora():
    return datetime.now(timezone.utc)


def assina(corpo: str) -> str:
    """HMAC-SHA256 do corpo exato que vai na requisicao.

    Tem de ser do corpo EXATO, byte a byte: se o worker assinar um
    JSON e mandar outro, com os campos em outra ordem, a conta do
    parceiro nao fecha e ele recusa um evento legitimo.
    """
    return hmac.new(config.SECRET.encode(), corpo.encode(), hashlib.sha256).hexdigest()


def entrega(evento: WebhookOutbox) -> tuple:
    """Manda o evento. Devolve (entregue, motivo)."""
    corpo = json.dumps(
        {
            "event_id": evento.event_id.strip(),
            "event_type": evento.event_type,
            "payload": evento.payload,
        },
        separators=(",", ":"),
    )
    cabecalhos = {
        "Content-Type": "application/json",
        "X-Banco-Signature": assina(corpo),
        "X-Banco-Event-Id": evento.event_id.strip(),
    }

    try:
        resposta = requests.post(
            evento.target_url,
            data=corpo.encode(),
            headers=cabecalhos,
            timeout=config.TIMEOUT_SECONDS,
        )
    except requests.exceptions.RequestException as erro:
        return False, type(erro).__name__

    if 200 <= resposta.status_code < 300:
        return True, None
    return False, f"HTTP {resposta.status_code}"


def marca_falha(evento: WebhookOutbox, motivo: str) -> None:
    """Conta a tentativa e agenda a proxima, com recuo exponencial."""
    evento.retries += 1
    evento.last_error = (motivo or "")[:255]
    evento.updated_at = agora()

    if evento.retries >= config.MAX_RETRIES:
        evento.status = "FAILED"
        logger.warning("evento %s dado como perdido depois de %s tentativas", evento.event_id, evento.retries)
        return

    espera = config.RETRY_BASE_SECONDS * (2 ** (evento.retries - 1))
    evento.status = "QUEUED_FOR_RETRY"
    evento.next_attempt_at = agora() + timedelta(seconds=espera)


def process_outbox_events(db_session) -> int:
    """Uma varredura. Devolve quantos eventos foram tratados."""
    eventos = (
        db_session.query(WebhookOutbox)
        .filter(
            WebhookOutbox.status.in_(PENDENTES),
            WebhookOutbox.next_attempt_at <= agora(),
        )
        .order_by(WebhookOutbox.next_attempt_at)
        .limit(config.BATCH_SIZE)
        .with_for_update(skip_locked=True)
        .all()
    )

    for evento in eventos:
        entregue, motivo = entrega(evento)
        if entregue:
            evento.status = "DELIVERED"
            evento.updated_at = agora()
            logger.info("evento %s entregue (%s)", evento.event_id, evento.event_type)
        else:
            marca_falha(evento, motivo)
        # Um COMMIT por evento: ver a decisao 2 no topo do arquivo.
        db_session.commit()

    return len(eventos)


def main() -> None:
    # Uma conexao, e so. O worker e um laco de uma thread so: o pool
    # padrao do SQLAlchemy (5 mais 10 de overflow) reservaria ate 15
    # conexoes para quem usa uma. Com seis clientes de banco no
    # compose, sobra pouco do max_connections do Postgres para quem
    # precisa de verdade.
    engine = create_engine(
        config.DATABASE_URL, pool_size=1, max_overflow=0, pool_pre_ping=True
    )
    Session = sessionmaker(bind=engine)

    logger.info(
        "de pe: varrendo a cada %ss, recuo de %ss, ate %s tentativas",
        config.POLL_SECONDS, config.RETRY_BASE_SECONDS, config.MAX_RETRIES,
    )

    while True:
        session = Session()
        try:
            process_outbox_events(session)
        except Exception as erro:
            # Um erro numa varredura nao pode derrubar o worker: ele
            # dorme e tenta de novo. O que estava na fila continua la.
            logger.error("falha na varredura: %s: %s", type(erro).__name__, erro)
            session.rollback()
        finally:
            session.close()

        time.sleep(config.POLL_SECONDS)


if __name__ == "__main__":
    main()
