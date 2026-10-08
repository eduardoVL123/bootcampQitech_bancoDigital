"""F10: LGPD, transversal (docs/testes/onboarding-api.md).

Dado pessoal (CPF, CNPJ, nome, renda, data de nascimento) nunca aparece em
URL nem em log. Os outros pontos da LGPD já têm teste nas fatias: respostas,
erros, verificações, fila, eventos e dados apagados no prazo.

O F10-02, o F10-03 e o F10-04 leem o log pelo docker compose logs, como
faria quem cuida do serviço. Eles não leem o banco nem importam o código
(R1). Sem docker, pulam.
"""
import random
import re
import shutil
import string
import subprocess
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pytest

from tests.utils.mockserver import account_api_responde, biros_regulares
from tests.utils.onboarding_api import (
    Onboarding,
    cabecalhos_do_gateway,
    credencial_de_compliance,
    espera_etapa,
    imagens,
    novo_cnpj,
    novo_cpf,
    pessoa_fisica,
    so_digitos,
)

RAIZ_DO_PROJETO = Path(__file__).resolve().parents[2]
DOCKER = shutil.which("docker")

# O relógio da máquina e o do Docker podem não bater: o teste lê o log desde
# um pouco antes de começar. Ele procura só os dados da própria pessoa.
FOLGA_DO_RELOGIO_SEGUNDOS = 30

ETAPAS_FINAIS = {"ACTIVE", "REJECTED", "MANUAL_REVIEW"}


def pessoa_reconhecivel(primeiro_nome: str) -> dict:
    """Uma PF com nome, nascimento e renda novos a cada rodada, além do CPF.

    O log é lido com folga para trás: com dados fixos, o vazamento de uma
    rodada anterior faria a próxima falhar por um dado que não é dela. A
    pessoa tem de 31 a 60 anos e renda de R$ 70 mil a R$ 80 mil, para não
    disparar as regras de PLD da análise."""
    sobrenome = "".join(random.choices(string.ascii_lowercase, k=10)).capitalize()
    nascimento = date(random.randint(1966, 1994), random.randint(1, 12), random.randint(1, 28))
    return pessoa_fisica(
        name=f"{primeiro_nome} {sobrenome}",
        birth_date=nascimento.isoformat(),
        declared_monthly_income_cents=random.randint(7_000_000, 7_999_999),
    )


def log_desde(momento: datetime) -> str:
    """O log da onboarding-api e do onboarding-worker desde o momento pedido."""
    desde = momento.strftime("%Y-%m-%dT%H:%M:%SZ")
    feito = subprocess.run(
        [DOCKER, "compose", "logs", "--no-color", "--since", desde, "onboarding-api", "onboarding-worker"],
        cwd=RAIZ_DO_PROJETO,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=120,
    )
    assert feito.returncode == 0, feito.stderr
    return feito.stdout


# Começo de um registro novo no log: o formato da API ou o do uvicorn.
NOVO_REGISTRO = re.compile(r"^(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2},\d{3} \[|(INFO|WARNING|ERROR|DEBUG|CRITICAL):\s)")


def registro_do_pedido(log: str, protocolo: str, mensagem: str) -> str:
    """O registro do pedido que começa com a mensagem, junto com as linhas que
    vêm logo depois dele no mesmo container (o traceback). Vazio se não houver."""
    linhas = log.splitlines()
    for posicao, linha in enumerate(linhas):
        if f"[{protocolo}] - {mensagem}" not in linha:
            continue
        container = linha.split("|", 1)[0]
        registro = [linha]
        for seguinte in linhas[posicao + 1:]:
            if not seguinte.startswith(container):
                continue
            if NOVO_REGISTRO.match(seguinte.split("|", 1)[1].strip()):
                break
            registro.append(seguinte)
        return "\n".join(registro)
    return ""


class TestLgpd:
    def test_nenhuma_rota_recebe_dado_pessoal_na_url(self):
        """F10-01. Nenhuma rota aceita dado pessoal na URL: um CPF na query
        string da fila é parâmetro desconhecido, 400 ONB000001."""
        # age
        resposta = Onboarding.fila(credencial_de_compliance(), {"document_number": novo_cpf()})

        # confere
        assert resposta.status_code == 400, resposta.text
        assert resposta.json()["code"] == "ONB000001"
        assert "document_number" in [erro["field"] for erro in resposta.json()["errors"]]

    @pytest.mark.skipif(DOCKER is None, reason="precisa do docker para ler o log da API e do worker")
    def test_log_nunca_tem_documento_nem_renda(self):
        """F10-02 (decisão D34). Uma jornada inteira, com recusas no meio e até
        um CPF mandado por engano na URL, como valor e como nome de parâmetro:
        o log da API e do worker não guarda o CPF (com ou sem máscara), o nome,
        a renda nem a data de nascimento."""
        # prepara: uma pessoa fácil de reconhecer
        comeco = datetime.now(timezone.utc) - timedelta(seconds=FOLGA_DO_RELOGIO_SEGUNDOS)
        joana = pessoa_reconhecivel("Joana")

        # age: a jornada inteira, com as recusas no meio
        data_impossivel = Onboarding.cadastra({**joana, "birth_date": "2001-02-30"})
        abertura = Onboarding.comeca_abertura(joana)
        repetida = Onboarding.cadastra(joana, cabecalhos_do_gateway())
        cpf_na_url = Onboarding.fila(credencial_de_compliance(), {"document_number": joana["document_number"]})
        cpf_como_nome = Onboarding.fila(credencial_de_compliance(), {joana["document_number"]: "1"})
        biros_regulares(joana)
        account_api_responde(abertura, joana)
        rg = Onboarding.envia_rg(abertura["onboarding_key"], abertura["access_token"], imagens("front", "back"))
        final = espera_etapa(abertura, ETAPAS_FINAIS)
        cadastro = Onboarding.consulta_cliente(abertura["customer_key"], abertura["access_token"])

        # confere: a jornada aconteceu como esperado
        assert [data_impossivel.status_code, repetida.status_code, cpf_na_url.status_code, cpf_como_nome.status_code] == [422, 409, 400, 400]
        assert rg.status_code == 202
        assert final["status"] == "ACTIVE"
        assert cadastro.status_code == 200

        # confere: nada pessoal no log
        time.sleep(2)
        log = log_desde(comeco)
        assert "ENTROU" in log, "o log da API veio vazio"
        pessoais = {
            "CPF com mascara": joana["document_number"],
            "CPF sem mascara": so_digitos(joana["document_number"]),
            "nome": joana["name"],
            "renda": str(joana["declared_monthly_income_cents"]),
            "data de nascimento": joana["birth_date"],
        }
        for o_que, dado in pessoais.items():
            assert dado not in log, f"{o_que} apareceu no log"

    @pytest.mark.skipif(DOCKER is None, reason="precisa do docker para ler o log da API")
    @pytest.mark.parametrize(
        "documento, codigo",
        [
            pytest.param(novo_cpf(), "ONB005007", id="CPF com mascara"),
            pytest.param(so_digitos(novo_cpf()), "ONB005007", id="CPF sem mascara"),
            # A barra do CNPJ abre outro caminho, que nenhuma rota atende.
            pytest.param(novo_cnpj(), "ONB000404", id="CNPJ com mascara"),
            pytest.param(so_digitos(novo_cnpj()), "ONB005007", id="CNPJ sem mascara"),
        ],
    )
    def test_documento_no_caminho_da_url_nao_vai_para_o_log(self, documento, codigo):
        """F10-03 (decisão D35). Um documento posto por engano no caminho da URL,
        no lugar da chave do cliente, recebe 404, e nem ele nem a versão com ou
        sem pontuação ficam no log: CPF e CNPJ viram *** em toda linha."""
        # prepara
        comeco = datetime.now(timezone.utc) - timedelta(seconds=FOLGA_DO_RELOGIO_SEGUNDOS)

        # age
        resposta = Onboarding.consulta_cliente(documento, credencial_de_compliance())

        # confere: o pedido foi recusado como qualquer chave que não existe
        assert resposta.status_code == 404, resposta.text
        assert resposta.json()["code"] == codigo

        # confere: o pedido está no log, e o documento não
        time.sleep(2)
        log = log_desde(comeco)
        protocolo = resposta.json()["request_id"]
        assert f"[{protocolo}] - ENTROU GET /customer/" in log, "o pedido não apareceu no log"
        digitos = so_digitos(documento)
        if len(digitos) == 11:
            com_mascara = f"{digitos[:3]}.{digitos[3:6]}.{digitos[6:9]}-{digitos[9:]}"
        else:
            com_mascara = f"{digitos[:2]}.{digitos[2:5]}.{digitos[5:8]}/{digitos[8:12]}-{digitos[12:]}"
        assert com_mascara not in log, "o documento com mascara apareceu no log"
        assert digitos not in log, "o documento sem mascara apareceu no log"

    @pytest.mark.fault_injection
    @pytest.mark.skipif(DOCKER is None, reason="precisa do docker para ler o log da API")
    def test_erro_inesperado_do_banco_nao_leva_dado_pessoal_ao_log(self):
        """F10-04 (decisão D35). Um erro inesperado do banco, com os dados da
        pessoa no comando e na mensagem do PostgreSQL, responde 500 e fica no
        log só com o tipo e o SQLSTATE: nem o CPF, nem o nome, nem a data de
        nascimento, nem a renda. E nada é gravado."""
        # prepara: uma pessoa fácil de reconhecer e a falha do banco ligada
        comeco = datetime.now(timezone.utc) - timedelta(seconds=FOLGA_DO_RELOGIO_SEGUNDOS)
        rita = pessoa_reconhecivel("Rita")
        com_o_banco_falhando = cabecalhos_do_gateway(extras={"X-Fault-Injection": "database_error"})

        # age
        resposta = Onboarding.cadastra(rita, com_o_banco_falhando)

        # confere: erro inesperado, e a resposta não repete nada da pessoa
        assert resposta.status_code == 500, resposta.text
        assert resposta.json()["code"] == "ONB000500"
        pessoais = {
            "CPF com mascara": rita["document_number"],
            "CPF sem mascara": so_digitos(rita["document_number"]),
            "nome": rita["name"],
            "data de nascimento": rita["birth_date"],
            "renda": str(rita["declared_monthly_income_cents"]),
        }
        for o_que, dado in pessoais.items():
            assert dado not in resposta.text, f"{o_que} apareceu na resposta"

        # confere: o erro está no log, sem nada da pessoa
        time.sleep(2)
        log = log_desde(comeco)
        protocolo = resposta.json()["request_id"]
        registro = registro_do_pedido(log, protocolo, "Erro inesperado em POST /onboarding")
        assert registro, "o erro não apareceu no log"
        for o_que, dado in pessoais.items():
            assert dado not in log, f"{o_que} apareceu no log"
        assert "CheckViolation" in registro and "SQLSTATE 23514" in registro, "o log não diz qual erro do banco aconteceu"

        # confere: nada foi gravado, e o mesmo CPF abre a conta sem a falha
        assert Onboarding.cadastra(rita).status_code == 201
