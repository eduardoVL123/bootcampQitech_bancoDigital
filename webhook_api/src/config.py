"""A configuracao do webhook, toda vinda do ambiente (12-factor).

Nada disto fica no codigo nem no banco. O segredo do parceiro, em
especial, era uma coluna em texto puro copiada em cada evento da fila:
agora ele e variavel de ambiente, lida uma vez, e nenhuma linha do
banco o carrega.
"""
import os


# Para onde o evento vai. Uma URL so, de um parceiro so: a tabela de
# assinaturas, com uma URL e um segredo por parceiro, e o desenho
# certo e esta fora do escopo desta entrega (ver RFC 06).
TARGET_URL = os.environ.get("WEBHOOK_TARGET_URL", "http://mockserver:1080/parceiro/webhook")

# Com que chave o evento e assinado. O padrao serve so para estudo.
SECRET = os.environ.get("WEBHOOK_SECRET", "webhook_secret_de_estudo")

# De quanto em quanto tempo o worker varre a fila.
POLL_SECONDS = float(os.environ.get("WEBHOOK_POLL_SECONDS", "1"))

# Quantas entregas por varredura. Segura o tamanho da transacao e
# impede que um lote gigante prenda o worker numa volta so.
BATCH_SIZE = int(os.environ.get("WEBHOOK_BATCH_SIZE", "20"))

# Quantos segundos esperar pela resposta do parceiro. Sem timeout, o
# prazo e para sempre, e um parceiro lento prende a fila inteira.
TIMEOUT_SECONDS = float(os.environ.get("WEBHOOK_TIMEOUT_SECONDS", "5"))

# O recuo exponencial: base * 2^(tentativas - 1).
#
# No compose a base e 2 segundos, para o ambiente local e os testes nao
# levarem minutos. Em producao seria 60, e a sequencia viraria 1, 2, 4,
# 8 e 16 minutos. O valor esta no docker-compose.yml, visivel, e nao
# escondido aqui dentro.
RETRY_BASE_SECONDS = float(os.environ.get("WEBHOOK_RETRY_BASE_SECONDS", "60"))

# Depois disto, o evento e dado como perdido e fica em FAILED, para
# alguem olhar. Nao se apaga: a fila morta e o registro de que tentamos.
MAX_RETRIES = int(os.environ.get("WEBHOOK_MAX_RETRIES", "5"))

DATABASE_URL = os.environ.get("DATABASE_URL")
