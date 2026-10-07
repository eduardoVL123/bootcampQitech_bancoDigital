import json
from sqlalchemy import text

def publish_webhook(db_session, target_url: str, event_type: str, payload: dict, secret_key: str = None) -> None:
    """
    Registra um novo evento na webhook_outbox para ser entregue aos parceiros.
    
    Esta função deve ser chamada ANTES do `db_session.commit()` do seu caso de uso.
    Como ela utiliza a mesma sessão de banco do Controller que a chamou,
    o evento do Webhook e as alterações de negócio (como criar a Conta ou Transação)
    serão salvos juntos (ACID). Se a transação falhar, o webhook também não será enviado.
    
    Args:
        db_session: A sessão atual do SQLAlchemy.
        target_url: URL do parceiro (ex: lida de uma configuração no banco).
        event_type: O tipo de evento (ex: 'account.created', 'transaction.success').
        payload: O dicionário com os dados que o parceiro vai receber.
        secret_key: Chave secreta do parceiro para gerar o HMAC (Opcional).
    """
    
    # Utilizando SQL bruto (text) para não forçar os outros microsserviços 
    # a importarem o model WebhookOutbox, garantindo total desacoplamento.
    query = text("""
        INSERT INTO webhook_outbox (target_url, event_type, payload, secret_key)
        VALUES (:target_url, :event_type, :payload, :secret_key)
    """)
    
    db_session.execute(query, {
        "target_url": target_url,
        "event_type": event_type,
        # O json.dumps prepara o dict do python para a coluna JSONB do Postgres
        "payload": json.dumps(payload),
        "secret_key": secret_key
    })
