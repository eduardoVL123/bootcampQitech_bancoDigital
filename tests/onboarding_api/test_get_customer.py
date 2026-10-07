"""F3: GET /customer/{customer_key}, a consulta do cadastro (docs/testes/onboarding-api.md)."""
from tests.utils.onboarding_api import Onboarding, credencial_de_compliance, nova_chave, pessoa_fisica, pessoa_juridica


class TestConsultaCliente:
    def test_cliente_ve_o_proprio_cadastro(self):
        """F3-06. O cadastro volta sem credencial, renda nem ocupação."""
        # prepara
        ana = pessoa_fisica()
        abertura = Onboarding.comeca_abertura(ana)

        # age
        resposta = Onboarding.consulta_cliente(abertura["customer_key"], abertura["access_token"])

        # confere
        assert resposta.status_code == 200
        corpo = resposta.json()
        assert set(corpo) == {"customer_key", "type", "name", "document_number", "birth_date", "created_at"}
        assert corpo["customer_key"] == abertura["customer_key"]
        assert corpo["type"] == "PF"
        assert corpo["name"] == ana["name"]
        assert corpo["document_number"] == ana["document_number"]
        assert corpo["birth_date"] == ana["birth_date"]

    def test_empresa_mostra_a_data_de_abertura(self):
        """F3-07. Na PJ vem a data de abertura, e não a de nascimento."""
        # prepara
        padaria = pessoa_juridica()
        abertura = Onboarding.comeca_abertura(padaria)

        # age
        resposta = Onboarding.consulta_cliente(abertura["customer_key"], abertura["access_token"])

        # confere
        corpo = resposta.json()
        assert set(corpo) == {"customer_key", "type", "name", "document_number", "opening_date", "created_at"}
        assert corpo["opening_date"] == padaria["opening_date"]

    def test_cadastro_de_outra_pessoa_responde_404(self):
        """F3-08 (R8). De outra pessoa é igual a não existir."""
        # prepara
        ana = Onboarding.comeca_abertura()
        bruno = Onboarding.comeca_abertura()

        # age: o Bruno tenta ver o cadastro da Ana
        resposta = Onboarding.consulta_cliente(ana["customer_key"], bruno["access_token"])

        # confere
        assert resposta.status_code == 404
        assert resposta.json()["code"] == "ONB005007"

    def test_cadastro_que_nao_existe_responde_404(self):
        """F3-09"""
        # prepara
        bruno = Onboarding.comeca_abertura()

        # age: uma chave que ninguém criou
        resposta = Onboarding.consulta_cliente(nova_chave(), bruno["access_token"])

        # confere
        assert resposta.status_code == 404
        assert resposta.json()["code"] == "ONB005007"

    def test_compliance_ve_qualquer_cadastro(self):
        """F3-10"""
        # prepara
        abertura = Onboarding.comeca_abertura()

        # age
        resposta = Onboarding.consulta_cliente(abertura["customer_key"], credencial_de_compliance())

        # confere
        assert resposta.status_code == 200
        assert resposta.json()["customer_key"] == abertura["customer_key"]
