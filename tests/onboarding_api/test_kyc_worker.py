"""F6: o worker analisa o KYC, aplica o PLD e abre a conta (docs/testes/onboarding-api.md).

Com o RG completo, a abertura entra na fila. O onboarding-worker consulta a
Receita, as sanções e o PEP, aplica as regras de PLD e, com tudo certo,
pede a conta à account-api. Os quatro ficam no Mockserver: o teste programa
cada um para o documento dele, manda o RG e espera a etapa.
"""
import time

import pytest

from tests.utils.mockserver import (
    ROTA_DA_RECEITA,
    ROTA_DAS_SANCOES,
    ROTA_DO_PEP,
    TOKEN_DE_SERVICO,
    account_api_responde,
    biros_regulares,
    cabecalho,
    corpo,
    pedidos_a_account_api,
    pedidos_aos_biros,
    pep_responde,
    receita_responde,
    sancoes_respondem,
)
from tests.utils.onboarding_api import (
    ESPERA_PELO_WORKER_SEGUNDOS,
    Onboarding,
    aberta_ha_dias,
    ao_mesmo_tempo,
    espera_ate,
    espera_etapa,
    imagens,
    nascido_para_completar_hoje,
    pessoa_fisica,
    pessoa_juridica,
)

# Onde a análise termina. APPROVED não está aqui: é a passagem para ACTIVE.
ETAPAS_FINAIS = {"ACTIVE", "REJECTED", "MANUAL_REVIEW"}


def manda_o_rg(abertura: dict) -> None:
    resposta = Onboarding.envia_rg(abertura["onboarding_key"], abertura["access_token"], imagens("front", "back"))
    assert resposta.status_code == 202, resposta.text


def consulta(abertura: dict) -> dict:
    resposta = Onboarding.consulta_abertura(abertura["onboarding_key"], abertura["access_token"])
    assert resposta.status_code == 200, resposta.text
    return resposta.json()


def abre_e_analisa(dados: dict, programa_os_biros=biros_regulares) -> tuple:
    """Cadastra, programa os birôs e a account-api, manda o RG e espera o fim
    da análise. Devolve a abertura, o GET do fim e a account_key do mock."""
    abertura = Onboarding.comeca_abertura(dados)
    programa_os_biros(dados)
    account_key = account_api_responde(abertura, dados)
    manda_o_rg(abertura)
    return abertura, espera_etapa(abertura, ETAPAS_FINAIS), account_key


def receita_diz(situacao: str = None, **trocas):
    """Programa a Receita com a situação ou os dados trocados, e as listas sem nada."""
    def programa(dados: dict) -> None:
        receita_responde(dados, situacao, **trocas)
        sancoes_respondem(dados)
        pep_responde(dados)
    return programa


def listas_dizem(match: bool = False, pep: bool = False):
    """Programa a Receita regular e as listas com o que o teste pedir."""
    def programa(dados: dict) -> None:
        receita_responde(dados)
        sancoes_respondem(dados, match)
        pep_responde(dados, pep)
    return programa


class TestCaminhoFeliz:
    def test_pessoa_regular_e_aprovada_e_ganha_conta(self):
        """F6-01. Tudo regular: o worker aprova, a account-api abre a conta e a
        abertura fica ACTIVE, com as quatro verificações aprovadas."""
        # prepara
        ana = pessoa_fisica()

        # age
        _, final, account_key = abre_e_analisa(ana)

        # confere
        assert final["status"] == "ACTIVE"
        assert final["next_step"] == "NONE"
        assert final["account_key"] == account_key
        assert final["risk_level"] == "LOW"
        assert final["reason_codes"] == []
        verificacoes = [(check["check_type"], check["result"]) for check in final["checks"]]
        assert verificacoes == [("RECEITA", "PASS"), ("SANCTIONS", "PASS"), ("PEP", "PASS"), ("PLD", "PASS")]
        historico = [evento["status"] for evento in final["status_events"]]
        assert historico == ["DRAFT", "PENDING_KYC", "ANALYSIS", "APPROVED", "ACTIVE"]

    def test_biros_sao_consultados_em_ordem(self):
        """F6-02. Primeiro a Receita, depois as sanções, depois o PEP, uma vez cada."""
        # prepara
        ana = pessoa_fisica()

        # age
        abre_e_analisa(ana)

        # confere
        assert pedidos_aos_biros(ana) == [ROTA_DA_RECEITA, ROTA_DAS_SANCOES, ROTA_DO_PEP]

    def test_conta_e_pedida_com_a_chave_da_abertura(self):
        """F6-03 (RFC 02, decisão D2). Uma chamada só à account-api, com a
        customer_key e o tipo, o SERVICE-TOKEN e a onboarding_key como chave idempotente."""
        # prepara
        ana = pessoa_fisica()

        # age
        abertura, _, _ = abre_e_analisa(ana)

        # confere
        pedidos = pedidos_a_account_api(abertura)
        assert len(pedidos) == 1
        assert corpo(pedidos[0]) == {"customer_key": abertura["customer_key"], "type": "PF"}
        assert cabecalho(pedidos[0], "SERVICE-TOKEN") == TOKEN_DE_SERVICO
        assert cabecalho(pedidos[0], "X-Idempotency-Key") == abertura["onboarding_key"]

    def test_empresa_regular_e_aprovada(self):
        """F6-04. Uma empresa ATIVA na Receita também ganha conta."""
        # prepara
        padaria = pessoa_juridica()

        # age
        _, final, _ = abre_e_analisa(padaria)

        # confere
        assert final["status"] == "ACTIVE"


class TestReceita:
    @pytest.mark.parametrize("situacao", ["SUSPENSA", "CANCELADA", "TITULAR_FALECIDO", "NULA", "PENDENTE_REGULARIZACAO"])
    def test_cpf_irregular_e_recusado(self, situacao):
        """F6-05. CPF fora da situação regular: recusado, com o motivo da Receita,
        e não há mais nada a fazer nesta abertura (decisão D26)."""
        # prepara
        ana = pessoa_fisica()

        # age
        _, final, _ = abre_e_analisa(ana, receita_diz(situacao))

        # confere
        assert final["status"] == "REJECTED"
        assert final["next_step"] == "NONE"
        assert final["reason_codes"] == [f"RECEITA_{situacao}"]

    @pytest.mark.parametrize("situacao", ["SUSPENSA", "INAPTA", "BAIXADA", "NULA"])
    def test_cnpj_irregular_e_recusado(self, situacao):
        """F6-06. CNPJ fora da situação ativa: recusado, com o motivo da Receita."""
        # prepara
        padaria = pessoa_juridica()

        # age
        _, final, _ = abre_e_analisa(padaria, receita_diz(situacao))

        # confere
        assert final["status"] == "REJECTED"
        assert final["reason_codes"] == [f"RECEITA_CNPJ_{situacao}"]

    @pytest.mark.parametrize(
        "cria_os_dados",
        [pytest.param(pessoa_fisica, id="CPF"), pytest.param(pessoa_juridica, id="CNPJ")],
    )
    def test_documento_desconhecido_e_recusado(self, cria_os_dados):
        """F6-07. A Receita não conhece o documento: recusado, com o mesmo
        motivo para CPF e CNPJ."""
        # prepara
        dados = cria_os_dados()

        # age
        _, final, _ = abre_e_analisa(dados, receita_diz("NAO_ENCONTRADO"))

        # confere
        assert final["status"] == "REJECTED"
        assert final["reason_codes"] == ["RECEITA_NAO_ENCONTRADO"]

    @pytest.mark.parametrize("situacao", ["CANCELADA", "NAO_ENCONTRADO"])
    def test_recusa_da_receita_para_antes_das_listas(self, situacao):
        """F6-08. Uma recusa da Receita encerra a análise: as listas e a
        account-api nunca são chamadas, mesmo programadas para responder."""
        # prepara
        ana = pessoa_fisica()

        # age
        abertura, final, _ = abre_e_analisa(ana, receita_diz(situacao))

        # confere
        assert final["status"] == "REJECTED"
        assert pedidos_aos_biros(ana) == [ROTA_DA_RECEITA]
        assert pedidos_a_account_api(abertura) == []

    @pytest.mark.parametrize(
        "trocas",
        [
            pytest.param({"nome": "Maria Divergente"}, id="outro nome"),
            pytest.param({"data": "1985-01-01"}, id="outra data"),
        ],
    )
    def test_dados_divergentes_vao_para_revisao(self, trocas):
        """F6-09. Nome ou data diferentes dos da Receita: uma pessoa decide."""
        # prepara
        ana = pessoa_fisica()

        # age
        _, final, _ = abre_e_analisa(ana, receita_diz(**trocas))

        # confere
        assert final["status"] == "MANUAL_REVIEW"
        assert final["reason_codes"] == ["RECEITA_DADOS_DIVERGENTES"]

    def test_comparacao_do_nome_ignora_maiuscula_e_acento(self):
        """F6-10 (decisão D13). JOSÉ DA SILVA, com espaços sobrando, é o mesmo Jose da Silva."""
        # prepara
        jose = pessoa_fisica(name="Jose da Silva")

        # age
        _, final, _ = abre_e_analisa(jose, receita_diz(nome="  JOSÉ   DA SILVA "))

        # confere
        assert final["status"] == "ACTIVE"


class TestListas:
    def test_pessoa_sancionada_e_recusada(self):
        """F6-11. Nome ou documento numa lista de sanções: recusado, e a conta nunca é pedida."""
        # prepara
        ana = pessoa_fisica()

        # age
        abertura, final, _ = abre_e_analisa(ana, listas_dizem(match=True))

        # confere
        assert final["status"] == "REJECTED"
        assert final["reason_codes"] == ["SANCTIONS_MATCH"]
        assert pedidos_a_account_api(abertura) == []

    def test_pep_na_lista_vai_para_revisao(self):
        """F6-12. Pessoa exposta politicamente pela lista: risco alto, uma pessoa
        decide, e o cliente espera (decisão D26)."""
        # prepara
        ana = pessoa_fisica()

        # age
        _, final, _ = abre_e_analisa(ana, listas_dizem(pep=True))

        # confere
        assert final["status"] == "MANUAL_REVIEW"
        assert final["next_step"] == "WAIT"
        assert final["reason_codes"] == ["PEP_MATCH"]
        assert final["risk_level"] == "HIGH"

    def test_pep_declarado_vai_para_revisao(self):
        """F6-13. Quem se declara PEP também vai para revisão, mesmo fora da lista."""
        # prepara
        ana = pessoa_fisica(pep_self_declared=True)

        # age
        _, final, _ = abre_e_analisa(ana)

        # confere
        assert final["status"] == "MANUAL_REVIEW"
        assert final["reason_codes"] == ["PEP_SELF_DECLARED"]
        assert final["risk_level"] == "HIGH"


class TestPld:
    def test_pf_jovem_com_renda_alta_vai_para_revisao(self):
        """F6-14. Menos de 21 anos e renda acima de R$ 30.000: risco médio, revisão."""
        # prepara
        joao = pessoa_fisica(birth_date=nascido_para_completar_hoje(20), declared_monthly_income_cents=3000001)

        # age
        _, final, _ = abre_e_analisa(joao)

        # confere
        assert final["status"] == "MANUAL_REVIEW"
        assert final["reason_codes"] == ["INCOME_PROFILE"]
        assert final["risk_level"] == "MEDIUM"

    def test_pf_jovem_no_limite_da_renda_e_aprovada(self):
        """F6-15. A borda da renda: R$ 30.000 cravados passam."""
        # prepara
        joao = pessoa_fisica(birth_date=nascido_para_completar_hoje(20), declared_monthly_income_cents=3000000)

        # age
        _, final, _ = abre_e_analisa(joao)

        # confere
        assert final["status"] == "ACTIVE"

    def test_pf_que_completa_21_hoje_com_renda_alta_e_aprovada(self):
        """F6-16. A borda da idade: quem completa 21 anos hoje já não cai na regra."""
        # prepara
        joao = pessoa_fisica(birth_date=nascido_para_completar_hoje(21), declared_monthly_income_cents=3000001)

        # age
        _, final, _ = abre_e_analisa(joao)

        # confere
        assert final["status"] == "ACTIVE"

    @pytest.mark.parametrize(
        "renda, etapa, motivos",
        [
            pytest.param(50000001, "MANUAL_REVIEW", ["INCOME_PROFILE"], id="R$ 500.000,01 vai para revisao"),
            pytest.param(50000000, "ACTIVE", [], id="R$ 500.000 cravados passam"),
        ],
    )
    def test_renda_acima_de_500_mil_vai_para_revisao(self, renda, etapa, motivos):
        """F6-17. Renda acima de R$ 500.000 por mês está fora do padrão, em qualquer idade."""
        # prepara
        ana = pessoa_fisica(declared_monthly_income_cents=renda)

        # age
        _, final, _ = abre_e_analisa(ana)

        # confere
        assert final["status"] == etapa
        assert final["reason_codes"] == motivos

    @pytest.mark.parametrize(
        "dias, faturamento, etapa",
        [
            pytest.param(179, 30000001, "MANUAL_REVIEW", id="179 dias e R$ 300.000,01"),
            pytest.param(180, 30000001, "ACTIVE", id="180 dias e R$ 300.000,01"),
            pytest.param(179, 30000000, "ACTIVE", id="179 dias e R$ 300.000"),
        ],
    )
    def test_empresa_nova_com_faturamento_alto_vai_para_revisao(self, dias, faturamento, etapa):
        """F6-18. Empresa aberta há menos de 180 dias com faturamento acima de
        R$ 300.000 vai para revisão. As duas bordas passam."""
        # prepara
        padaria = pessoa_juridica(opening_date=aberta_ha_dias(dias), declared_monthly_income_cents=faturamento)

        # age
        _, final, _ = abre_e_analisa(padaria)

        # confere
        assert final["status"] == etapa

    def test_duas_regras_dao_risco_alto(self):
        """F6-19. Jovem com renda acima de R$ 500.000: as duas regras de renda
        disparam, o risco é alto, e o motivo aparece uma vez só."""
        # prepara
        joao = pessoa_fisica(birth_date=nascido_para_completar_hoje(20), declared_monthly_income_cents=50000001)

        # age
        _, final, _ = abre_e_analisa(joao)

        # confere
        assert final["status"] == "MANUAL_REVIEW"
        assert final["risk_level"] == "HIGH"
        assert final["reason_codes"] == ["INCOME_PROFILE"]

    def test_pep_e_renda_listam_os_dois_motivos(self):
        """F6-20. PEP declarado e renda fora do padrão: os dois motivos aparecem."""
        # prepara
        ana = pessoa_fisica(pep_self_declared=True, declared_monthly_income_cents=50000001)

        # age
        _, final, _ = abre_e_analisa(ana)

        # confere
        assert final["status"] == "MANUAL_REVIEW"
        assert final["risk_level"] == "HIGH"
        assert sorted(final["reason_codes"]) == ["INCOME_PROFILE", "PEP_SELF_DECLARED"]

    def test_verificacoes_nunca_mostram_os_dados_consultados(self):
        """F6-21 (LGPD). De cada verificação sai só o tipo, o resultado e o
        motivo: nada do que o birô respondeu, nem o protocolo dele."""
        # prepara
        ana = pessoa_fisica(pep_self_declared=True)

        # age
        _, final, _ = abre_e_analisa(ana)

        # confere
        assert len(final["checks"]) == 4
        for check in final["checks"]:
            assert set(check) == {"check_type", "result", "reason_code"}


class TestContaNaAccountApi:
    @pytest.mark.slow
    def test_account_api_fora_mantem_aprovada_e_tenta_de_novo(self):
        """F6-22. A account-api falhou: a abertura espera em APPROVED e o worker
        tenta de novo em 1 minuto, com a mesma chave idempotente."""
        # prepara: a primeira chamada falha (503), as seguintes abrem a conta
        ana = pessoa_fisica()
        abertura = Onboarding.comeca_abertura(ana)
        biros_regulares(ana)
        account_api_responde(abertura, ana, status=503, vezes=1, prioridade=10)
        account_key = account_api_responde(abertura, ana)

        # age
        manda_o_rg(abertura)

        # confere: depois da falha, a abertura espera aprovada
        espera_ate(lambda: len(pedidos_a_account_api(abertura)), lambda chamadas: chamadas >= 1, 20)
        aprovada = consulta(abertura)
        assert aprovada["status"] == "APPROVED"
        assert aprovada["next_step"] == "WAIT"

        # confere: o worker não insiste na hora; segundos depois, ainda uma chamada só
        time.sleep(3)
        assert consulta(abertura)["status"] == "APPROVED"
        assert len(pedidos_a_account_api(abertura)) == 1

        # confere: a nova tentativa abre a conta
        final = espera_etapa(abertura, {"ACTIVE"}, ESPERA_PELO_WORKER_SEGUNDOS)
        assert final["account_key"] == account_key
        pedidos = pedidos_a_account_api(abertura)
        assert len(pedidos) == 2
        assert {cabecalho(pedido, "X-Idempotency-Key") for pedido in pedidos} == {abertura["onboarding_key"]}

    def test_conta_que_ja_existe_e_reaproveitada(self):
        """F6-23. A account-api responde 200 com a conta que o cliente já tinha:
        a abertura fica ACTIVE com essa conta (uma conta por cliente)."""
        # prepara
        ana = pessoa_fisica()
        abertura = Onboarding.comeca_abertura(ana)
        biros_regulares(ana)
        conta_existente = account_api_responde(abertura, ana, status=200)

        # age
        manda_o_rg(abertura)

        # confere
        final = espera_etapa(abertura, ETAPAS_FINAIS)
        assert final["status"] == "ACTIVE"
        assert final["account_key"] == conta_existente

    @pytest.mark.concurrency
    def test_cada_abertura_e_analisada_uma_vez(self):
        """F6-24. Dez RG completos chegando juntos, com duas réplicas do worker:
        cada abertura é analisada uma vez só (FOR UPDATE SKIP LOCKED)."""
        # prepara
        pessoas = [pessoa_fisica() for _ in range(10)]
        aberturas = []
        for dados in pessoas:
            abertura = Onboarding.comeca_abertura(dados)
            biros_regulares(dados)
            account_api_responde(abertura, dados)
            aberturas.append(abertura)

        # age
        envios = ao_mesmo_tempo([
            lambda abertura=abertura: Onboarding.envia_rg(abertura["onboarding_key"], abertura["access_token"], imagens("front", "back"))
            for abertura in aberturas
        ])

        # confere
        assert [envio.status_code for envio in envios] == [202] * 10
        for dados, abertura in zip(pessoas, aberturas):
            assert espera_etapa(abertura, ETAPAS_FINAIS)["status"] == "ACTIVE"
            assert pedidos_aos_biros(dados).count(ROTA_DA_RECEITA) == 1
            assert len(pedidos_a_account_api(abertura)) == 1
