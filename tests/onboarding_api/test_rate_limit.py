"""F2: limites de pedidos no Redis (docs/testes/onboarding-api.md).

Cada teste usa a própria origem (X-Forwarded-For) e documentos novos, para
os contadores de um teste não atrapalharem os outros.
"""
import pytest

from tests.utils.onboarding_api import (
    FALHA_SIMULADA_LIGADA,
    Onboarding,
    cabecalhos_do_gateway,
    ip_aleatorio,
    nova_chave,
    pessoa_fisica,
)

TENTATIVAS_POR_DOCUMENTO_POR_HORA = 5
RECUSAS_QUE_BLOQUEIAM_A_ORIGEM = 20
BLOQUEIO_DA_ORIGEM_SEGUNDOS = 30 * 60
UMA_HORA_SEGUNDOS = 60 * 60


def cadastra_vindo_de(ip: str, dados: dict, extras: dict = None):
    """POST /onboarding vindo de um IP escolhido, com chave nova."""
    return Onboarding.cadastra(dados, cabecalhos_do_gateway(ip=ip, extras=extras))


def clientes_ja_cadastrados(quantos: int) -> list:
    """Cadastra `quantos` clientes, cada um vindo de um IP qualquer, e devolve os dados deles."""
    clientes = [pessoa_fisica() for _ in range(quantos)]
    for cliente in clientes:
        Onboarding.comeca_abertura(cliente)
    return clientes


def confere_tentativas_demais(resposta, espera_maxima_segundos: int) -> None:
    """429 ONB005013, com o Retry-After dizendo quantos segundos esperar."""
    assert resposta.status_code == 429
    assert resposta.json()["code"] == "ONB005013"
    assert 0 < int(resposta.headers["Retry-After"]) <= espera_maxima_segundos


class TestLimitePorDocumento:
    def test_sexta_tentativa_do_mesmo_documento_na_hora_e_recusada(self):
        """F2-01. Cinco tentativas por documento por hora; a sexta espera o Retry-After."""
        # prepara: cinco tentativas com o mesmo CPF (uma cria, quatro levam 409)
        ip = ip_aleatorio()
        ana = pessoa_fisica()
        status = [cadastra_vindo_de(ip, ana).status_code for _ in range(TENTATIVAS_POR_DOCUMENTO_POR_HORA)]
        assert status == [201, 409, 409, 409, 409]

        # age: a sexta
        resposta = cadastra_vindo_de(ip, ana)

        # confere
        confere_tentativas_demais(resposta, UMA_HORA_SEGUNDOS)

    def test_repetir_uma_tentativa_ja_contada_recebe_a_mesma_resposta(self):
        """F2-07. Repetir uma tentativa (mesma chave) não é tentativa nova: recebe
        a mesma resposta de antes, e não o 429. Só uma chave nova é barrada."""
        # prepara: cinco tentativas, cada uma com a sua chave
        ip = ip_aleatorio()
        ana = pessoa_fisica()
        chaves = [nova_chave() for _ in range(TENTATIVAS_POR_DOCUMENTO_POR_HORA)]
        for chave in chaves:
            Onboarding.cadastra(ana, cabecalhos_do_gateway(chave=chave, ip=ip))

        # age: repete a quinta chave, e depois tenta uma chave nova
        repetida = Onboarding.cadastra(ana, cabecalhos_do_gateway(chave=chaves[-1], ip=ip))
        nova = cadastra_vindo_de(ip, ana)

        # confere
        assert repetida.status_code == 409
        assert repetida.json()["code"] == "ONB005003"
        confere_tentativas_demais(nova, UMA_HORA_SEGUNDOS)

    def test_limite_de_um_documento_nao_atrapalha_outro(self):
        """F2-02. O documento barrado não barra os outros documentos da mesma origem."""
        # prepara: um CPF que estourou o limite
        ip = ip_aleatorio()
        ana = pessoa_fisica()
        for _ in range(TENTATIVAS_POR_DOCUMENTO_POR_HORA + 1):
            cadastra_vindo_de(ip, ana)

        # age: outro CPF, da mesma origem
        resposta = cadastra_vindo_de(ip, pessoa_fisica())

        # confere
        assert resposta.status_code == 201


class TestLimitePorOrigem:
    def test_vinte_recusas_bloqueiam_a_origem(self):
        """F2-03. Quem testa CPFs para descobrir quem é cliente fica bloqueado
        por 30 minutos, até para pedidos certos."""
        # prepara: o atacante tenta 20 CPFs que já são clientes (20 recusas)
        atacante = ip_aleatorio()
        for cliente in clientes_ja_cadastrados(RECUSAS_QUE_BLOQUEIAM_A_ORIGEM):
            assert cadastra_vindo_de(atacante, cliente).json()["code"] == "ONB005003"

        # age: um pedido novo e certo, da mesma origem
        resposta = cadastra_vindo_de(atacante, pessoa_fisica())

        # confere
        confere_tentativas_demais(resposta, BLOQUEIO_DA_ORIGEM_SEGUNDOS)

    def test_dezenove_recusas_nao_bloqueiam_a_origem(self):
        """F2-04. O outro lado da borda: 19 recusas ainda não bloqueiam."""
        # prepara: 19 recusas
        ip = ip_aleatorio()
        for cliente in clientes_ja_cadastrados(RECUSAS_QUE_BLOQUEIAM_A_ORIGEM - 1):
            assert cadastra_vindo_de(ip, cliente).status_code == 409

        # age
        resposta = cadastra_vindo_de(ip, pessoa_fisica())

        # confere
        assert resposta.status_code == 201

    def test_origem_bloqueada_nao_bloqueia_as_outras(self):
        """F2-05. O bloqueio vale só para a origem que errou demais."""
        # prepara: o atacante fica bloqueado
        atacante = ip_aleatorio()
        for cliente in clientes_ja_cadastrados(RECUSAS_QUE_BLOQUEIAM_A_ORIGEM):
            cadastra_vindo_de(atacante, cliente)
        assert cadastra_vindo_de(atacante, pessoa_fisica()).status_code == 429

        # age: um pedido de outra origem
        resposta = cadastra_vindo_de(ip_aleatorio(), pessoa_fisica())

        # confere
        assert resposta.status_code == 201


@pytest.mark.fault_injection
@pytest.mark.skipif(not FALHA_SIMULADA_LIGADA, reason="precisa da API e do pytest com FAULT_INJECTION_ENABLED=true")
class TestRedisFora:
    def test_sem_redis_os_limites_desligam_e_a_api_continua(self):
        """F2-06. Com o Redis fora, os limites desligam e o resto continua funcionando."""
        # prepara: cinco tentativas do mesmo CPF, com o Redis fora (falha simulada)
        redis_fora = {"X-Fault-Injection": "redis_unavailable"}
        ip = ip_aleatorio()
        ana = pessoa_fisica()
        for _ in range(TENTATIVAS_POR_DOCUMENTO_POR_HORA):
            cadastra_vindo_de(ip, ana, redis_fora)

        # age: a sexta
        resposta = cadastra_vindo_de(ip, ana, redis_fora)

        # confere: sem limite, a sexta recebe o 409 normal, e um CPF novo passa
        assert resposta.status_code == 409
        assert resposta.json()["code"] == "ONB005003"
        assert cadastra_vindo_de(ip, pessoa_fisica(), redis_fora).status_code == 201
