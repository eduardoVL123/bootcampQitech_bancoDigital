#!/bin/bash
# Roda dentro do LocalStack, quando ele fica pronto (pasta ready.d).
#
# Cria o bucket privado do RG (RFC 05). Privado quer dizer: nenhum acesso
# publico, nem por ACL nem por politica. A foto so sai do bucket por um
# link assinado de 5 minutos, pedido por compliance.
set -euo pipefail

awslocal s3api create-bucket --bucket rg-documentos

awslocal s3api put-public-access-block \
    --bucket rg-documentos \
    --public-access-block-configuration \
    BlockPublicAcls=true,IgnorePublicAcls=true,BlockPublicPolicy=true,RestrictPublicBuckets=true
