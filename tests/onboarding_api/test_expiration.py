"""F5: o prazo de 20 minutos (docs/testes/onboarding-api.md).

Enquanto a abertura está em DRAFT, a pessoa tem 20 minutos para mandar o
RG. Depois disso, todo pedido recebe 410, e o worker apaga as fotos e os
dados pessoais. Com o RG completo, o prazo deixa de contar.

O teste não espera 20 minutos de verdade: com o relógio simulado (decisão
D16), o POST acontece "no passado", e o relógio de verdade faz o resto.
"""
import pytest

from tests.utils.onboarding_api import (
    ESPERA_PELO_WORKER_SEGUNDOS,
    RELOGIO_SIMULADO_LIGADO,
    Onboarding,
    cabecalhos_do_gateway,
    credencial_de_compliance,
    espera_ate,
    imagens,
    no_passado,
    pessoa_fisica,
)

pytestmark = [
    pytest.mark.simulated_clock,
    pytest.mark.skipif(not RELOGIO_SIMULADO_LIGADO, reason="precisa da API e do pytest com SIMULATED_CLOCK_ENABLED=true"),
]


def abertura_criada_ha(minutos: float, dados: dict = None, chave: str = None) -> dict:
    """Uma abertura cujo POST aconteceu `minutos` atrás."""
    cabecalhos = cabecalhos_do_gateway(chave=chave, extras=no_passado(minutos))
    return Onboarding.comeca_abertura(dados, cabecalhos)


def envia(abertura: dict, arquivos: list, cabecalhos: dict = None):
    """O dono da abertura manda as imagens do RG."""
    return Onboarding.envia_rg(abertura["onboarding_key"], abertura["access_token"], arquivos, cabecalhos)


def envia_no_passado(abertura: dict, arquivos: list, minutos: float):
    """O envio do RG acontecendo `minutos` atrás."""
    return envia(abertura, arquivos, cabecalhos_do_gateway(extras=no_passado(minutos)))


def espera_o_worker_apagar_o_cadastro(abertura: dict):
    """O worker passa a cada minuto. Quando ele apaga o cadastro, compliance
    deixa de achar o cliente (o mesmo 404 de um cliente que não existe)."""
    return espera_ate(
        lambda: Onboarding.consulta_cliente(abertura["customer_key"], credencial_de_compliance()),
        lambda resposta: resposta.status_code == 404,
        ESPERA_PELO_WORKER_SEGUNDOS,
    )


class TestPrazo:
    def test_envio_depois_do_prazo_responde_410(self):
        """F5-01. Passaram 21 minutos em DRAFT: o envio do RG é recusado com 410."""
        # prepara
        abertura = abertura_criada_ha(21)

        # age
        resposta = envia(abertura, imagens("front", "back"))

        # confere
        assert resposta.status_code == 410
        assert resposta.json()["code"] == "ONB005010"

    @pytest.mark.parametrize(
        "credencial_de_quem_le",
        [
            pytest.param(lambda abertura: abertura["access_token"], id="dono"),
            pytest.param(lambda abertura: credencial_de_compliance(), id="compliance"),
        ],
    )
    def test_consulta_depois_do_prazo_responde_410(self, credencial_de_quem_le):
        """F5-02. Depois do prazo, a consulta também responde 410, para o dono e para compliance."""
        # prepara
        abertura = abertura_criada_ha(21)

        # age
        resposta = Onboarding.consulta_abertura(abertura["onboarding_key"], credencial_de_quem_le(abertura))

        # confere
        assert resposta.status_code == 410
        assert resposta.json()["code"] == "ONB005010"

    def test_envio_pouco_antes_do_prazo_e_aceito(self):
        """F5-03. A borda do prazo: aos 19 minutos o RG ainda é aceito."""
        # prepara
        abertura = abertura_criada_ha(19)

        # age
        resposta = envia(abertura, imagens("front", "back"))

        # confere
        assert resposta.status_code == 202
        assert resposta.json()["status"] == "PENDING_KYC"

    def test_prazo_para_de_contar_depois_do_rg_completo(self):
        """F5-06. O RG ficou completo antes de vencer: daí em diante o tempo é
        do banco, e não da pessoa. Passados 25 minutos, a abertura não vence."""
        # prepara: o POST há 25 minutos e o RG completo há 10, antes de vencer
        abertura = abertura_criada_ha(25)
        envio = envia_no_passado(abertura, imagens("front", "back"), 10)
        assert envio.status_code == 202, envio.text

        # age
        resposta = Onboarding.consulta_abertura(abertura["onboarding_key"], abertura["access_token"])

        # confere
        assert resposta.status_code == 200
        assert resposta.json()["status"] != "EXPIRED"

    def test_repetir_o_cadastro_de_abertura_vencida_responde_410(self):
        """F5-07 (decisão D9). Repetir o POST de uma abertura vencida, com a
        mesma chave, não devolve a abertura nem uma credencial nova: 410."""
        # prepara
        ana = pessoa_fisica()
        chave = cabecalhos_do_gateway()["X-Idempotency-Key"]
        abertura_criada_ha(21, ana, chave)

        # age: o mesmo pedido, com a mesma chave, agora
        resposta = Onboarding.cadastra(ana, cabecalhos_do_gateway(chave=chave))

        # confere
        assert resposta.status_code == 410
        assert resposta.json()["code"] == "ONB005010"
        assert "access_token" not in resposta.text

    def test_abertura_vencida_de_outra_pessoa_continua_404(self):
        """F5-08 (R8). Vencida ou não, a abertura de outra pessoa responde 404:
        quem não é o dono não descobre que ela existiu."""
        # prepara: a abertura da Ana venceu, e o Bruno tem a credencial dele
        ana = abertura_criada_ha(21)
        bruno = Onboarding.comeca_abertura()

        # age
        consulta = Onboarding.consulta_abertura(ana["onboarding_key"], bruno["access_token"])
        envio = Onboarding.envia_rg(ana["onboarding_key"], bruno["access_token"], imagens("front", "back"))

        # confere
        assert consulta.status_code == 404
        assert consulta.json()["code"] == "ONB005006"
        assert envio.status_code == 404
        assert envio.json()["code"] == "ONB005006"


@pytest.mark.slow
class TestWorkerVenceAbertura:
    def test_worker_apaga_os_dados_da_abertura_vencida(self):
        """F5-04 (LGPD). O worker apaga o cadastro e as fotos de quem não
        terminou a tempo. Depois disso, o dono ainda recebe 410 (decisão D24),
        e não 404: a abertura guarda a customer_key, que não é dado pessoal."""
        # prepara: o POST há 21 minutos e a frente enviada antes de vencer
        abertura = abertura_criada_ha(21)
        frente = envia_no_passado(abertura, imagens("front"), 20.5)
        assert frente.status_code == 200, frente.text

        # age: espera a passada do worker
        espera_o_worker_apagar_o_cadastro(abertura)

        # confere
        consulta = Onboarding.consulta_abertura(abertura["onboarding_key"], abertura["access_token"])
        assert consulta.status_code == 410
        assert consulta.json()["code"] == "ONB005010"
        envio = envia(abertura, imagens("back"))
        assert envio.status_code == 410
        assert envio.json()["code"] == "ONB005010"

    def test_worker_nao_vence_abertura_com_rg_completo(self):
        """F5-09. O worker também respeita o RG completo: passada a hora, ele
        vence só quem ficou em DRAFT.

        Uma segunda abertura, a sentinela, vence 10 s depois da preparação.
        Quando o worker a apaga, é certo que a passada começou depois da
        preparação, e que passou antes pela abertura completa, que venceu
        primeiro (o worker anda das mais antigas para as mais novas)."""
        # prepara: a abertura com o RG completo antes de vencer, e depois a sentinela
        completa = abertura_criada_ha(25)
        envio = envia_no_passado(completa, imagens("front", "back"), 10)
        assert envio.status_code == 202, envio.text
        sentinela = abertura_criada_ha(20 - 10 / 60)

        # age: espera uma passada do worker
        espera_o_worker_apagar_o_cadastro(sentinela)

        # confere: a abertura completa não venceu, e o cadastro continua lá
        consulta = Onboarding.consulta_abertura(completa["onboarding_key"], completa["access_token"])
        assert consulta.status_code == 200
        assert consulta.json()["status"] != "EXPIRED"
        cadastro = Onboarding.consulta_cliente(completa["customer_key"], credencial_de_compliance())
        assert cadastro.status_code == 200

    def test_documento_fica_livre_depois_do_vencimento(self):
        """F5-05. Depois que o worker apaga a abertura vencida, o mesmo CPF
        começa uma abertura nova."""
        # prepara
        ana = pessoa_fisica()
        abertura = abertura_criada_ha(21, ana)
        espera_o_worker_apagar_o_cadastro(abertura)

        # age: o mesmo CPF, com outra chave
        resposta = Onboarding.cadastra(ana)

        # confere
        assert resposta.status_code == 201
        assert resposta.json()["onboarding_key"] != abertura["onboarding_key"]
