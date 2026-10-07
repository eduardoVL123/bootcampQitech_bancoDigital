import time

import boto3
from botocore.config import Config
from botocore.exceptions import BotoCoreError, ClientError

from constants import BUCKET_TIMEOUT_SECONDS, RG_BUCKET, S3_ENDPOINT_URL, S3_REGION
from utils.logger import get_logger


# O cliente do S3, criado uma vez, como o do Redis em src/cache.py.
#
# O timeout de 10 s vale para conectar e para esperar a resposta, e não há
# retentativa: o padrão do boto3 tentaria de novo várias vezes, e um bucket
# fora do ar seguraria o pedido por mais tempo do que o gateway espera.
# O endereço no estilo "path" (http://localstack:4566/rg-documentos/...) é o
# que o LocalStack entende sem precisar de DNS para o nome do bucket.
s3_client = boto3.client(
    "s3",
    endpoint_url=S3_ENDPOINT_URL,
    region_name=S3_REGION,
    config=Config(
        connect_timeout=BUCKET_TIMEOUT_SECONDS,
        read_timeout=BUCKET_TIMEOUT_SECONDS,
        retries={"mode": "standard", "total_max_attempts": 1},
        s3={"addressing_style": "path"},
    ),
)


class BucketError(Exception):
    """O bucket não respondeu. Quem traduz isso para o cliente é o controller."""


class BucketConnector:
    """O bucket privado das fotos do RG (RFC 05). É o único lugar que fala com o S3.

    Com `available=False`, finge que o bucket caiu: é a falha simulada
    `bucket_unavailable`, que só o ambiente de teste liga (decisão D17).
    """

    def __init__(self, available: bool = True) -> None:
        self.logger = get_logger(__name__)
        self.available = available

    def put_object(self, object_key: str, content: bytes, content_type: str) -> None:
        if not self.available:
            self.logger.warning("Bucket indisponivel (falha simulada)")
            raise BucketError()

        # O log mostra a ida e a volta, nunca a foto nem dado pessoal: o
        # caminho do objeto só tem a chave da abertura.
        self.logger.info(f"OUTGOING PutObject {RG_BUCKET}")
        started_at = time.perf_counter()

        try:
            s3_client.put_object(Bucket=RG_BUCKET, Key=object_key, Body=content, ContentType=content_type)
        except (BotoCoreError, ClientError) as error:
            self.logger.error(f"Bucket indisponivel ({type(error).__name__})")
            raise BucketError() from error

        elapsed_ms = (time.perf_counter() - started_at) * 1000
        self.logger.info(f"INCOMING PutObject {RG_BUCKET} - {elapsed_ms:.1f} ms")
