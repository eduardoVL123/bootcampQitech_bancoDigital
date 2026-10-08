"""F10: LGPD, transversal (docs/testes/onboarding-api.md).

Dado pessoal (CPF, CNPJ, nome, renda, data de nascimento) nunca aparece em
URL nem em log. Os outros pontos da LGPD já têm teste nas fatias: respostas,
erros, verificações, fila, eventos e dados apagados no prazo.

O F10-02 lê o log pelo docker compose logs, como faria quem cuida do
serviço. Ele não lê o banco nem importa o código (R1). Sem docker, pula.
"""
import shutil
import subprocess
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from tests.utils.mockserver import account_api_responde, biros_regulares
from tests.utils.onboarding_api import (
    Onboarding,
    cabecalhos_do_gateway,
    credencial_de_compliance,
    espera_etapa,
    imagens,
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
        joana = pessoa_fisica(name="Joana Logadissima", declared_monthly_income_cents=7654321)

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
