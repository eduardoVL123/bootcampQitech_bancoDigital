"""Ataques: mutacoes de um cenario legitimo que tentam passar por baixo de todos os cortes.

Cada teste faz o papel de quem quer burlar o motor. Parte de um cliente com
rotina de verdade (um Pix por dia para 3 destinos de sempre) e muda o que
um golpista mudaria para nao acender nenhuma regra: o intervalo entre os
Pix, o valor logo abaixo do corte, a conta que recebe, o aparelho, o canal.
As taticas sao as que o mercado descreve (conta laranja alugada ou antiga,
pulverizacao em cascata, valor abaixo do limite, mao fantasma com acesso
remoto, conta parada que volta); o catalogo, com as fontes, esta em
docs/testes/antifraude-ataques.md.

O que cada teste exige e o MINIMO que uma defesa razoavel daria: que o
ataque inteiro nao passe sem nenhum atrito. Onde a vitima enganada e quem
faz a facial (a falsa central, o falso parente), a facial sozinha nao
protege: o teste exige a verificacao COM o aviso ao pagador
(`metadata.authentication.payer_warning`), que e o que o app mostra na hora.

ESCRITOS EM 18/10/2026 SEM RODAR, enquanto o motor estava em mudanca. A
expectativa e que varios fiquem vermelhos: e para isso que existem, cada
vermelho e uma porta aberta. Por isso so rodam com RUN_ATAQUES=true, e
nenhum CI liga essa chave.
"""
from datetime import timedelta
from os import environ
from uuid import uuid4

import pytest

from tests.utils.pix import (
    REDE_RECIFE, SAO_PAULO_GPS, AntifraudApi, Pagador, Recebedor, analisa, nova_base, novo_ip, paga, pix,
)

pytestmark = pytest.mark.skipif(environ.get("RUN_ATAQUES") != "true",
                                reason="ataques ao motor: ligue com RUN_ATAQUES=true (ver docs/testes/antifraude-ataques.md)")

# Valores da rotina do cliente, em centavos: entre R$ 150 e R$ 250, mediana perto de R$ 200.
ROTINA = (15000, 18000, 20000, 22000, 25000)


# ----------------------------------------------------------------------
# Ferramentas
# ----------------------------------------------------------------------

def _rotina(pagador: Pagador, hoje, valores=ROTINA, dias: int = 45, gps: bool = True) -> list:
    """O cliente de verdade: um Pix por dia, as 10h, para 3 destinos de sempre, nos `dias` antes de hoje."""
    destinos = [Recebedor() for _ in range(3)]
    for dia in range(dias, 0, -1):
        momento = (hoje - timedelta(days=dia)).replace(hour=10, minute=0, second=0)
        extra = {} if gps else {"gps": None}
        paga(pix(pagador, destinos[dia % 3], valores[dia % len(valores)], momento.isoformat(), **extra))
    return destinos


def _aparelho_do_golpista() -> str:
    return f"dvc-golpista-{uuid4().hex[:10]}"


def _passou(corpo: dict) -> bool:
    return corpo["status"] == "approved"


def _resumo(corpos: list) -> list:
    """Para a mensagem de falha: status, score e as regras que pontuaram em cada Pix."""
    return [(c["status"], c["metadata"]["risk_score"],
             [r["rule"] for r in c["metadata"]["rules"] if r["effective_points"]]) for c in corpos]


# ----------------------------------------------------------------------
# 1. O golpista no aparelho da vitima (mao fantasma, acesso remoto)
#
# Aparelho, IP e GPS sao os de sempre: so o comportamento pode denunciar.
# ----------------------------------------------------------------------

def test_dreno_abaixo_de_todos_os_cortes_no_aparelho_da_vitima_nao_passa_inteiro():
    # Mutacoes: R$ 650 (a menos de R$ 500 da mediana, abaixo da diferenca
    # minima do PERFIL e do corte de R$ 1.000 da CONTRAPARTE_INEDITA); um Pix
    # a cada 31 min (fora da janela de 30 min da VELOCITY e com no maximo 2
    # na hora do FATIAMENTO); cada um para uma conta laranja antiga (sem
    # DESTINO_NOVO). Dez Pix sao R$ 6.500 numa manha, 30 vezes o dia normal.
    hoje = nova_base().replace(hour=9, minute=0, second=0)
    vitima = Pagador()
    _rotina(vitima, hoje)

    corpos = [analisa(pix(vitima, Recebedor(), 65000, (hoje + timedelta(minutes=31 * i)).isoformat()))
              for i in range(10)]

    assert not all(_passou(c) for c in corpos), _resumo(corpos)


def test_valor_subindo_aos_poucos_para_o_mesmo_destino_trava_antes_de_10_vezes_a_mediana():
    # "Sapo fervendo": um Pix por dia para a mesma conta, 40% maior que o
    # anterior, comecando na mediana do cliente. O golpista nao passa em
    # nenhuma facial, entao nada que pediu 2FA vira historico.
    hoje = nova_base()
    vitima = Pagador()
    _rotina(vitima, hoje, dias=30)
    laranja = Recebedor()

    valor, dia, corpos = 20000, 0, []
    while valor < 200000:
        corpos.append(paga(pix(vitima, laranja, valor, (hoje + timedelta(days=dia)).isoformat()), confirma=False))
        valor, dia = int(valor * 1.4), dia + 1

    assert not all(_passou(c) for c in corpos), _resumo(corpos)


def test_conta_parada_ha_90_dias_volta_devagar_abaixo_da_rajada_e_do_perfil():
    # CONTA_REATIVADA pede 3 tentativas em 1 h ou valor acima de R$ 5.000.
    # O golpista volta com 2 Pix por hora de R$ 650; o historico da conta
    # ficou fora da janela de 90 dias do PERFIL.
    hoje = nova_base().replace(hour=9, minute=0, second=0)
    vitima = Pagador()
    _rotina(vitima, hoje - timedelta(days=90), dias=30)

    corpos = [analisa(pix(vitima, Recebedor(), 65000, (hoje + timedelta(minutes=31 * i)).isoformat()))
              for i in range(6)]

    assert not all(_passou(c) for c in corpos), _resumo(corpos)


# ----------------------------------------------------------------------
# 2. O golpista no aparelho dele (conta tomada)
# ----------------------------------------------------------------------

def test_gps_forjado_no_lugar_de_sempre_com_ip_de_outra_regiao_nao_passa():
    # O GPS diz Sao Paulo (o ponto de sempre), o IP diz Recife, o aparelho e
    # novo. O valor fica abaixo do corte de R$ 20 mil do LIMITE_POR_PIX.
    hoje = nova_base()
    vitima = Pagador()
    _rotina(vitima, hoje)

    corpo = analisa(pix(vitima, Recebedor(), 300000, hoje.isoformat(), aparelho=_aparelho_do_golpista(),
                        ip=novo_ip(REDE_RECIFE), gps=SAO_PAULO_GPS))

    assert not _passou(corpo), _resumo([corpo])


def test_aparelho_novo_com_pix_de_199_nao_drena_o_dia_de_quem_nunca_manda_gps():
    # A regra do BC deixa aparelho sem cadastro fazer ate R$ 200 por Pix e
    # R$ 1.000 por dia (APARELHO_NAO_CADASTRADO). O titular nunca manda GPS
    # (GEO_AUSENTE nao pesa para ele), o IP e de rede privada (nenhuma
    # regra de geografia avalia), e cada Pix vai para uma laranja antiga.
    hoje = nova_base().replace(hour=9, minute=0, second=0)
    vitima = Pagador()
    _rotina(vitima, hoje, gps=False)
    aparelho = _aparelho_do_golpista()

    corpos = [analisa(pix(vitima, Recebedor(), 19900, (hoje + timedelta(minutes=31 * i)).isoformat(),
                          aparelho=aparelho, ip="10.23.45.67", gps=None))
              for i in range(5)]

    assert not all(_passou(c) for c in corpos), _resumo(corpos)


def test_pessoa_fisica_que_sempre_usa_o_app_aparecendo_pela_api_com_aparelho_novo_nao_passa():
    # Pelo canal api, GEO_AUSENTE vale 0 e APARELHO_NAO_CADASTRADO nao se
    # aplica: foram pensados para a empresa que paga pelo proprio sistema.
    # Uma pessoa fisica que sempre usou o app aparece de repente pela api
    # (credencial roubada num iniciador de pagamento), de aparelho novo.
    hoje = nova_base()
    vitima = Pagador()
    _rotina(vitima, hoje)

    corpo = analisa(pix(vitima, Recebedor(), 65000, hoje.isoformat(), aparelho=_aparelho_do_golpista(),
                        canal="api", gps=None))

    assert not _passou(corpo), _resumo([corpo])


def test_aparelho_cadastrado_por_um_codigo_confirmado_nao_libera_valor_fora_do_perfil():
    # Engenharia social: "confirme o codigo que chegou". O primeiro Pix do
    # aparelho novo pede a facial, a vitima enganada confirma, e o aparelho
    # passa a contar como cadastrado. O golpista entao pede o valor alto.
    hoje = nova_base()
    vitima = Pagador()
    _rotina(vitima, hoje)
    aparelho = _aparelho_do_golpista()

    isca = pix(vitima, Recebedor(), 30000, hoje.isoformat(), aparelho=aparelho)
    corpo = analisa(isca)
    assert corpo["status"] == "two_factor_required", _resumo([corpo])
    resposta = AntifraudApi.patch(isca["id"], {"challenge_result": "approved_by_client",
                                               "event_date": isca["transaction_date"]})
    assert resposta.status_code == 200, resposta.text

    saque = analisa(pix(vitima, Recebedor(), 400000, (hoje + timedelta(minutes=20)).isoformat(), aparelho=aparelho))

    assert not _passou(saque), _resumo([saque])


# ----------------------------------------------------------------------
# 3. Dividir entre contas do mesmo titular
# ----------------------------------------------------------------------

@pytest.mark.parametrize("contas", [1, 3], ids=["controle_uma_conta", "ataque_tres_contas_do_mesmo_cpf"])
def test_rajada_de_9_pix_em_4_minutos_nao_passa_inteira(contas):
    # A VELOCITY conta tentativas por CONTA. Nove Pix numa conta so passam
    # do corte de 5 em 5 min; divididos em tres contas do mesmo CPF, no
    # mesmo aparelho e no mesmo IP, cada conta fica com 3.
    hoje = nova_base()
    titular = Pagador()
    origens = [titular] + [Pagador(documento=titular.documento) for _ in range(contas - 1)]
    for origem in origens[1:]:
        origem.aparelho, origem.ip = titular.aparelho, titular.ip

    corpos = [analisa(pix(origens[i % contas], Recebedor(), 30000, (hoje + timedelta(seconds=25 * i)).isoformat()))
              for i in range(9)]

    assert not all(_passou(c) for c in corpos), _resumo(corpos)


# ----------------------------------------------------------------------
# 4. A conta laranja (o lado de quem recebe)
# ----------------------------------------------------------------------

def test_laranja_antiga_que_recebe_4_vitimas_por_hora_o_dia_todo():
    # CONTA_LARANJA pontua com 5 pagadores na hora; a laranja antiga (conta
    # de 2019, comprada ou alugada) recebe 4 por hora, durante 6 horas: 24
    # vitimas no dia, cada uma com R$ 900 (abaixo do corte da CONTRAPARTE).
    # A partir da 20a, o padrao do dia ja nao tem como ser loja de bairro.
    hoje = nova_base().replace(hour=8, minute=0, second=0)
    laranja = Recebedor()

    corpos = [analisa(pix(Pagador(), laranja, 90000, (hoje + timedelta(minutes=15 * i)).isoformat()))
              for i in range(24)]

    assert not all(_passou(c) for c in corpos[19:]), _resumo(corpos[19:])


def test_fazenda_de_contas_cada_uma_com_aparelho_e_ip_proprios_para_conta_nova():
    # COORDENACAO_ENTRE_CONTAS precisa do mesmo aparelho; CONTA_LARANJA,
    # de 5 pagadores na hora. Oito contas, cada uma com o seu aparelho e o
    # seu IP, pagam R$ 180 (abaixo do teto da conta nova) a uma conta de 3
    # dias, 4 por hora.
    hoje = nova_base().replace(hour=9, minute=0, second=0)
    laranja = Recebedor(aberta_em=hoje - timedelta(days=3))

    corpos = [analisa(pix(Pagador(), laranja, 18000, (hoje + timedelta(minutes=16 * i)).isoformat()))
              for i in range(8)]

    assert not all(_passou(c) for c in corpos), _resumo(corpos)


# ----------------------------------------------------------------------
# 5. A vitima enganada (falso parente, falsa central, conta segura)
#
# Quem aperta o botao e o titular, no aparelho dele: a facial nao protege.
# ----------------------------------------------------------------------

def test_falso_parente_pede_valor_do_perfil_para_conta_aberta_ha_3_horas():
    # "Troquei de numero, me faz um Pix?": R$ 700, dentro do habito do
    # cliente (R$ 500 a R$ 700), para uma conta aberta ha 3 horas.
    hoje = nova_base()
    vitima = Pagador()
    _rotina(vitima, hoje, valores=(50000, 55000, 60000, 65000, 70000))
    golpista = Recebedor(aberta_em=hoje - timedelta(hours=3))

    corpo = analisa(pix(vitima, golpista, 70000, hoje.isoformat()))

    assert not _passou(corpo), _resumo([corpo])
    assert corpo["metadata"]["authentication"]["payer_warning"]["code"] == "new_payee_account"


def test_conta_segura_no_proprio_cpf_em_outro_banco_pede_verificacao_com_aviso():
    # A falsa central manda "proteger o saldo" numa conta nova no nome da
    # propria vitima, em outro banco, aberta ha 2 horas, sem nenhuma
    # marcacao no mock. A vitima passa na facial, entao a facial sozinha nao
    # protege. Reprovar toda transferencia alta para conta nova no proprio CPF,
    # porem, barraria quem so esta trocando de banco: o que protege e o aviso
    # na hora ("nenhum banco pede conta segura"). Decisao de 18/10/2026; antes
    # o teste exigia `rejected`.
    hoje = nova_base()
    vitima = Pagador()
    _rotina(vitima, hoje)
    conta_segura = Recebedor(documento=vitima.documento, aberta_em=hoje - timedelta(hours=2), participante="00000001")

    corpo = analisa(pix(vitima, conta_segura, 800000, hoje.isoformat()))

    assert corpo["status"] == "two_factor_required", _resumo([corpo])
    assert corpo["metadata"]["authentication"]["payer_warning"]["code"] == "safe_account"


# ----------------------------------------------------------------------
# 6. O horario
# ----------------------------------------------------------------------

@pytest.mark.parametrize("pj, idade_dias", [(False, 400), (True, 31)],
                         ids=["controle_pessoa_fisica", "ataque_pj_de_31_dias"])
def test_pix_noturno_de_1900_para_quem_nao_e_loja_estabelecida(pj, idade_dias):
    # O NOTURNO vale para pessoa fisica e para PJ com conta de menos de 30
    # dias. O MEI de fachada da laranja espera o 31o dia. O cliente gasta
    # de R$ 1.200 a R$ 1.800 de dia; R$ 1.900 fica a menos de R$ 500 da
    # mediana (PERFIL nao pesa).
    hoje = nova_base().replace(hour=23, minute=10, second=0)
    vitima = Pagador()
    _rotina(vitima, hoje, valores=(120000, 135000, 150000, 165000, 180000))
    recebedor = Recebedor(pj=pj, aberta_em=hoje - timedelta(days=idade_dias))

    corpo = analisa(pix(vitima, recebedor, 190000, hoje.isoformat()))

    assert not _passou(corpo), _resumo([corpo])
