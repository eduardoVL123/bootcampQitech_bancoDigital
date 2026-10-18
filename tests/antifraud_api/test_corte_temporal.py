"""O historico de um instante so ve as confirmacoes de 2FA que ja tinham acontecido.

Um Pix das 10h confirmado as 10h05 era, as 10h03, um desafio pendente: nao
era dinheiro que saiu, e ainda era uma decisao restritiva. A confirmacao ja
esta gravada quando a analise das 10h03 chega (o PATCH vem antes, aqui): o
que vale e a event_date, nao a ordem de chegada.

As referencias congeladas no inicio do dia param nele, exclusivo: o Pix da
meia-noite e a confirmacao de hoje so entram na regua de amanha.
"""
from datetime import timedelta
from uuid import uuid4

from tests.utils.pix import (
    RECEBEDOR_MARCACAO_CRITICA, AntifraudApi, Pagador, Recebedor, analisa, disparou, historico, nova_base, pix, regra,
)


def _desafio_confirmado_em(pagador, recebedor, valor, quando, confirmado_em, **over):
    """Um Pix que pediu 2FA, com a confirmacao gravada agora, mas datada de `confirmado_em`."""
    payload = pix(pagador, recebedor, valor, quando.isoformat(), **over)
    assert analisa(payload)["status"] == "two_factor_required"
    resposta = AntifraudApi.patch(payload["id"], {"challenge_result": "approved_by_client",
                                                  "event_date": confirmado_em.isoformat()})
    assert resposta.status_code == 200, resposta.text


def test_montante_so_soma_o_desafio_a_partir_da_confirmacao():
    # R$ 30 mil as 10h, confirmados as 10h05, mais R$ 25 mil: passa dos R$ 50
    # mil em 24h so no instante da confirmacao, nao antes.
    hoje, pagador, recebedor = nova_base(), Pagador(), Recebedor()
    _desafio_confirmado_em(pagador, recebedor, 3000000, hoje, hoje + timedelta(minutes=5))

    antes = analisa(pix(pagador, recebedor, 2500000, (hoje + timedelta(minutes=3)).isoformat()))
    no_instante = analisa(pix(pagador, recebedor, 2500000, (hoje + timedelta(minutes=5)).isoformat()))

    assert antes["status"] != "approved"
    assert not disparou(antes, "MONTANTE_24H")
    assert disparou(no_instante, "MONTANTE_24H")


def test_desafio_confirmado_depois_ainda_era_restritivo_antes_da_confirmacao():
    hoje = nova_base()
    cedo, tarde = (Pagador(), Recebedor()), (Pagador(), Recebedor())
    for pagador, recebedor in (cedo, tarde):
        _desafio_confirmado_em(pagador, recebedor, 3000000, hoje, hoje + timedelta(minutes=5))

    antes = analisa(pix(*cedo, 2500000, (hoje + timedelta(minutes=3)).isoformat()))
    depois = analisa(pix(*tarde, 2500000, (hoje + timedelta(minutes=6)).isoformat()))

    assert disparou(antes, "SONDAGEM_DE_LIMITE")
    assert regra(antes, "SONDAGEM_DE_LIMITE")["raw_points"] == 30
    assert not disparou(depois, "SONDAGEM_DE_LIMITE")


def _nove_pagamentos(pagador, hoje):
    """Nove aprovados em dias anteriores: um a menos que a referencia `payer` do PERFIL pede."""
    historico(pagador, [10000] * 9, (hoje - timedelta(days=12)).replace(hour=11), timedelta(days=1),
              recebedores_novos=True)


def _perfil_avaliavel(corpo) -> bool:
    if "PERFIL" in corpo["metadata"]["rules_not_triggered"]:
        return True
    return regra(corpo, "PERFIL")["evaluation"] != "not_evaluable"


def test_pix_da_meia_noite_fica_fora_da_referencia_do_dia():
    hoje = nova_base()
    meia_noite = hoje.replace(hour=0, minute=0, second=0)
    ontem, hoje_cedo = Pagador(), Pagador()
    for pagador, decimo in ((ontem, meia_noite - timedelta(minutes=1)), (hoje_cedo, meia_noite)):
        _nove_pagamentos(pagador, hoje)
        assert analisa(pix(pagador, Recebedor(), 10000, decimo.isoformat()))["status"] == "approved"

    com_o_de_ontem = analisa(pix(ontem, Recebedor(), 10000, hoje.isoformat()))
    com_o_da_meia_noite = analisa(pix(hoje_cedo, Recebedor(), 10000, hoje.isoformat()))

    assert _perfil_avaliavel(com_o_de_ontem)
    assert not _perfil_avaliavel(com_o_da_meia_noite)


def test_confirmacao_de_hoje_fica_fora_da_referencia_do_dia():
    # O decimo pagamento e de ontem, mas so virou dinheiro quando o cliente
    # confirmou. Confirmado hoje cedo, ele ainda nao estava na regua congelada
    # no inicio do dia.
    hoje = nova_base()
    meia_noite = hoje.replace(hour=0, minute=0, second=0)
    ontem, hoje_cedo = Pagador(), Pagador()
    for pagador, confirmado_em in ((ontem, meia_noite - timedelta(hours=1)),
                                   (hoje_cedo, meia_noite + timedelta(hours=9))):
        _nove_pagamentos(pagador, hoje)
        _desafio_confirmado_em(pagador, Recebedor(), 2500000, meia_noite - timedelta(hours=9), confirmado_em)

    confirmado_ontem = analisa(pix(ontem, Recebedor(), 10000, hoje.isoformat()))
    confirmado_hoje = analisa(pix(hoje_cedo, Recebedor(), 10000, hoje.isoformat()))

    assert _perfil_avaliavel(confirmado_ontem)
    assert not _perfil_avaliavel(confirmado_hoje)


def test_aparelho_so_fica_cadastrado_no_instante_da_confirmacao():
    hoje, titular, recebedor = nova_base(), Pagador(), Recebedor()
    analisa(pix(titular, recebedor, 5000, (hoje - timedelta(days=1)).isoformat()))
    novo = f"dvc-{uuid4().hex[:12]}"
    _desafio_confirmado_em(titular, recebedor, 50000, hoje, hoje + timedelta(minutes=5), aparelho=novo)

    antes = analisa(pix(titular, recebedor, 30000, (hoje + timedelta(minutes=3)).isoformat(), aparelho=novo))
    depois = analisa(pix(titular, recebedor, 30000, (hoje + timedelta(minutes=6)).isoformat(), aparelho=novo))

    assert disparou(antes, "APARELHO_NAO_CADASTRADO")
    assert not disparou(depois, "APARELHO_NAO_CADASTRADO")


def test_rede_so_usa_a_aresta_da_ancora_depois_da_confirmacao():
    # A aresta b do grafo (ancora -> meio) pediu 2FA e foi confirmada em hoje + 1 min.
    hoje = nova_base()
    ancora, meio, destino = Pagador(documento=RECEBEDOR_MARCACAO_CRITICA), Recebedor(), Recebedor()
    _desafio_confirmado_em(ancora, meio, 2500000, hoje - timedelta(days=2), hoje + timedelta(minutes=1))
    analisa(pix(meio.como_pagador(), destino, 5000, (hoje - timedelta(days=1)).isoformat()))

    antes = analisa(pix(Pagador(), destino, 5000, hoje.isoformat()))
    depois = analisa(pix(Pagador(), destino, 5000, (hoje + timedelta(minutes=2)).isoformat()))

    assert not disparou(antes, "REDE_SUSPEITA")
    assert regra(depois, "REDE_SUSPEITA")["hops"] == 2


def test_rede_so_usa_a_aresta_do_destino_depois_da_confirmacao():
    # Agora e a aresta a (meio -> destino) que pediu 2FA.
    hoje = nova_base()
    ancora, meio, destino = Pagador(documento=RECEBEDOR_MARCACAO_CRITICA), Recebedor(), Recebedor()
    analisa(pix(ancora, meio, 5000, (hoje - timedelta(days=2)).isoformat()))
    _desafio_confirmado_em(meio.como_pagador(), destino, 2500000, hoje - timedelta(days=1), hoje + timedelta(minutes=1))

    antes = analisa(pix(Pagador(), destino, 5000, hoje.isoformat()))
    depois = analisa(pix(Pagador(), destino, 5000, (hoje + timedelta(minutes=2)).isoformat()))

    assert not disparou(antes, "REDE_SUSPEITA")
    assert regra(depois, "REDE_SUSPEITA")["hops"] == 2
