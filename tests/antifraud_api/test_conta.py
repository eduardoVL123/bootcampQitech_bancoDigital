"""A conta e uma so: o titular e a abertura que o motor viu primeiro valem para todos os Pix dela.

Pedido que descreve a conta de outro jeito volta 409 (QIT006007), e nao
`rejected`: e dado contraditorio, nao decisao de fraude. Mascara, letra
minuscula no CNPJ e outro fuso para o mesmo instante nao sao divergencia.
"""
import re
from datetime import timedelta, timezone

from tests.utils.pix import AntifraudApi, Pagador, Recebedor, analisa, mutar, nova_base, pix
from tests.utils.random_generator import RandomGenerator

CASA = "99999999"


def _diverge(resposta, lado):
    assert resposta.status_code == 409, resposta.text
    assert resposta.json()["code"] == "QIT006007"
    assert lado in resposta.json()["description"]


def test_mesma_conta_de_origem_com_outro_cpf_da_409_e_nao_grava_nada():
    hoje, pagador = nova_base(), Pagador()
    analisa(pix(pagador, Recebedor(), 5000, hoje.isoformat()))
    outro = mutar(pix(pagador, Recebedor(), 5000, (hoje + timedelta(minutes=1)).isoformat()),
                  "source_account.owner.document_number", RandomGenerator.generate_cpf())

    resposta = AntifraudApi.post(outro)

    _diverge(resposta, "source_account")
    assert AntifraudApi.get(outro["id"]).status_code == 404


def test_conta_de_cpf_nao_vira_cnpj():
    hoje, pagador = nova_base(), Pagador()
    analisa(pix(pagador, Recebedor(), 5000, hoje.isoformat()))
    outro = mutar(pix(pagador, Recebedor(), 5000, (hoje + timedelta(minutes=1)).isoformat()),
                  "source_account.owner.document_number", RandomGenerator.generate_cnpj())

    _diverge(AntifraudApi.post(outro), "source_account")


def test_mesma_conta_com_outra_abertura_da_409():
    hoje, pagador = nova_base(), Pagador()
    analisa(pix(pagador, Recebedor(), 5000, hoje.isoformat()))
    outro = mutar(pix(pagador, Recebedor(), 5000, (hoje + timedelta(minutes=1)).isoformat()),
                  "source_account.opening_date", (pagador.aberta_em + timedelta(days=1)).isoformat())

    _diverge(AntifraudApi.post(outro), "source_account")


def test_mesma_conta_de_destino_com_outro_titular_da_409():
    hoje, recebedor = nova_base(), Recebedor()
    analisa(pix(Pagador(), recebedor, 5000, hoje.isoformat()))
    outro = mutar(pix(Pagador(), recebedor, 5000, (hoje + timedelta(minutes=1)).isoformat()),
                  "destination_account.owner.document_number", RandomGenerator.generate_cpf())

    _diverge(AntifraudApi.post(outro), "destination_account")


def test_mascara_letra_minuscula_e_outro_fuso_sao_a_mesma_conta():
    hoje, pagador = nova_base(), Pagador()
    recebedor = Recebedor(documento="12.ABC.345/01DE-35")
    analisa(pix(pagador, recebedor, 5000, hoje.isoformat()))
    segundo = pix(pagador, recebedor, 5000, (hoje + timedelta(minutes=1)).isoformat())
    segundo = mutar(segundo, "source_account.owner.document_number", re.sub(r"\D", "", pagador.documento))
    segundo = mutar(segundo, "source_account.opening_date", pagador.aberta_em.astimezone(timezone.utc).isoformat())
    segundo = mutar(segundo, "destination_account.owner.document_number", "12abc34501de35")
    segundo = mutar(segundo, "destination_account.opening_date",
                    recebedor.aberta_em.astimezone(timezone.utc).isoformat().replace("+00:00", "Z"))

    assert AntifraudApi.post(segundo).status_code == 201


def test_conta_da_casa_e_a_mesma_como_destino_e_como_origem():
    hoje, conta = nova_base(), Recebedor(participante=CASA)
    analisa(pix(Pagador(), conta, 5000, hoje.isoformat()))
    impostor = conta.como_pagador()
    impostor.documento = RandomGenerator.generate_cpf()

    paga_igual = AntifraudApi.post(pix(conta.como_pagador(), Recebedor(), 5000, (hoje + timedelta(minutes=1)).isoformat()))
    paga_outro = AntifraudApi.post(pix(impostor, Recebedor(), 5000, (hoje + timedelta(minutes=2)).isoformat()))

    assert paga_igual.status_code == 201
    _diverge(paga_outro, "source_account")


def test_pix_para_a_propria_conta_descreve_a_conta_igual_nas_duas_pontas():
    hoje, conta = nova_base(), Recebedor(participante=CASA)
    mesma = pix(conta.como_pagador(), conta, 5000, hoje.isoformat())
    contraditorio = mutar(pix(conta.como_pagador(), conta, 5000, (hoje + timedelta(minutes=1)).isoformat()),
                          "destination_account.owner.document_number", RandomGenerator.generate_cpf())

    assert AntifraudApi.post(mesma).status_code == 201
    _diverge(AntifraudApi.post(contraditorio), "destination_account")


def test_pedido_recusado_nao_grava_a_outra_conta_nem_gasta_o_id():
    # A conta destino e criada antes da origem (ordem da chave unica), entao o
    # pedido recusado chegou a inseri-la. O rollback a desfaz: outro titular
    # pode estrear essa conta depois, e o id continua livre.
    hoje, pagador, destino = nova_base(), Pagador(), Recebedor()
    analisa(pix(pagador, Recebedor(), 5000, hoje.isoformat()))
    recusado = mutar(pix(pagador, destino, 5000, (hoje + timedelta(minutes=1)).isoformat()),
                     "source_account.owner.document_number", RandomGenerator.generate_cpf())
    _diverge(AntifraudApi.post(recusado), "source_account")

    titular_do_destino = RandomGenerator.generate_cpf()
    estreia = mutar(pix(Pagador(), destino, 5000, (hoje + timedelta(minutes=2)).isoformat()),
                    "destination_account.owner.document_number", titular_do_destino)
    corrigido = mutar(mutar(recusado, "source_account.owner.document_number", pagador.documento),
                      "destination_account.owner.document_number", titular_do_destino)

    assert AntifraudApi.post(estreia).status_code == 201
    assert AntifraudApi.post(corrigido).status_code == 201


def test_mesmo_id_com_outro_titular_continua_sendo_o_409_do_id():
    hoje, pagador = nova_base(), Pagador()
    payload = pix(pagador, Recebedor(), 5000, hoje.isoformat())
    analisa(payload)

    resposta = AntifraudApi.post(mutar(payload, "source_account.owner.document_number", RandomGenerator.generate_cpf()))

    assert resposta.status_code == 409
    assert resposta.json()["code"] == "QIT006004"
