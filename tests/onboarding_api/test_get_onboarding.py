"""F3: GET /onboarding/{onboarding_key}, a consulta da abertura (docs/testes/onboarding-api.md)."""
from tests.utils.onboarding_api import Onboarding, credencial_de_compliance, nova_chave, pessoa_fisica, so_digitos


class TestConsultaAbertura:
    def test_dono_ve_a_propria_abertura_em_draft(self):
        """F3-01. O dono vê a etapa, o próximo passo, o prazo e o histórico."""
        # prepara
        abertura = Onboarding.comeca_abertura()

        # age
        resposta = Onboarding.consulta_abertura(abertura["onboarding_key"], abertura["access_token"])

        # confere
        assert resposta.status_code == 200
        corpo = resposta.json()
        assert corpo["onboarding_key"] == abertura["onboarding_key"]
        assert corpo["customer_key"] == abertura["customer_key"]
        assert corpo["status"] == "DRAFT"
        assert corpo["next_step"] == "SEND_DOCUMENT"
        assert corpo["expires_at"] == abertura["expires_at"]
        assert corpo["documents"] == []
        assert corpo["checks"] == []
        assert corpo["reason_codes"] == []
        assert corpo["risk_level"] is None
        assert corpo["account_key"] is None
        assert [evento["status"] for evento in corpo["status_events"]] == ["DRAFT"]

    def test_abertura_nao_mostra_dado_pessoal(self):
        """F3-02. Nem CPF, nem nome, nem renda, nem data de nascimento (LGPD)."""
        # prepara: uma cliente com nome e renda fáceis de reconhecer
        joana = pessoa_fisica(name="Joana Personalissima", declared_monthly_income_cents=987654321)
        abertura = Onboarding.comeca_abertura(joana)

        # age
        resposta = Onboarding.consulta_abertura(abertura["onboarding_key"], abertura["access_token"])

        # confere
        assert resposta.status_code == 200
        dados_pessoais = [
            joana["document_number"],
            so_digitos(joana["document_number"]),
            joana["name"],
            "987654321",
            joana["birth_date"],
        ]
        for dado in dados_pessoais:
            assert dado not in resposta.text

    def test_abertura_de_outra_pessoa_responde_404(self):
        """F3-03 (R8). De outra pessoa é igual a não existir."""
        # prepara: a Ana tem uma abertura, e o Bruno tem a credencial dele
        ana = Onboarding.comeca_abertura()
        bruno = Onboarding.comeca_abertura()

        # age: o Bruno tenta ver a abertura da Ana
        resposta = Onboarding.consulta_abertura(ana["onboarding_key"], bruno["access_token"])

        # confere
        assert resposta.status_code == 404
        assert resposta.json()["code"] == "ONB005006"

    def test_abertura_que_nao_existe_responde_igual_a_de_outra_pessoa(self):
        """F3-04. O corpo é o mesmo do F3-03, menos o protocolo: quem pede não
        descobre se a abertura existe."""
        # prepara: a resposta de "é de outra pessoa"
        bruno = Onboarding.comeca_abertura()
        ana = Onboarding.comeca_abertura()
        de_outra_pessoa = Onboarding.consulta_abertura(ana["onboarding_key"], bruno["access_token"]).json()

        # age: uma chave que ninguém criou
        resposta = Onboarding.consulta_abertura(nova_chave(), bruno["access_token"])

        # confere
        assert resposta.status_code == 404
        corpo = resposta.json()
        assert corpo["code"] == "ONB005006"
        corpo.pop("request_id")
        de_outra_pessoa.pop("request_id")
        assert corpo == de_outra_pessoa

    def test_compliance_ve_qualquer_abertura(self):
        """F3-05. O analista de compliance vê a abertura de qualquer pessoa."""
        # prepara
        abertura = Onboarding.comeca_abertura()

        # age
        resposta = Onboarding.consulta_abertura(abertura["onboarding_key"], credencial_de_compliance())

        # confere
        assert resposta.status_code == 200
        assert resposta.json()["onboarding_key"] == abertura["onboarding_key"]
