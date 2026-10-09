"""F9: a outbox e os eventos para a webhook-api (docs/testes/onboarding-api.md).

Toda mudança de etapa que o parceiro precisa saber grava um evento na
outbox, no mesmo COMMIT da mudança. O onboarding-worker entrega cada evento
à webhook-api (POST /internal/event) e repete, com o mesmo event_id, até
ela responder 202 (recebido) ou 200 (já recebido). Os eventos de uma
abertura chegam na ordem em que aconteceram.

A webhook-api fica no Mockserver, que sobe recebendo todo evento com 202. O
teste lê os eventos que chegaram com a onboarding_key dele, e programa por
cima a falha que quer provocar. O contrato com a webhook-api ainda se alinha
com a RFC 06 (pendência P2): se ele mudar, mudam a entrega e estes testes.
"""
import json
import time
from datetime import datetime
from uuid import UUID

import pytest

from tests.utils.mockserver import (
    TOKEN_DE_SERVICO,
    account_api_responde,
    biros_regulares,
    cabecalho,
    corpo,
    eventos_da_abertura,
    pep_responde,
    receita_responde,
    sancoes_respondem,
    webhook_responde,
)
from tests.utils.onboarding_api import (
    ESPERA_PELO_WORKER_SEGUNDOS,
    Onboarding,
    credencial_de_compliance,
    espera_ate,
    espera_etapa,
    imagens,
    pessoa_fisica,
    so_digitos,
)

ETAPAS_FINAIS = {"ACTIVE", "REJECTED", "MANUAL_REVIEW"}

APROVADA = "account.kyc.approved"
CRIADA = "account.created"
RECUSADA = "account.rejected"
EM_REVISAO = "account.kyc.manual_review"

# O que cada evento leva em data (RFC 05, Eventos): só chaves, risco e motivos.
CAMPOS_DO_DATA = {
    APROVADA: {"onboarding_key", "customer_key", "risk_level"},
    CRIADA: {"onboarding_key", "customer_key", "account_key"},
    RECUSADA: {"onboarding_key", "reason_codes"},
    EM_REVISAO: {"onboarding_key", "reason_codes"},
}

CAMPOS_DO_ENVELOPE = {"event_id", "event_type", "occurred_at", "data"}

JUSTIFICATIVA = "Decisao de compliance no teste de eventos"

# Quanto o teste espera, depois do último evento, para conferir que não vem outro.
FOLGA_SEGUNDOS = 3


# ----------------------------------------------------------------------
# Preparação
# ----------------------------------------------------------------------

def manda_o_rg(abertura: dict) -> None:
    resposta = Onboarding.envia_rg(abertura["onboarding_key"], abertura["access_token"], imagens("front", "back"))
    assert resposta.status_code == 202, resposta.text


def analisada(dados: dict, programa_os_biros=biros_regulares, antes_do_rg=None) -> tuple:
    """Cadastra, programa os birôs e a account-api, manda o RG e espera o fim
    da análise. `antes_do_rg` recebe a abertura e programa o que mais o teste
    quiser antes do envio. Devolve a abertura, o GET do fim e a account_key do mock."""
    abertura = Onboarding.comeca_abertura(dados)
    programa_os_biros(dados)
    account_key = account_api_responde(abertura, dados)
    if antes_do_rg is not None:
        antes_do_rg(abertura)
    manda_o_rg(abertura)
    return abertura, espera_etapa(abertura, ETAPAS_FINAIS), account_key


def receita_cancelada(dados: dict) -> None:
    receita_responde(dados, "CANCELADA")
    sancoes_respondem(dados)
    pep_responde(dados)


def sancionada(dados: dict) -> None:
    receita_responde(dados)
    sancoes_respondem(dados, match=True)
    pep_responde(dados)


def decide(abertura: dict, decisao: str) -> None:
    resposta = Onboarding.decide(
        abertura["onboarding_key"], credencial_de_compliance(), {"decision": decisao, "justification": JUSTIFICATIVA}
    )
    assert resposta.status_code in (200, 202), resposta.text


def decide_e_devolve(abertura: dict, decisao: str) -> dict:
    """Compliance decide e devolve a abertura, para caber num caso parametrizado."""
    decide(abertura, decisao)
    return abertura


def espera_eventos(abertura: dict, quantos: int, limite_segundos: float = 20) -> list:
    """Espera chegarem pelo menos `quantos` eventos da abertura e devolve os corpos, na ordem."""
    entregas = espera_ate(lambda: eventos_da_abertura(abertura), lambda chegaram: len(chegaram) >= quantos, limite_segundos)
    return [corpo(entrega) for entrega in entregas]


def tipos(eventos: list) -> list:
    return [evento["event_type"] for evento in eventos]


def o_evento(eventos: list, tipo: str) -> dict:
    return next(evento for evento in eventos if evento["event_type"] == tipo)


# ----------------------------------------------------------------------
# Os testes
# ----------------------------------------------------------------------

class TestEventos:
    def test_aprovacao_publica_aprovada_e_depois_criada(self):
        """F9-01. A abertura aprovada publica account.kyc.approved e depois
        account.created, cada um com o próprio event_id e a hora em que aconteceu."""
        # prepara
        ana = pessoa_fisica()

        # age
        abertura, final, account_key = analisada(ana)

        # confere
        assert final["status"] == "ACTIVE"
        eventos = espera_eventos(abertura, 2)
        assert tipos(eventos) == [APROVADA, CRIADA]
        aprovada, criada = eventos
        assert aprovada["data"] == {
            "onboarding_key": abertura["onboarding_key"],
            "customer_key": abertura["customer_key"],
            "risk_level": "LOW",
        }
        assert criada["data"] == {
            "onboarding_key": abertura["onboarding_key"],
            "customer_key": abertura["customer_key"],
            "account_key": account_key,
        }
        for evento in eventos:
            assert set(evento) == CAMPOS_DO_ENVELOPE
            UUID(evento["event_id"])
            datetime.fromisoformat(evento["occurred_at"])
        assert aprovada["event_id"] != criada["event_id"]

    @pytest.mark.parametrize(
        "prepara, motivo",
        [
            pytest.param(lambda: analisada(pessoa_fisica(), receita_cancelada)[0], "RECEITA_CANCELADA", id="recusa da Receita"),
            pytest.param(
                lambda: decide_e_devolve(analisada(pessoa_fisica(pep_self_declared=True))[0], "REJECT"),
                "COMPLIANCE_REJECTED",
                id="recusa de compliance",
            ),
        ],
    )
    def test_recusa_publica_recusada(self, prepara, motivo):
        """F9-02. A recusa, da Receita ou de compliance, publica account.rejected com os motivos."""
        # prepara e age
        abertura = prepara()

        # confere
        eventos = espera_ate(
            lambda: [corpo(entrega) for entrega in eventos_da_abertura(abertura)],
            lambda chegaram: RECUSADA in tipos(chegaram),
            20,
        )
        assert o_evento(eventos, RECUSADA)["data"] == {"onboarding_key": abertura["onboarding_key"], "reason_codes": [motivo]}

    def test_revisao_publica_revisao(self):
        """F9-03. A abertura que vai para revisão publica account.kyc.manual_review com os motivos."""
        # prepara
        ana = pessoa_fisica(pep_self_declared=True)

        # age
        abertura, final, _ = analisada(ana)

        # confere
        assert final["status"] == "MANUAL_REVIEW"
        eventos = espera_eventos(abertura, 1)
        assert tipos(eventos) == [EM_REVISAO]
        assert eventos[0]["data"] == {"onboarding_key": abertura["onboarding_key"], "reason_codes": ["PEP_SELF_DECLARED"]}

    def test_aprovacao_de_compliance_publica_aprovada(self):
        """F9-04. Compliance aprova: depois da revisão, saem account.kyc.approved e
        account.created, nessa ordem."""
        # prepara
        abertura, _, _ = analisada(pessoa_fisica(pep_self_declared=True))

        # age
        decide(abertura, "APPROVE")

        # confere
        assert tipos(espera_eventos(abertura, 3)) == [EM_REVISAO, APROVADA, CRIADA]

    def test_eventos_nao_levam_dado_pessoal(self):
        """F9-05 (LGPD). Nenhum evento leva CPF, nome, renda nem data de
        nascimento: data tem só os campos da tabela da RFC."""
        # prepara: três pessoas fáceis de reconhecer: uma aprovada, uma recusada e uma em revisão pela renda
        pessoas = [
            (pessoa_fisica(name="Joana Personalissima", declared_monthly_income_cents=987654), biros_regulares, 2),
            (pessoa_fisica(name="Bruna Sancionadissima", declared_monthly_income_cents=876543), sancionada, 1),
            (pessoa_fisica(name="Carla Rendadissima", declared_monthly_income_cents=987654321), biros_regulares, 1),
        ]

        for dados, programa_os_biros, quantos in pessoas:
            # age
            abertura, _, _ = analisada(dados, programa_os_biros)

            # confere
            eventos = espera_eventos(abertura, quantos)
            for evento in eventos:
                assert set(evento["data"]) == CAMPOS_DO_DATA[evento["event_type"]]
                texto = json.dumps(evento, ensure_ascii=False)
                pessoais = [dados["document_number"], so_digitos(dados["document_number"]), dados["name"]]
                pessoais += [str(dados["declared_monthly_income_cents"]), dados["birth_date"]]
                for dado in pessoais:
                    assert dado not in texto

    def test_cada_mudanca_publica_uma_vez(self):
        """F9-06. Cada evento chega uma vez só, e DRAFT, PENDING_KYC e ANALYSIS
        não publicam nada."""
        # prepara e age
        abertura, _, _ = analisada(pessoa_fisica())

        # confere: o último evento chegou, e nada mais vem depois dele
        espera_eventos(abertura, 2)
        time.sleep(FOLGA_SEGUNDOS)
        assert tipos([corpo(entrega) for entrega in eventos_da_abertura(abertura)]) == [APROVADA, CRIADA]

    def test_eventos_vao_com_service_token(self):
        """F9-08. Toda entrega à webhook-api se apresenta com o SERVICE-TOKEN."""
        # prepara e age
        abertura, _, _ = analisada(pessoa_fisica())

        # confere
        espera_eventos(abertura, 2)
        for entrega in eventos_da_abertura(abertura):
            assert cabecalho(entrega, "SERVICE-TOKEN") == TOKEN_DE_SERVICO


class TestEntrega:
    @pytest.mark.slow
    @pytest.mark.parametrize(
        "status, atraso_segundos",
        [pytest.param(503, None, id="webhook com 503"), pytest.param(202, 4, id="webhook demora 4 s")],
    )
    def test_webhook_fora_reenvia_o_mesmo_event_id(self, status, atraso_segundos):
        """F9-07 (decisão D33). A primeira entrega falha (503, ou resposta depois
        do prazo de 3 s): o evento é entregue de novo perto de 1 minuto depois,
        com o mesmo event_id. account.created espera: os eventos de uma
        abertura chegam na ordem."""
        # prepara: a webhook-api falha só na primeira entrega desta abertura
        dados = pessoa_fisica()

        # age
        abertura, _, _ = analisada(dados, antes_do_rg=lambda abertura: webhook_responde(abertura, status, 1, atraso_segundos))
        espera_eventos(abertura, 1)
        falhou_em = time.monotonic()

        # confere
        eventos = espera_eventos(abertura, 3, ESPERA_PELO_WORKER_SEGUNDOS)
        assert time.monotonic() - falhou_em >= 50
        assert tipos(eventos) == [APROVADA, APROVADA, CRIADA]
        assert eventos[0]["event_id"] == eventos[1]["event_id"]

    @pytest.mark.slow
    def test_evento_ja_recebido_nao_e_reenviado(self):
        """F9-09 (decisão D33). A webhook-api responde 200, já recebido: também é
        entregue, e nenhum evento sai de novo, nem 1 minuto depois."""
        # prepara: a webhook-api responde 200 a todo evento desta abertura
        dados = pessoa_fisica()

        # age
        abertura, _, _ = analisada(dados, antes_do_rg=lambda abertura: webhook_responde(abertura, 200))
        espera_eventos(abertura, 2)
        time.sleep(70)

        # confere
        assert tipos([corpo(entrega) for entrega in eventos_da_abertura(abertura)]) == [APROVADA, CRIADA]
