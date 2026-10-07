"""F8: compliance, a fila e a decisão (docs/testes/onboarding-api.md).

PEP, renda fora do padrão ou dados divergentes levam a abertura a
MANUAL_REVIEW, e uma pessoa decide. Compliance vê a fila
(GET /onboardings), aprova ou recusa com justificativa
(PUT /onboarding/{key}/decision), e o histórico guarda quem decidiu e por
quê. Só compliance vê a justificativa e quem decidiu: avisar o suspeito de
uma suspeita de lavagem é proibido (decisão D31).

A abertura em revisão vem do próprio worker, com os birôs regulares no
Mockserver. A fila é do banco inteiro, e não só do teste: os testes
procuram as aberturas deles percorrendo as páginas, e nunca contam o total.
"""
import time

import pytest

from tests.utils.mockserver import (
    account_api_responde,
    biros_regulares,
    pedidos_a_account_api,
    pep_responde,
    receita_fora_do_ar,
    receita_responde,
    sancoes_respondem,
)
from tests.utils.onboarding_api import (
    ANALISTA_DE_COMPLIANCE,
    ESPERA_PELO_WORKER_SEGUNDOS,
    RELOGIO_SIMULADO_LIGADO,
    Onboarding,
    ao_mesmo_tempo,
    cabecalhos_do_gateway,
    campos_e_regras,
    credencial_de_compliance,
    espera_etapa,
    imagens,
    no_passado,
    nova_chave,
    pessoa_fisica,
    so_digitos,
)

ETAPAS_FINAIS = {"ACTIVE", "REJECTED", "MANUAL_REVIEW"}

CAMPOS_DO_ITEM_DA_FILA = {"onboarding_key", "customer_key", "status", "reason_codes", "risk_level", "created_at"}

JUSTIFICATIVA = "PEP confirmado; diligencia reforcada concluida"

# Quanto o teste espera para conferir que o worker não fez nada.
FOLGA_SEGUNDOS = 3


# ----------------------------------------------------------------------
# Preparação
# ----------------------------------------------------------------------

def manda_o_rg(abertura: dict, cabecalhos: dict = None) -> None:
    resposta = Onboarding.envia_rg(abertura["onboarding_key"], abertura["access_token"], imagens("front", "back"), cabecalhos)
    assert resposta.status_code == 202, resposta.text


def analisada(dados: dict, programa_os_biros=biros_regulares) -> tuple:
    """Cadastra, programa os birôs e a account-api, manda o RG e espera o fim
    da análise. Devolve a abertura, o GET do fim e a account_key do mock."""
    abertura = Onboarding.comeca_abertura(dados)
    programa_os_biros(dados)
    account_key = account_api_responde(abertura, dados)
    manda_o_rg(abertura)
    return abertura, espera_etapa(abertura, ETAPAS_FINAIS), account_key


def em_revisao(dados: dict = None) -> tuple:
    """Uma abertura em MANUAL_REVIEW por PEP declarado, a não ser que os dados
    digam outro motivo. Devolve a abertura e a account_key do mock."""
    if dados is None:
        dados = pessoa_fisica(pep_self_declared=True)

    abertura, final, account_key = analisada(dados)
    assert final["status"] == "MANUAL_REVIEW", final
    return abertura, account_key


def sancionada(dados: dict) -> None:
    receita_responde(dados)
    sancoes_respondem(dados, match=True)
    pep_responde(dados)


def percorre_a_fila(parametros: dict = None, limite: int = 100) -> list:
    """Todas as páginas da fila, da primeira à última, com `limite` itens por página."""
    paginas = []
    pagina = 0
    while True:
        resposta = Onboarding.fila(credencial_de_compliance(), {**(parametros or {}), "limit": limite, "page": pagina})
        assert resposta.status_code == 200, resposta.text
        paginas.append(resposta)
        if resposta.json()["is_last_page"]:
            return paginas
        # Uma página vazia que não diz ser a última faria o teste andar para sempre.
        assert resposta.json()["data"], f"pagina {pagina} vazia, mas is_last_page falso"
        pagina = pagina + 1


def itens(paginas: list) -> list:
    return [item for pagina in paginas for item in pagina.json()["data"]]


def chaves(paginas: list) -> list:
    return [item["onboarding_key"] for item in itens(paginas)]


def decide(abertura: dict, decisao: str, justificativa: str = JUSTIFICATIVA):
    return Onboarding.decide(
        abertura["onboarding_key"], credencial_de_compliance(), {"decision": decisao, "justification": justificativa}
    )


def para_compliance(abertura: dict) -> dict:
    resposta = Onboarding.consulta_abertura(abertura["onboarding_key"], credencial_de_compliance())
    assert resposta.status_code == 200, resposta.text
    return resposta.json()


def para_o_dono(abertura: dict) -> dict:
    resposta = Onboarding.consulta_abertura(abertura["onboarding_key"], abertura["access_token"])
    assert resposta.status_code == 200, resposta.text
    return resposta.json()


def historico(corpo: dict) -> list:
    return [evento["status"] for evento in corpo["status_events"]]


def decisoes_no_historico(corpo: dict) -> list:
    return [evento["status"] for evento in corpo["status_events"] if evento["actor"] == "compliance"]


# ----------------------------------------------------------------------
# A fila
# ----------------------------------------------------------------------

class TestFila:
    def test_fila_lista_da_mais_antiga_para_a_mais_nova(self):
        """F8-01 (decisão D30). A fila anda da abertura mais antiga para a mais
        nova, e o filtro de motivo acha quem tem o motivo entre os seus."""
        # prepara: A e depois B, as duas por PEP declarado
        a, _ = em_revisao()
        b, _ = em_revisao()

        # age
        paginas = percorre_a_fila({"reason_code": "PEP_SELF_DECLARED"})

        # confere
        na_fila = chaves(paginas)
        assert na_fila.index(a["onboarding_key"]) < na_fila.index(b["onboarding_key"])
        for item in itens(paginas):
            assert "PEP_SELF_DECLARED" in item["reason_codes"]

    def test_fila_usa_os_valores_padrao(self):
        """F8-02. Sem parâmetros: 10 por página, a primeira página, só MANUAL_REVIEW."""
        # prepara
        em_revisao()

        # age
        resposta = Onboarding.fila(credencial_de_compliance())

        # confere
        assert resposta.status_code == 200, resposta.text
        corpo = resposta.json()
        assert corpo["limit"] == 10
        assert corpo["page"] == 0
        assert 1 <= len(corpo["data"]) <= 10
        assert {item["status"] for item in corpo["data"]} == {"MANUAL_REVIEW"}

    def test_fila_filtra_pela_etapa(self):
        """F8-03. Com status=REJECTED, a fila traz só as recusadas."""
        # prepara: uma recusada por sanção e uma em revisão
        recusada, final, _ = analisada(pessoa_fisica(), sancionada)
        assert final["status"] == "REJECTED"
        revisao, _ = em_revisao()

        # age
        paginas = percorre_a_fila({"status": "REJECTED"})

        # confere
        na_fila = chaves(paginas)
        assert recusada["onboarding_key"] in na_fila
        assert revisao["onboarding_key"] not in na_fila
        assert {item["status"] for item in itens(paginas)} == {"REJECTED"}

    def test_fila_marca_a_ultima_pagina(self):
        """F8-04. Um filtro que não acha nada responde a página vazia, que já é
        a última. Com duas aberturas em revisão, a primeira página de um item
        não é a última. Percorrendo a fila, toda página antes da última vem cheia."""
        # prepara
        em_revisao()
        em_revisao()

        # age
        vazia = Onboarding.fila(credencial_de_compliance(), {"status": "DRAFT", "reason_code": "SANCTIONS_MATCH"})
        de_um_item = Onboarding.fila(credencial_de_compliance(), {"limit": 1})
        paginas = percorre_a_fila(limite=100)

        # confere
        assert vazia.status_code == 200, vazia.text
        assert vazia.json()["data"] == []
        assert vazia.json()["is_last_page"] is True
        assert len(de_um_item.json()["data"]) == 1
        assert de_um_item.json()["is_last_page"] is False
        for pagina in paginas[:-1]:
            assert len(pagina.json()["data"]) == 100
        assert 1 <= len(paginas[-1].json()["data"]) <= 100

    @pytest.mark.parametrize(
        "parametros, campo",
        [
            pytest.param({"limit": "0"}, "limit", id="limit 0"),
            pytest.param({"limit": "101"}, "limit", id="limit 101"),
            pytest.param({"limit": "abc"}, "limit", id="limit abc"),
            pytest.param({"page": "-1"}, "page", id="page -1"),
            pytest.param({"status": "QUALQUER"}, "status", id="status desconhecido"),
            pytest.param({"reason_code": "QUALQUER"}, "reason_code", id="motivo desconhecido"),
            pytest.param({"document_number": "123.456.789-09"}, "document_number", id="parametro a mais"),
        ],
    )
    def test_fila_recusa_parametro_errado(self, parametros, campo):
        """F8-05 (LGPD). Parâmetro fora do formato, valor desconhecido ou
        parâmetro que a rota não tem: 400 ONB000001, dizendo qual. Nenhum dado
        pessoal entra pela URL."""
        # age
        resposta = Onboarding.fila(credencial_de_compliance(), parametros)

        # confere
        assert resposta.status_code == 400, resposta.text
        assert resposta.json()["code"] == "ONB000001"
        assert campo in [erro["field"] for erro in resposta.json()["errors"]]

    def test_itens_da_fila_nao_mostram_dado_pessoal(self):
        """F8-06 (LGPD, decisão D30). O item da fila tem chaves, etapa, motivos,
        risco e data. Nem CPF, nem nome, nem renda."""
        # prepara: uma cliente com nome e renda fáceis de reconhecer, em revisão pela renda
        joana = pessoa_fisica(name="Joana Personalissima", declared_monthly_income_cents=987654321)
        abertura, _ = em_revisao(joana)

        # age
        paginas = percorre_a_fila({"reason_code": "INCOME_PROFILE"})

        # confere
        item = next(item for item in itens(paginas) if item["onboarding_key"] == abertura["onboarding_key"])
        assert set(item) == CAMPOS_DO_ITEM_DA_FILA
        for pagina in paginas:
            for dado in (joana["document_number"], so_digitos(joana["document_number"]), joana["name"], "987654321"):
                assert dado not in pagina.text


# ----------------------------------------------------------------------
# A decisão
# ----------------------------------------------------------------------

class TestDecisao:
    def test_aprovacao_de_compliance_abre_a_conta(self):
        """F8-07 (decisão D31). Compliance aprova com justificativa: a abertura
        fica APPROVED, o worker abre a conta, e o histórico guarda quem
        decidiu e por quê. Os motivos da revisão continuam lá."""
        # prepara
        abertura, account_key = em_revisao()

        # age
        resposta = decide(abertura, "APPROVE")

        # confere: a resposta
        assert resposta.status_code == 202, resposta.text
        assert resposta.json() == {"onboarding_key": abertura["onboarding_key"], "status": "APPROVED", "next_step": "WAIT"}

        # confere: a conta é aberta
        assert espera_etapa(abertura, ETAPAS_FINAIS)["status"] == "ACTIVE"
        final = para_compliance(abertura)
        assert final["account_key"] == account_key
        assert final["reason_codes"] == ["PEP_SELF_DECLARED"]

        # confere: quem decidiu e por quê
        aprovacao = next(evento for evento in final["status_events"] if evento["status"] == "APPROVED")
        assert aprovacao["actor"] == "compliance"
        assert aprovacao["justification"] == JUSTIFICATIVA
        assert aprovacao["decided_by"] == ANALISTA_DE_COMPLIANCE
        assert historico(final)[-3:] == ["MANUAL_REVIEW", "APPROVED", "ACTIVE"]

    def test_recusa_de_compliance_e_definitiva(self):
        """F8-08 (decisão D31). Compliance recusa: REJECTED, o motivo vira
        COMPLIANCE_REJECTED, e a conta nunca é pedida."""
        # prepara
        abertura, _ = em_revisao()

        # age
        resposta = decide(abertura, "REJECT")

        # confere
        assert resposta.status_code == 200, resposta.text
        assert resposta.json() == {"onboarding_key": abertura["onboarding_key"], "status": "REJECTED", "next_step": "NONE"}
        time.sleep(FOLGA_SEGUNDOS)
        final = para_o_dono(abertura)
        assert final["status"] == "REJECTED"
        assert final["reason_codes"] == ["COMPLIANCE_REJECTED"]
        assert pedidos_a_account_api(abertura) == []

    @pytest.mark.parametrize(
        "prepara_a_abertura, etapa",
        [
            pytest.param(lambda: Onboarding.comeca_abertura(), "DRAFT", id="DRAFT"),
            pytest.param(lambda: analisada(pessoa_fisica())[0], "ACTIVE", id="ACTIVE"),
            pytest.param(lambda: analisada(pessoa_fisica(), sancionada)[0], "REJECTED", id="recusada por sancao"),
        ],
    )
    def test_decisao_fora_de_revisao_e_recusada(self, prepara_a_abertura, etapa):
        """F8-09. Só se decide abertura em MANUAL_REVIEW: as outras respondem
        409 ONB005014, e a etapa não muda. Sanção nunca chega a compliance."""
        # prepara
        abertura = prepara_a_abertura()

        # age
        resposta = decide(abertura, "APPROVE")

        # confere
        assert resposta.status_code == 409, resposta.text
        assert resposta.json()["code"] == "ONB005014"
        assert para_compliance(abertura)["status"] == etapa

    @pytest.mark.parametrize(
        "corpo, campo",
        [
            pytest.param({"justification": JUSTIFICATIVA}, "decision", id="sem decision"),
            pytest.param({"decision": "APPROVE"}, "justification", id="sem justification"),
        ],
    )
    def test_decisao_exige_decisao_e_justificativa(self, corpo, campo):
        """F8-10. Sem a decisão ou sem a justificativa: 400 ONB005001, dizendo
        qual falta, e nada muda."""
        # prepara
        abertura, _ = em_revisao()

        # age
        resposta = Onboarding.decide(abertura["onboarding_key"], credencial_de_compliance(), corpo)

        # confere
        assert resposta.status_code == 400, resposta.text
        assert resposta.json()["code"] == "ONB005001"
        assert campos_e_regras(resposta.json()) == [(campo, "required")]
        assert para_compliance(abertura)["status"] == "MANUAL_REVIEW"

    @pytest.mark.parametrize(
        "tamanho, status, regra",
        [
            pytest.param(9, 400, "minimum", id="9 caracteres"),
            pytest.param(501, 400, "maximum", id="501 caracteres"),
            pytest.param(10, 200, None, id="10 caracteres"),
            pytest.param(500, 200, None, id="500 caracteres"),
        ],
    )
    def test_limites_do_tamanho_da_justificativa(self, tamanho, status, regra):
        """F8-11. A justificativa tem de 10 a 500 caracteres. As duas bordas
        passam, e um a menos ou a mais é recusado."""
        # prepara
        abertura, _ = em_revisao()

        # age
        resposta = decide(abertura, "REJECT", "j" * tamanho)

        # confere
        assert resposta.status_code == status, resposta.text
        if regra is not None:
            assert resposta.json()["code"] == "ONB000001"
            assert campos_e_regras(resposta.json()) == [("justification", regra)]

    def test_decisao_so_aceita_approve_ou_reject(self):
        """F8-12. Outra decisão: 400 ONB000001."""
        # prepara
        abertura, _ = em_revisao()

        # age
        resposta = decide(abertura, "MAYBE")

        # confere
        assert resposta.status_code == 400, resposta.text
        assert resposta.json()["code"] == "ONB000001"
        assert campos_e_regras(resposta.json()) == [("decision", "format")]

    def test_decisao_em_abertura_que_nao_existe_responde_404(self):
        """F8-13 (R8). Abertura que ninguém criou: 404 ONB005006."""
        # age
        resposta = Onboarding.decide(nova_chave(), credencial_de_compliance(), {"decision": "APPROVE", "justification": JUSTIFICATIVA})

        # confere
        assert resposta.status_code == 404, resposta.text
        assert resposta.json()["code"] == "ONB005006"

    @pytest.mark.concurrency
    def test_decisoes_simultaneas_valem_uma_vez(self):
        """F8-14. Aprovar e recusar a mesma abertura no mesmo instante: uma
        decisão vale, a outra recebe 409 ONB005014, e o histórico tem uma só."""
        # prepara: cinco aberturas em revisão
        aberturas = [em_revisao()[0] for _ in range(5)]

        for abertura in aberturas:
            # age
            aprovacao, recusa = ao_mesmo_tempo([
                lambda abertura=abertura: decide(abertura, "APPROVE"),
                lambda abertura=abertura: decide(abertura, "REJECT"),
            ])

            # confere
            status = sorted([aprovacao.status_code, recusa.status_code])
            assert status in ([200, 409], [202, 409]), (aprovacao.text, recusa.text)
            perdedora = aprovacao if aprovacao.status_code == 409 else recusa
            assert perdedora.json()["code"] == "ONB005014"
            assert len(decisoes_no_historico(para_compliance(abertura))) == 1

    def test_decisao_exige_a_chave_idempotente(self):
        """F8-15 (decisão D7). Sem a X-Idempotency-Key: 400 ONB000011."""
        # prepara
        abertura, _ = em_revisao()
        cabecalhos = cabecalhos_do_gateway()
        del cabecalhos["X-Idempotency-Key"]

        # age
        resposta = Onboarding.decide(
            abertura["onboarding_key"], credencial_de_compliance(), {"decision": "REJECT", "justification": JUSTIFICATIVA}, cabecalhos
        )

        # confere
        assert resposta.status_code == 400, resposta.text
        assert resposta.json()["code"] == "ONB000011"

    def test_dono_nao_ve_a_justificativa_nem_quem_decidiu(self):
        """F8-16 (decisão D31). O cliente vê a etapa e o motivo, mas não a
        justificativa nem quem decidiu: avisar o suspeito de uma suspeita de
        lavagem é proibido. Compliance continua vendo tudo."""
        # prepara
        abertura, _ = em_revisao()
        segredo = "Justificativa-reservada-de-compliance"
        assert decide(abertura, "REJECT", segredo).status_code == 200

        # age
        resposta = Onboarding.consulta_abertura(abertura["onboarding_key"], abertura["access_token"])

        # confere
        assert resposta.status_code == 200, resposta.text
        for evento in resposta.json()["status_events"]:
            assert "justification" not in evento
            assert "decided_by" not in evento
        assert segredo not in resposta.text
        assert ANALISTA_DE_COMPLIANCE not in resposta.text
        assert para_compliance(abertura)["status_events"][-1]["justification"] == segredo

    @pytest.mark.simulated_clock
    @pytest.mark.skipif(not RELOGIO_SIMULADO_LIGADO, reason="precisa da API e do pytest com SIMULATED_CLOCK_ENABLED=true")
    def test_aprovacao_de_abertura_parada_por_biro_fora_e_recusada(self):
        """F8-17 (decisão D32). Sem KYC aprovado, sem conta: uma abertura parada
        por birô fora nunca terminou as consultas obrigatórias, e compliance não
        pode aprová-la (409 ONB005017). O caminho é a retentativa em lote.
        Recusar continua valendo."""
        # prepara: o RG chegou há 24 h e 1 min, e a Receita não respondeu
        dados = pessoa_fisica()
        abertura = Onboarding.comeca_abertura(dados)
        biros_regulares(dados)
        account_api_responde(abertura, dados)
        receita_fora_do_ar(dados, vezes=3)
        manda_o_rg(abertura, cabecalhos_do_gateway(extras=no_passado(24 * 60 + 1)))
        parada = espera_etapa(abertura, ETAPAS_FINAIS, ESPERA_PELO_WORKER_SEGUNDOS)
        assert parada["reason_codes"] == ["BUREAU_UNAVAILABLE"], parada

        # age
        aprovacao = decide(abertura, "APPROVE")

        # confere
        assert aprovacao.status_code == 409, aprovacao.text
        assert aprovacao.json()["code"] == "ONB005017"
        depois = para_compliance(abertura)
        assert depois["status"] == "MANUAL_REVIEW"
        assert decisoes_no_historico(depois) == []
        assert decide(abertura, "REJECT").status_code == 200
