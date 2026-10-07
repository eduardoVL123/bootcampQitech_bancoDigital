import pytest
from tests.utils.onboarding_api import Onboarding, imagens, credencial_de_compliance

def envia(abertura: dict, arquivos: list):
    resposta = Onboarding.envia_rg(abertura["onboarding_key"], abertura["access_token"], arquivos)
    assert resposta.status_code in (200, 202)
    return resposta

def get_url(abertura: dict, side: str, credencial: dict = None):
    # If the credencial is a string (token), convert to header dict
    cabecalhos = None
    if isinstance(credencial, str):
        from tests.utils.onboarding_api import cabecalhos_com_credencial
        cabecalhos = cabecalhos_com_credencial(credencial)
    elif isinstance(credencial, dict):
        from tests.utils.onboarding_api import cabecalhos_com_credencial
        cabecalhos = cabecalhos_com_credencial()
        cabecalhos.update(credencial)
        
    return Onboarding.envia("GET", f"/internal/onboarding/{abertura['onboarding_key']}/document/{side}/url", cabecalhos=cabecalhos)

class TestGetDocumentUrl:
    def test_compliance_consegue_pegar_url_assinada_do_documento(self):
        """Compliance consegue pegar a URL pre-assinada de uma imagem enviada."""
        abertura = Onboarding.comeca_abertura()
        envia(abertura, imagens("front"))
        
        # O time de compliance tenta pegar a URL assinada para FRONT
        resposta = get_url(abertura, "front", credencial_de_compliance())
        
        assert resposta.status_code == 200
        corpo = resposta.json()
        assert "url" in corpo
        assert "rg-documentos" in corpo["url"]
        assert "AWSAccessKeyId" in corpo["url"]

    def test_rejeita_se_credencial_nao_for_de_compliance(self):
        """Se o próprio cliente (dono) ou outro tentar pegar a URL pela rota interna, deve ser recusado (404 oculto)."""
        abertura = Onboarding.comeca_abertura()
        envia(abertura, imagens("front"))
        
        # A API internal bloqueia quem nao tem a credencial certa
        # A própria lib de cliente mock (Onboarding) usa o access_token normal se não passar a credencial
        credencial = {"Authorization": f"Bearer {abertura['access_token']}"}
        resposta = get_url(abertura, "front", credencial)
        
        # Por causa do InternalTokenMiddleware ou de _is_compliance no controller, deve dar 404 (para esconder) ou 403.
        # Nosso controller joga OnboardingNotFound() -> 404 se não for compliance.
        assert resposta.status_code == 404
        assert resposta.json()["code"] == "ONB005006"

    def test_retorna_404_se_o_lado_do_documento_nao_existir(self):
        """Se pedir a URL do verso (back) mas a pessoa só mandou a frente, retorna 404 pro documento."""
        abertura = Onboarding.comeca_abertura()
        envia(abertura, imagens("front"))
        
        resposta = get_url(abertura, "back", credencial_de_compliance())
        
        assert resposta.status_code == 404
        assert resposta.json()["code"] == "ONB005016"
