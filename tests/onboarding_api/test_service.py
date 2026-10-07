"""F0: a onboarding-api sobe (docs/testes/onboarding-api.md)."""
from tests.utils.onboarding_api import TOKEN_DO_APLICATIVO, Onboarding


class TestServico:
    def test_pagina_inicial_diz_qual_servico_e(self):
        """F0-01. A raiz responde sem token e diz o nome do serviço."""
        # age
        resposta = Onboarding.pagina_inicial()

        # confere
        assert resposta.status_code == 200
        assert resposta.json()["service"] == "onboarding-api"

    def test_health_check_responde_sem_token(self):
        """F0-02. O Docker consulta o health check para saber se a API está de pé."""
        # age
        resposta = Onboarding.health_check()

        # confere
        assert resposta.status_code == 204

    def test_sem_token_do_aplicativo_nada_passa(self):
        """F0-03. Sem o INTERNAL-TOKEN, a API recusa antes de olhar o pedido (RFC 00)."""
        # age: pedido sem nenhum cabeçalho
        resposta = Onboarding.cadastra({}, cabecalhos={})

        # confere
        assert resposta.status_code == 403
        assert resposta.json()["code"] == "ONB000002"

    def test_rota_que_nao_existe_responde_404_com_corpo_de_erro(self):
        """F0-04. Todo erro tem os seis campos da RFC 05, e o request_id é o
        mesmo protocolo que volta no cabeçalho X-Request-ID."""
        # age
        resposta = Onboarding.envia("GET", "/nao_existe", {"INTERNAL-TOKEN": TOKEN_DO_APLICATIVO})

        # confere
        assert resposta.status_code == 404
        corpo = resposta.json()
        assert corpo["code"] == "ONB000404"
        assert set(corpo) == {"code", "title", "description", "translation", "request_id", "errors"}
        assert corpo["request_id"] == resposta.headers["X-Request-ID"]
        assert corpo["errors"] == []
