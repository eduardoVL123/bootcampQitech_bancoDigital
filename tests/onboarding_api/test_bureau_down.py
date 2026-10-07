"""F7: birô fora do ar (docs/testes/onboarding-api.md).

Na dúvida, não aprova: com um birô sem resposta, a abertura não é aprovada
nem recusada. O worker repete a consulta na hora (até 2 retentativas), tenta
a abertura de novo em 1, 5, 15 e 60 minutos e, com 24 horas na fila, passa a
decisão a compliance (MANUAL_REVIEW, BUREAU_UNAVAILABLE). Com 5 consultas
seguidas sem resposta, o circuito do birô abre por 30 s. Quando o birô
volta, compliance devolve as aberturas à fila em lote.

O birô fora é simulado no Mockserver, preso ao documento do teste: 503,
atraso de 3 s ou conexão derrubada, só nas chamadas que o teste precisa.
Depois delas, o birô volta a responder: a abertura que sobra do teste
termina sozinha, sem deixar falha para os próximos.

O circuito é de todos os testes ao mesmo tempo, como seria de todos os
clientes. Por isso os testes que provocam falha começam com o circuito da
Receita fechado (fixture circuito_da_receita_fechado), e os que abrem o
circuito ou mexem na chamada de teste dos birôs são global_state e rodam
no fim da fila.
"""
import time

import pytest

from tests.utils.mockserver import (
    ROTA_DA_RECEITA,
    ROTA_DAS_SANCOES,
    ROTA_DO_PEP,
    PRIORIDADE_DA_FALHA,
    Mockserver,
    account_api_responde,
    biros_regulares,
    pedidos_a_account_api,
    pedidos_a_receita,
    pedidos_aos_biros,
    receita_demora,
    receita_derruba_a_conexao,
    receita_fora_do_ar,
    saude_do_biro,
)
from tests.utils.onboarding_api import (
    ESPERA_PELO_WORKER_SEGUNDOS,
    RELOGIO_SIMULADO_LIGADO,
    Onboarding,
    cabecalhos_do_gateway,
    campos_e_regras,
    credencial_de_compliance,
    espera_ate,
    espera_etapa,
    imagens,
    no_passado,
    pessoa_fisica,
)

# Onde a análise termina. ANALYSIS e APPROVED não estão aqui: são passagem.
ETAPAS_FINAIS = {"ACTIVE", "REJECTED", "MANUAL_REVIEW"}

# Um minuto antes e um minuto depois das 24 horas na fila.
QUASE_24_HORAS_EM_MINUTOS = 24 * 60 - 1
MAIS_DE_24_HORAS_EM_MINUTOS = 24 * 60 + 1

# Uma tentativa da abertura chama o birô até três vezes: uma e mais 2 retentativas.
CHAMADAS_POR_TENTATIVA = 3

# Quanto o teste espera, depois do que viu, para conferir que nada mais aconteceu.
FOLGA_SEGUNDOS = 3

so_com_relogio_simulado = [
    pytest.mark.simulated_clock,
    pytest.mark.skipif(not RELOGIO_SIMULADO_LIGADO, reason="precisa da API e do pytest com SIMULATED_CLOCK_ENABLED=true"),
]


# ----------------------------------------------------------------------
# Preparação
# ----------------------------------------------------------------------

def prepara_abertura(dados: dict) -> dict:
    """Cadastra e programa, por baixo de tudo, os três birôs regulares e a
    account-api. O teste programa por cima a falha que quer provocar."""
    abertura = Onboarding.comeca_abertura(dados)
    biros_regulares(dados)
    account_api_responde(abertura, dados)
    return abertura


def manda_o_rg(abertura: dict, minutos_atras: int = None) -> None:
    """Manda o RG completo. Com `minutos_atras`, o envio acontece no passado
    (relógio simulado), e é dali que contam as 24 horas na fila."""
    cabecalhos = None
    if minutos_atras is not None:
        cabecalhos = cabecalhos_do_gateway(extras=no_passado(minutos_atras))

    resposta = Onboarding.envia_rg(abertura["onboarding_key"], abertura["access_token"], imagens("front", "back"), cabecalhos)
    assert resposta.status_code == 202, resposta.text


def consulta(abertura: dict) -> dict:
    resposta = Onboarding.consulta_abertura(abertura["onboarding_key"], abertura["access_token"])
    assert resposta.status_code == 200, resposta.text
    return resposta.json()


def historico(corpo: dict) -> list:
    return [evento["status"] for evento in corpo["status_events"]]


def espera_chamadas_a_receita(dados: dict, quantas: int) -> None:
    espera_ate(lambda: len(pedidos_a_receita(dados)), lambda chamadas: chamadas >= quantas, 20)


def abertura_parada_por_biro_fora(falhas_da_receita: int = CHAMADAS_POR_TENTATIVA) -> tuple:
    """Uma abertura em MANUAL_REVIEW com BUREAU_UNAVAILABLE: o RG chegou há
    24 horas e 1 minuto, e a Receita falhou nas `falhas_da_receita` chamadas
    seguintes. Depois delas, a Receita volta a responder regular."""
    dados = pessoa_fisica()
    abertura = prepara_abertura(dados)
    receita_fora_do_ar(dados, vezes=falhas_da_receita)
    manda_o_rg(abertura, minutos_atras=MAIS_DE_24_HORAS_EM_MINUTOS)

    parada = espera_etapa(abertura, ETAPAS_FINAIS)
    assert parada["reason_codes"] == ["BUREAU_UNAVAILABLE"], parada
    return dados, abertura


def retenta(abertura: dict):
    """Compliance pede a retentativa em lote só desta abertura."""
    return Onboarding.retenta_em_lote({"onboarding_keys": [abertura["onboarding_key"]]}, credencial_de_compliance())


@pytest.fixture
def circuito_da_receita_fechado():
    """Uma análise regular passa antes do teste. O circuito abre com 5 falhas
    seguidas, e uma resposta da Receita zera a contagem: assim, as falhas do
    teste contam do zero, não importa o que rodou antes. Se o circuito estiver
    aberto, a análise espera ele fechar (a nova tentativa vem em 1 minuto)."""
    dados = pessoa_fisica()
    abertura = prepara_abertura(dados)
    manda_o_rg(abertura)
    assert espera_etapa(abertura, ETAPAS_FINAIS, ESPERA_PELO_WORKER_SEGUNDOS)["status"] == "ACTIVE"


# ----------------------------------------------------------------------
# Respostas fora do contrato (F7-13), uma por birô
# ----------------------------------------------------------------------

def receita_sem_situacao(dados: dict) -> None:
    resposta = {"name": dados["name"], "birth_date": dados["birth_date"], "protocol": "RF-sem-situacao"}
    Mockserver.programa(ROTA_DA_RECEITA, {"document_number": dados["document_number"]}, 200, resposta, 1, PRIORIDADE_DA_FALHA)


def receita_com_404(dados: dict) -> None:
    """O corpo seria de quem está regular, mas o status não é o do contrato."""
    resposta = {"situacao": "REGULAR", "name": dados["name"], "birth_date": dados["birth_date"], "protocol": "RF-404"}
    Mockserver.programa(ROTA_DA_RECEITA, {"document_number": dados["document_number"]}, 404, resposta, 1, PRIORIDADE_DA_FALHA)


def sancoes_sem_match(dados: dict) -> None:
    resposta = {"protocol": "SC-sem-match"}
    Mockserver.programa(ROTA_DAS_SANCOES, {"document_number": dados["document_number"]}, 200, resposta, 1, PRIORIDADE_DA_FALHA)


def pep_sem_pep(dados: dict) -> None:
    resposta = {"protocol": "PEP-sem-pep"}
    Mockserver.programa(ROTA_DO_PEP, {"document_number": dados["document_number"]}, 200, resposta, 1, PRIORIDADE_DA_FALHA)


# ----------------------------------------------------------------------
# Os testes
# ----------------------------------------------------------------------

@pytest.mark.usefixtures("circuito_da_receita_fechado")
class TestBiroFora:
    def test_biro_fora_mantem_em_analise(self):
        """F7-01. A Receita responde 503: o worker chama três vezes (uma e mais
        2 retentativas) e deixa para depois. Na dúvida, não aprova nem recusa:
        a abertura fica em ANALYSIS, sem nada da análise gravado, as listas não
        são consultadas e a conta nunca é pedida."""
        # prepara: a Receita falha nas três chamadas desta tentativa, e depois volta
        ana = pessoa_fisica()
        abertura = prepara_abertura(ana)
        receita_fora_do_ar(ana, vezes=CHAMADAS_POR_TENTATIVA)

        # age
        manda_o_rg(abertura)

        # confere: três chamadas e, segundos depois, ainda três (o worker não insiste na hora)
        espera_chamadas_a_receita(ana, CHAMADAS_POR_TENTATIVA)
        time.sleep(FOLGA_SEGUNDOS)
        assert pedidos_aos_biros(ana) == [ROTA_DA_RECEITA] * CHAMADAS_POR_TENTATIVA

        final = consulta(abertura)
        assert final["status"] == "ANALYSIS"
        assert final["next_step"] == "WAIT"
        assert final["checks"] == []
        assert final["reason_codes"] == []
        assert pedidos_a_account_api(abertura) == []

    def test_timeout_do_biro_conta_como_falha(self):
        """F7-02. Cada chamada tem 2 s de prazo. A Receita responde regular,
        mas depois de 3 s: a resposta chega tarde e não vale. São três
        chamadas, e a abertura fica em ANALYSIS."""
        # prepara: as três chamadas desta tentativa demoram 3 s
        ana = pessoa_fisica()
        abertura = prepara_abertura(ana)
        receita_demora(ana, segundos=3, vezes=CHAMADAS_POR_TENTATIVA)

        # age
        manda_o_rg(abertura)

        # confere
        espera_chamadas_a_receita(ana, CHAMADAS_POR_TENTATIVA)
        time.sleep(FOLGA_SEGUNDOS)
        assert pedidos_aos_biros(ana) == [ROTA_DA_RECEITA] * CHAMADAS_POR_TENTATIVA
        assert consulta(abertura)["status"] == "ANALYSIS"
        assert pedidos_a_account_api(abertura) == []

    def test_conexao_derrubada_conta_como_falha(self):
        """F7-03. A Receita fecha a conexão sem responder: é falha, como o 503."""
        # prepara
        ana = pessoa_fisica()
        abertura = prepara_abertura(ana)
        receita_derruba_a_conexao(ana, vezes=CHAMADAS_POR_TENTATIVA)

        # age
        manda_o_rg(abertura)

        # confere
        espera_chamadas_a_receita(ana, CHAMADAS_POR_TENTATIVA)
        time.sleep(FOLGA_SEGUNDOS)
        assert pedidos_aos_biros(ana) == [ROTA_DA_RECEITA] * CHAMADAS_POR_TENTATIVA
        assert consulta(abertura)["status"] == "ANALYSIS"

    @pytest.mark.slow
    def test_biro_de_volta_retoma_a_analise(self):
        """F7-04. A Receita falha numa tentativa e volta. A nova tentativa vem
        1 minuto depois, e não antes, e a análise segue até ACTIVE, como se
        nada tivesse acontecido: sem etapa repetida no histórico."""
        # prepara
        ana = pessoa_fisica()
        abertura = prepara_abertura(ana)
        receita_fora_do_ar(ana, vezes=CHAMADAS_POR_TENTATIVA)

        # age
        manda_o_rg(abertura)
        espera_chamadas_a_receita(ana, CHAMADAS_POR_TENTATIVA)
        falhou_em = time.monotonic()

        # confere
        final = espera_etapa(abertura, {"ACTIVE"}, ESPERA_PELO_WORKER_SEGUNDOS)
        assert time.monotonic() - falhou_em >= 50
        assert len(pedidos_a_receita(ana)) == CHAMADAS_POR_TENTATIVA + 1
        assert historico(final) == ["DRAFT", "PENDING_KYC", "ANALYSIS", "APPROVED", "ACTIVE"]
        assert len(final["checks"]) == 4


@pytest.mark.usefixtures("circuito_da_receita_fechado")
class TestEsperaDe24Horas:
    pytestmark = so_com_relogio_simulado

    def test_biro_fora_por_24h_vai_para_revisao(self):
        """F7-05. O RG ficou completo há 24 horas e 1 minuto, e a Receita
        continua sem responder: o worker não espera mais e passa a decisão a
        compliance (MANUAL_REVIEW, BUREAU_UNAVAILABLE), sem aprovar nem recusar."""
        # prepara
        ana = pessoa_fisica()
        abertura = prepara_abertura(ana)
        receita_fora_do_ar(ana, vezes=CHAMADAS_POR_TENTATIVA)

        # age: o RG chega "há 24 h e 1 min", pelo relógio simulado
        manda_o_rg(abertura, minutos_atras=MAIS_DE_24_HORAS_EM_MINUTOS)

        # confere
        final = espera_etapa(abertura, ETAPAS_FINAIS)
        assert final["status"] == "MANUAL_REVIEW"
        assert final["next_step"] == "WAIT"
        assert final["reason_codes"] == ["BUREAU_UNAVAILABLE"]
        assert final["risk_level"] is None
        assert final["checks"] == []
        assert historico(final) == ["DRAFT", "PENDING_KYC", "ANALYSIS", "MANUAL_REVIEW"]
        assert pedidos_a_account_api(abertura) == []

    def test_biro_fora_por_menos_de_24h_continua_em_analise(self):
        """F7-06. A borda das 24 horas: com o RG completo há 23 horas e 59
        minutos, a abertura ainda espera o birô em ANALYSIS."""
        # prepara
        ana = pessoa_fisica()
        abertura = prepara_abertura(ana)
        receita_fora_do_ar(ana, vezes=CHAMADAS_POR_TENTATIVA)

        # age
        manda_o_rg(abertura, minutos_atras=QUASE_24_HORAS_EM_MINUTOS)

        # confere
        espera_chamadas_a_receita(ana, CHAMADAS_POR_TENTATIVA)
        time.sleep(FOLGA_SEGUNDOS)
        final = consulta(abertura)
        assert final["status"] == "ANALYSIS"
        assert final["reason_codes"] == []


@pytest.mark.usefixtures("circuito_da_receita_fechado")
class TestRespostaForaDoContrato:
    pytestmark = so_com_relogio_simulado

    @pytest.mark.parametrize(
        "responde_fora_do_contrato, rota",
        [
            pytest.param(receita_sem_situacao, ROTA_DA_RECEITA, id="Receita sem situacao"),
            pytest.param(receita_com_404, ROTA_DA_RECEITA, id="Receita com 404 e corpo de regular"),
            pytest.param(sancoes_sem_match, ROTA_DAS_SANCOES, id="sancoes sem match"),
            pytest.param(pep_sem_pep, ROTA_DO_PEP, id="PEP sem pep"),
        ],
    )
    def test_resposta_fora_do_contrato_conta_como_biro_sem_resposta(self, responde_fora_do_contrato, rota):
        """F7-13 (decisão D15). O contrato é 200 com o campo principal
        (situacao, match ou pep). Qualquer outra resposta não diz nada: não
        aprova, não recusa e não é repetida na hora. Com o RG completo há mais
        de 24 horas, a abertura vai direto para compliance."""
        # prepara: o birô responde fora do contrato uma vez, e depois volta ao contrato
        ana = pessoa_fisica()
        abertura = prepara_abertura(ana)
        responde_fora_do_contrato(ana)

        # age
        manda_o_rg(abertura, minutos_atras=MAIS_DE_24_HORAS_EM_MINUTOS)

        # confere
        final = espera_etapa(abertura, ETAPAS_FINAIS)
        assert final["status"] == "MANUAL_REVIEW"
        assert final["reason_codes"] == ["BUREAU_UNAVAILABLE"]
        assert final["checks"] == []
        assert pedidos_aos_biros(ana).count(rota) == 1
        assert pedidos_a_account_api(abertura) == []


class TestRetentativaEmLote:
    @pytest.mark.usefixtures("circuito_da_receita_fechado")
    @pytest.mark.simulated_clock
    @pytest.mark.skipif(not RELOGIO_SIMULADO_LIGADO, reason="precisa da API e do pytest com SIMULATED_CLOCK_ENABLED=true")
    def test_retentativa_em_lote_devolve_para_a_fila(self):
        """F7-08. O birô voltou: compliance manda refazer a análise da abertura
        parada por birô fora. Ela volta para a fila (PENDING_KYC), com
        compliance no histórico, e a análise segue até ACTIVE."""
        # prepara
        _, abertura = abertura_parada_por_biro_fora()

        # age
        resposta = retenta(abertura)

        # confere
        assert resposta.status_code == 202, resposta.text
        assert resposta.json() == {"requeued_count": 1}

        final = espera_etapa(abertura, {"ACTIVE"})
        assert historico(final) == [
            "DRAFT", "PENDING_KYC", "ANALYSIS", "MANUAL_REVIEW", "PENDING_KYC", "ANALYSIS", "APPROVED", "ACTIVE"
        ]
        assert final["status_events"][4]["actor"] == "compliance"
        assert final["reason_codes"] == []
        assert [check["result"] for check in final["checks"]] == ["PASS"] * 4

    @pytest.mark.parametrize(
        "cria_os_dados, motivo",
        [
            pytest.param(lambda: pessoa_fisica(pep_self_declared=True), "PEP_SELF_DECLARED", id="PEP declarado"),
            pytest.param(lambda: pessoa_fisica(declared_monthly_income_cents=50000001), "INCOME_PROFILE", id="renda fora do padrao"),
        ],
    )
    def test_retentativa_em_lote_mantem_os_outros_motivos(self, cria_os_dados, motivo):
        """F7-09. Só birô fora volta para a fila. PEP e renda fora do padrão
        continuam com compliance, mesmo com a chave na lista."""
        # prepara
        dados = cria_os_dados()
        abertura = prepara_abertura(dados)
        manda_o_rg(abertura)
        antes = espera_etapa(abertura, ETAPAS_FINAIS)
        assert antes["reason_codes"] == [motivo]

        # age
        resposta = retenta(abertura)

        # confere
        assert resposta.status_code == 202, resposta.text
        assert resposta.json() == {"requeued_count": 0}
        depois = consulta(abertura)
        assert depois["status"] == "MANUAL_REVIEW"
        assert depois["status_events"] == antes["status_events"]

    @pytest.mark.usefixtures("circuito_da_receita_fechado")
    @pytest.mark.simulated_clock
    @pytest.mark.skipif(not RELOGIO_SIMULADO_LIGADO, reason="precisa da API e do pytest com SIMULATED_CLOCK_ENABLED=true")
    @pytest.mark.parametrize("corpo", [pytest.param({}, id="corpo vazio"), pytest.param(None, id="sem corpo")])
    def test_retentativa_sem_chaves_pega_todas_com_biro_fora(self, corpo):
        """F7-10. Sem a lista de chaves, a retentativa vale para todas as
        aberturas paradas por birô fora, inclusive a deste teste."""
        # prepara
        _, abertura = abertura_parada_por_biro_fora()

        # age
        resposta = Onboarding.retenta_em_lote(corpo, credencial_de_compliance())

        # confere
        assert resposta.status_code == 202, resposta.text
        assert resposta.json()["requeued_count"] >= 1

        final = espera_etapa(abertura, {"ACTIVE"}, ESPERA_PELO_WORKER_SEGUNDOS)
        assert historico(final)[3:5] == ["MANUAL_REVIEW", "PENDING_KYC"]

    @pytest.mark.slow
    @pytest.mark.usefixtures("circuito_da_receita_fechado")
    @pytest.mark.simulated_clock
    @pytest.mark.skipif(not RELOGIO_SIMULADO_LIGADO, reason="precisa da API e do pytest com SIMULATED_CLOCK_ENABLED=true")
    def test_retentativa_recomeca_a_contagem_das_24h(self):
        """F7-14 (decisão D28). A retentativa em lote recomeça a contagem das
        24 horas e das tentativas: se o birô falhar de novo logo depois, a
        abertura espera em ANALYSIS, e não volta direto para compliance, e a
        próxima tentativa vem em 1 minuto, como na primeira vez."""
        # prepara: a Receita falha na primeira análise e também na seguinte, e só depois volta
        ana, abertura = abertura_parada_por_biro_fora(falhas_da_receita=2 * CHAMADAS_POR_TENTATIVA)

        # age
        resposta = retenta(abertura)

        # confere: a falha depois da retentativa deixa a abertura esperando
        assert resposta.status_code == 202, resposta.text
        espera_chamadas_a_receita(ana, 2 * CHAMADAS_POR_TENTATIVA)
        time.sleep(FOLGA_SEGUNDOS)
        esperando = consulta(abertura)
        assert esperando["status"] == "ANALYSIS"
        assert historico(esperando) == ["DRAFT", "PENDING_KYC", "ANALYSIS", "MANUAL_REVIEW", "PENDING_KYC", "ANALYSIS"]

        # confere: a nova tentativa vem em 1 minuto, e a Receita, de volta, deixa seguir
        assert espera_etapa(abertura, ETAPAS_FINAIS, ESPERA_PELO_WORKER_SEGUNDOS)["status"] == "ACTIVE"

    @pytest.mark.parametrize(
        "corpo, campo, regra",
        [
            pytest.param({"onboarding_keys": "abc"}, "onboarding_keys", "type", id="chaves que nao sao lista"),
            pytest.param({"onboarding_keys": ["nao-e-uuid"]}, "onboarding_keys.0", "format", id="item que nao e UUID"),
            pytest.param({"onboarding_keys": []}, "onboarding_keys", "minimum", id="lista vazia"),
            pytest.param({"reason_code": "BUREAU_UNAVAILABLE"}, "reason_code", "format", id="campo a mais"),
        ],
    )
    def test_retentativa_em_lote_confere_o_corpo(self, corpo, campo, regra):
        """F7-12 (decisão D29). onboarding_keys, se vier, é uma lista com pelo
        menos um UUID, e nenhum outro campo é aceito: 400 ONB000001, com o campo
        e a regra. A lista vazia é recusada, para não ser confundida com "todas"."""
        # age
        resposta = Onboarding.retenta_em_lote(corpo, credencial_de_compliance())

        # confere
        assert resposta.status_code == 400, resposta.text
        assert resposta.json()["code"] == "ONB000001"
        assert campos_e_regras(resposta.json()) == [(campo, regra)]

    def test_retentativa_exige_a_chave_idempotente(self):
        """F7-15 (decisão D7). Sem a X-Idempotency-Key: 400 ONB000011."""
        # prepara
        cabecalhos = cabecalhos_do_gateway()
        del cabecalhos["X-Idempotency-Key"]

        # age
        resposta = Onboarding.retenta_em_lote({}, credencial_de_compliance(), cabecalhos)

        # confere
        assert resposta.status_code == 400, resposta.text
        assert resposta.json()["code"] == "ONB000011"


@pytest.mark.global_state
@pytest.mark.usefixtures("circuito_da_receita_fechado")
class TestCircuitBreaker:
    @pytest.mark.slow
    def test_circuito_abre_depois_de_cinco_falhas(self):
        """F7-07. Cinco consultas seguidas à Receita sem resposta abrem o
        circuito por 30 s: nesse tempo, nenhuma abertura chama a Receita, nem a
        que teria resposta regular. Passados os 30 s, a próxima consulta é o
        teste: a Receita responde, o circuito fecha e a análise segue."""
        # prepara: cinco aberturas, uma depois da outra, com a Receita sem resposta
        for _ in range(5):
            dados = pessoa_fisica()
            abertura = prepara_abertura(dados)
            receita_fora_do_ar(dados, vezes=CHAMADAS_POR_TENTATIVA)
            manda_o_rg(abertura)
            espera_chamadas_a_receita(dados, CHAMADAS_POR_TENTATIVA)
        abriu_em = time.monotonic()

        # age: duas aberturas com a Receita regular, uma logo e outra 20 s depois
        regulares = []
        for espera_ate_segundos in (0, 20):
            time.sleep(max(0, abriu_em + espera_ate_segundos - time.monotonic()))
            dados = pessoa_fisica()
            abertura = prepara_abertura(dados)
            manda_o_rg(abertura)
            espera_etapa(abertura, {"ANALYSIS"} | ETAPAS_FINAIS)
            regulares.append((dados, abertura))
        time.sleep(FOLGA_SEGUNDOS)

        # confere: com o circuito aberto, nenhuma das duas chamou a Receita
        for dados, abertura in regulares:
            assert pedidos_a_receita(dados) == []
            assert consulta(abertura)["status"] == "ANALYSIS"

        # confere: passados os 30 s, o circuito fecha e as duas seguem, com uma chamada cada
        for dados, abertura in regulares:
            assert espera_etapa(abertura, ETAPAS_FINAIS, ESPERA_PELO_WORKER_SEGUNDOS)["status"] == "ACTIVE"
            assert len(pedidos_a_receita(dados)) == 1

    def test_resposta_fora_do_contrato_nao_abre_o_circuito(self):
        """F7-16 (decisão D15). Cinco respostas seguidas fora do contrato não
        abrem o circuito: o birô respondeu, só que a resposta não diz nada. A
        abertura seguinte, com a Receita regular, é analisada na hora."""
        # prepara: cinco aberturas, uma depois da outra, com a Receita respondendo 404
        for _ in range(5):
            dados = pessoa_fisica()
            abertura = prepara_abertura(dados)
            receita_com_404(dados)
            manda_o_rg(abertura)
            espera_chamadas_a_receita(dados, 1)

        # age
        ana = pessoa_fisica()
        abertura = prepara_abertura(ana)
        manda_o_rg(abertura)

        # confere
        assert espera_etapa(abertura, ETAPAS_FINAIS)["status"] == "ACTIVE"
        assert len(pedidos_a_receita(ana)) == 1


@pytest.mark.global_state
@pytest.mark.usefixtures("circuito_da_receita_fechado")
class TestRetentativaComBiroFora:
    pytestmark = so_com_relogio_simulado

    @pytest.mark.parametrize("biro", ["receita", "sancoes", "pep"])
    def test_retentativa_com_biro_ainda_fora_nao_muda_nada(self, biro):
        """F7-11. Antes de devolver as aberturas à fila, a API faz uma chamada
        de teste a cada birô obrigatório. Se algum ainda não responde: 503
        ONB005016, e nenhuma abertura muda."""
        # prepara
        _, abertura = abertura_parada_por_biro_fora()
        saude_do_biro(biro, 503)

        # age
        resposta = retenta(abertura)

        # confere
        assert resposta.status_code == 503, resposta.text
        assert resposta.json()["code"] == "ONB005016"
        depois = consulta(abertura)
        assert depois["status"] == "MANUAL_REVIEW"
        assert depois["reason_codes"] == ["BUREAU_UNAVAILABLE"]
        assert historico(depois) == ["DRAFT", "PENDING_KYC", "ANALYSIS", "MANUAL_REVIEW"]
