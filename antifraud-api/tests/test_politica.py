"""A politica versao 2: o que o banco novo recebe e o que a migracao aplica num banco que ja existe.

Os dois caminhos precisam gravar a mesma politica. Aqui se le o SQL dos dois
arquivos, sem banco: o comando da migracao tem de ser o mesmo do
database/antifraud.sql, e a versao 2 (a 1 com os blocos da diferenca por
cima) tem de trazer o bloco de toda regra do motor.
"""
import json
import pathlib
import re

from controllers.rules import RULES

RAIZ = pathlib.Path(__file__).resolve().parents[2]
INICIAL = (RAIZ / "database" / "antifraud.sql").read_text(encoding="utf-8")
MIGRACAO = (RAIZ / "antifraud-api" / "migrations" / "0002_politica_v2.sql").read_text(encoding="utf-8")
COMANDO = re.compile(r"INSERT INTO fraud_policy \(version, parameters\)\nSELECT 2,.*?ON CONFLICT \(version\) DO NOTHING;", re.S)


def _versao_1() -> dict:
    return json.loads(re.search(r"VALUES \(1, '(\{.*?\})'\);", INICIAL, re.S).group(1))


def _diferenca() -> dict:
    return json.loads(re.search(r"parameters \|\| '(\{.*?\})'::jsonb", INICIAL, re.S).group(1))


def test_a_migracao_aplica_o_mesmo_comando_do_banco_novo():
    assert COMANDO.search(MIGRACAO).group(0) == COMANDO.search(INICIAL).group(0)


def test_a_migracao_e_idempotente():
    assert "ON CONFLICT (version) DO NOTHING" in MIGRACAO
    assert "CREATE INDEX IF NOT EXISTS pix_challenge_result_approved_event" in MIGRACAO


def test_a_versao_2_tem_o_bloco_de_toda_regra():
    versao_2 = {**_versao_1(), **_diferenca()}

    assert [regra.code for regra in RULES if regra.code not in versao_2] == []


def test_a_versao_1_continua_sem_os_blocos_novos():
    assert "DISPERSAO_DE_SAIDA" not in _versao_1()
    assert "window_hours" not in _versao_1()["CONTA_REATIVADA"]
