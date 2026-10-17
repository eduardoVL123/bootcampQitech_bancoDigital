"""Payloads de Pix para a antifraud-api, vistos de fora.

Nada aqui conhece o codigo da API: so o contrato do POST /pix/transaction
(secao 3.1 do desafio, o schema post_pix_transaction.json da antifraud-api).
O ponto de partida e um Pix comum, de dia, entre contas antigas, no app e
em Sao Paulo. Cada cenario parte dele e muda so o que interessa, com
mutar(), para que a diferenca entre um caso e outro fique evidente.

As constantes de documento, aparelho e localizacao sao as do seed da API
(database/antifraud.sql). Se o seed mudar, elas mudam junto, senao os
cenarios de reputacao (fraude ativa, vitima, watchlist) deixam de achar o
cadastro que esperam.

Mora dentro do laboratorio, e nao em tests/utils, de proposito: o
tests/utils/pix.py e o dos testes da propria API (Pagador, Recebedor,
paga), e este aqui usa so a biblioteca padrao, para os scripts de tools/
rodarem sem as dependencias dos testes.
"""

import copy
import uuid

# Faixas de IP e GPS de cada cidade, as tres do ip_range_location do seed.
# O IP e de faixa de documentacao (RFC 5737), entao nunca aponta para uma
# maquina de verdade. A API acha a cidade pela faixa /24, nao pelo IP exato.
IP_SP = "198.51.100.23"
GPS_SP = {"latitude": -23.56, "longitude": -46.65}

IP_RECIFE = "203.0.113.45"
GPS_RECIFE = {"latitude": -8.05, "longitude": -34.90}

IP_LISBOA = "192.0.2.88"
GPS_LISBOA = {"latitude": 38.72, "longitude": -9.14}

# Sydney fica de proposito FORA do seed: e o brasileiro no exterior com um IP
# que a API nunca viu. Ela so descobre onde ele fica pelo GPS dos Pix
# anteriores daquela rede (/48 no IPv6). 2001:db8::/32 e faixa de documentacao.
IP_SYDNEY = "2001:db8:61::10"
GPS_SYDNEY = {"latitude": -33.87, "longitude": 151.21}

# Documentos do seed (reputation_fixture e watchlist).
DOC_FRAUDE_ATIVA = "52998224725"  # conta laranja confirmada, marcacao critica vigente
DOC_ALERTA_RISCO = "11144477735"  # denuncia em aberto, alerta vigente
DOC_ALERTA_VENCIDO = "39053344705"  # mesma marcacao, mas vencida em 2019
DOC_VITIMA = "12345678909"  # vitima registrada, recebe normalmente
DOC_WATCHLIST = "27548438923"  # CPF na lista interna de fraude
DEVICE_WATCHLIST = "dvc-watchlist-0001"  # aparelho na lista interna de fraude

# Participante (ISPB) de quem recebe. O pagador e sempre cliente da propria
# instituicao, por isso a conta de origem nao leva participante: a API a grava
# como da casa (99999999). Quem recebe e depois paga (a laranja que repassa)
# precisa receber como PARTICIPANTE_CASA, senao a API ve duas contas e nao
# liga a entrada com a saida.
PARTICIPANTE_PADRAO = "60701190"
PARTICIPANTE_CASA = "99999999"

# Data de abertura que o projeto trata como "conta antiga" (mais de 1 ano).
CONTA_ANTIGA = "2021-03-10T09:00:00-03:00"

# Pagador e recebedor do Pix padrao. Nao sao do seed: so precisam existir
# como documentos validos.
DOC_PAGADOR_PADRAO = "24843803480"
DOC_RECEBEDOR_PADRAO = "45287196000185"


def abertura(data: str) -> str:
    """A data de abertura de conta no formato do contrato: "2021-03-10" vira 9h de Brasilia."""
    return data if "T" in data else f"{data}T09:00:00-03:00"


def cpf_com_digitos(base: str) -> str:
    """Completa 9 digitos de CPF com os dois verificadores."""
    digitos = [int(d) for d in base]
    for _ in range(2):
        soma = sum((len(digitos) + 1 - i) * d for i, d in enumerate(digitos)) % 11
        digitos.append(11 - soma if soma > 1 else 0)
    return "".join(str(d) for d in digitos)


def cnpj_com_digitos(base: str) -> str:
    """Completa 12 digitos de CNPJ com os dois verificadores."""
    digitos = [int(d) for d in base]
    for _ in range(2):
        soma = sum(d * (i % 8 + 2) for i, d in enumerate(reversed(digitos)))
        dv = 11 - soma % 11
        digitos.append(dv if dv < 10 else 0)
    return "".join(str(d) for d in digitos)


def documento_valido(documento: str) -> bool:
    """Confere o digito verificador de um CPF (11) ou CNPJ (14)."""
    if not documento.isdigit() or len(set(documento)) == 1:
        return False
    if len(documento) == 11:
        return cpf_com_digitos(documento[:9]) == documento
    if len(documento) == 14:
        return cnpj_com_digitos(documento[:12]) == documento
    return False


def mutar(pix: dict, caminho: str, valor: any) -> dict:
    """Copia o payload e troca a chave do caminho ("source.device_id").

    Valor None remove a chave, que e o jeito de simular um campo que o
    cliente nao mandou (por exemplo, o GPS desligado). Os niveis que
    faltarem no caminho sao criados.
    """
    copia = copy.deepcopy(pix)
    chaves = caminho.split(".")
    alvo = copia
    for chave in chaves[:-1]:
        if valor is None and not isinstance(alvo.get(chave), dict):
            return copia
        alvo = alvo.setdefault(chave, {})
    if valor is None:
        alvo.pop(chaves[-1], None)
    else:
        alvo[chaves[-1]] = copy.deepcopy(valor)
    return copia


def pix_normal(**overrides) -> dict:
    """Um Pix que nao deveria acender regra nenhuma.

    R$ 50,00 as 14h de um sabado, no app, em Sao Paulo, entre duas contas
    abertas ha anos. Os overrides aceitam caminho aninhado com "__":
    pix_normal(amount=100, source__device_id="x") troca source.device_id.
    """
    pix = {
        "id": f"pix-{uuid.uuid4()}",
        "amount": 5000,
        "transaction_date": "2026-10-17T14:00:00-03:00",
        "source_account": {
            "branch": "0001",
            "account_number": "000001",
            "opening_date": CONTA_ANTIGA,
            "owner": {"document_number": DOC_PAGADOR_PADRAO},
        },
        "destination_account": {
            "participant": PARTICIPANTE_PADRAO,
            "branch": "0001",
            "account_number": "000002",
            "opening_date": CONTA_ANTIGA,
            "owner": {"document_number": DOC_RECEBEDOR_PADRAO},
        },
        "source": {
            "device_id": "dvc-pagador-padrao",
            "channel": "app",
            "ip": IP_SP,
            "geolocation": dict(GPS_SP),
        },
    }
    for chave, valor in overrides.items():
        pix = mutar(pix, chave.replace("__", "."), valor)
    return pix
