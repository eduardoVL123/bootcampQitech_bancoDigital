"""F3: a matriz de credencial (docs/testes/onboarding-api.md).

Cada teste roda uma vez para cada rota que exige credencial. Cada fatia que
cria uma rota nova com credencial acrescenta a rota em ROTAS_COM_CREDENCIAL.
O F3-16 (403 por escopo) entra com a primeira rota só de compliance, na F8.
"""
import pytest

from tests.utils.onboarding_api import (
    TOKEN_DO_APLICATIVO,
    Onboarding,
    cabecalhos_com_credencial,
    cabecalhos_do_gateway,
    credencial_com_outro_segredo,
    credencial_sem_assinatura,
    credencial_vencida,
    imagens,
)


# Cada rota recebe a abertura do teste e os cabeçalhos da credencial, e
# devolve a resposta. O resto do pedido vai certo: só a credencial está errada.

def le_a_abertura(abertura: dict, cabecalhos: dict):
    return Onboarding.envia("GET", f"/onboarding/{abertura['onboarding_key']}", cabecalhos)


def le_o_cliente(abertura: dict, cabecalhos: dict):
    return Onboarding.envia("GET", f"/customer/{abertura['customer_key']}", cabecalhos)


def envia_o_rg(abertura: dict, cabecalhos: dict):
    """O envio do RG leva também o que o gateway manda e um RG válido."""
    cabecalhos = {**cabecalhos_do_gateway(), **cabecalhos}
    caminho = f"/onboarding/{abertura['onboarding_key']}/document"
    return Onboarding.envia("PUT", caminho, cabecalhos, files=imagens("front", "back"))


ROTAS_COM_CREDENCIAL = [
    pytest.param(le_a_abertura, id="GET /onboarding/{key}"),
    pytest.param(le_o_cliente, id="GET /customer/{key}"),
    pytest.param(envia_o_rg, id="PUT /onboarding/{key}/document"),
]


@pytest.mark.parametrize("pede_a_rota", ROTAS_COM_CREDENCIAL)
class TestCredencial:
    def test_sem_credencial_responde_401(self, pede_a_rota):
        """F3-11. Sem o cabeçalho Authorization: 401, e o WWW-Authenticate diz
        que a rota pede uma credencial Bearer (padrão OAuth)."""
        # prepara
        abertura = Onboarding.comeca_abertura()

        # age: só o token do aplicativo, sem credencial
        resposta = pede_a_rota(abertura, cabecalhos_com_credencial(None))

        # confere
        assert resposta.status_code == 401
        assert resposta.json()["code"] == "ONB000003"
        assert resposta.headers["WWW-Authenticate"] == 'Bearer realm="banco"'

    def test_credencial_assinada_com_outro_segredo_responde_401(self, pede_a_rota):
        """F3-12. Credencial falsificada: a assinatura não bate com o segredo do banco."""
        # prepara
        abertura = Onboarding.comeca_abertura()
        falsificada = credencial_com_outro_segredo(abertura["customer_key"])

        # age
        resposta = pede_a_rota(abertura, cabecalhos_com_credencial(falsificada))

        # confere
        assert resposta.status_code == 401
        assert resposta.json()["code"] == "ONB000006"
        assert 'error="invalid_token"' in resposta.headers["WWW-Authenticate"]

    @pytest.mark.parametrize(
        "authorization",
        [
            pytest.param("Bearer abc", id="token que nao e JWT"),
            pytest.param("Basic abc", id="outro tipo de credencial"),
            pytest.param("Bearer", id="Bearer sem token"),
        ],
    )
    def test_credencial_mal_formada_responde_401(self, pede_a_rota, authorization):
        """F3-13. O cabeçalho Authorization existe, mas não traz um JWT Bearer."""
        # prepara
        abertura = Onboarding.comeca_abertura()
        cabecalhos = {"INTERNAL-TOKEN": TOKEN_DO_APLICATIVO, "Authorization": authorization}

        # age
        resposta = pede_a_rota(abertura, cabecalhos)

        # confere
        assert resposta.status_code == 401
        assert resposta.json()["code"] == "ONB000006"
        assert 'error="invalid_token"' in resposta.headers["WWW-Authenticate"]

    def test_credencial_sem_assinatura_responde_401(self, pede_a_rota):
        """F3-14. JWT com alg none, sem assinatura: o ataque clássico é recusado."""
        # prepara
        abertura = Onboarding.comeca_abertura()
        sem_assinatura = credencial_sem_assinatura(abertura["customer_key"])

        # age
        resposta = pede_a_rota(abertura, cabecalhos_com_credencial(sem_assinatura))

        # confere
        assert resposta.status_code == 401
        assert resposta.json()["code"] == "ONB000006"

    def test_credencial_vencida_responde_401(self, pede_a_rota):
        """F3-15. A credencial vale 1 hora. Vencida: 401, dizendo que expirou."""
        # prepara: uma credencial emitida há mais de 1 hora
        abertura = Onboarding.comeca_abertura()
        vencida = credencial_vencida(abertura["customer_key"])

        # age
        resposta = pede_a_rota(abertura, cabecalhos_com_credencial(vencida))

        # confere
        assert resposta.status_code == 401
        assert resposta.json()["code"] == "ONB000007"
        assert 'error="invalid_token"' in resposta.headers["WWW-Authenticate"]
        assert 'error_description="token expirado"' in resposta.headers["WWW-Authenticate"]
