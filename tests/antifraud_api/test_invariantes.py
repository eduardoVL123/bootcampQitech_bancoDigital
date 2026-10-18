"""O que toda resposta do motor tem que cumprir, qualquer que seja o Pix.

Os outros testes perguntam "esta regra disparou?". Estes perguntam se a
conta fecha: se o score e a soma dos eixos, se cada eixo e a soma das suas
regras, se a decisao bate com a tabela da politica, se o motivo e a regra
que mais pesou. Um erro aqui nao aparece em nenhum teste de regra, porque
cada regra pode estar certa e a soma errada.

Os cenarios sao variados de proposito (honesto, madrugada, valor alto,
recebedor marcado, data recuada, aparelho de outro titular...), e
as invariantes sao conferidas em todos, no POST e no GET.

Depois vem os testes metamorficos: duas formas do mesmo Pix dao a mesma
analise, e subir o valor, com tudo o mais igual, nunca afrouxa a decisao.
"""
from datetime import timedelta, timezone

import pytest

from tests.utils.pix import (
    RECEBEDOR_ALERTA, RECEBEDOR_MARCACAO_CRITICA, RECEBEDOR_NA_WATCHLIST, REDE_LISBOA, AntifraudApi, Pagador,
    Recebedor, analisa, historico, nova_base, novo_ip, pix,
)
from tests.utils.run_at_the_same_time import run_at_the_same_time

# A tabela da politica no seed (database/antifraud.sql, "decision" e "reducers").
FACIAL, FACIAL_DOCUMENT, REJECT = 40, 60, 80
REJECT_MIN_AXIS_POINTS, REJECT_MIN_AXES, REJECT_DESTINATION_ALONE = 20, 2, 80
# O eixo destino so rejeita sozinho com denuncia do recebedor ou acima do teto da conta nova.
DESTINATION_CORROBORATION = {"REPUTACAO_EXTERNA", "REPUTACAO_INTERNA"}
NEW_DESTINATION_CAP = "TETO_DESTINO_NOVO"
REDUCERS_MAX = 20
VALUE_FAMILY, TRUST_FAMILY = "valor_individual", "confianca"
CHECKS = {"none": [], "facial": ["facial"], "facial_document": ["facial", "document"]}
NIVEIS = ["none", "facial", "facial_document"]


def _analisa(payload):
    """Analisa e guarda o id do Pix no corpo, para o GET depois."""
    corpo = analisa(payload)
    corpo["_pix_id"] = payload["id"]
    return corpo


def cenarios():
    """Uma lista de (nome, corpo) com respostas bem diferentes entre si."""
    base = nova_base()
    saida = []

    agora = base.isoformat()
    saida.append(("honesto_pequeno", _analisa(pix(Pagador(), Recebedor(), 5000, agora))))
    saida.append(("madrugada_alto", _analisa(pix(Pagador(), Recebedor(), 800000, base.replace(hour=3).isoformat()))))
    saida.append(("valor_enorme", _analisa(pix(Pagador(), Recebedor(), 50000000, agora))))
    saida.append(("marcacao_critica", _analisa(pix(Pagador(), Recebedor(documento=RECEBEDOR_MARCACAO_CRITICA), 5000, agora))))
    saida.append(("alerta_externo", _analisa(pix(Pagador(), Recebedor(documento=RECEBEDOR_ALERTA), 300000, agora))))
    saida.append(("lista_interna", _analisa(pix(Pagador(), Recebedor(documento=RECEBEDOR_NA_WATCHLIST), 5000, agora))))
    conta_de_ontem = Recebedor(aberta_em=base - timedelta(hours=20))
    saida.append(("conta_destino_de_ontem", _analisa(pix(Pagador(), conta_de_ontem, 400000, agora))))
    saida.append(("ip_de_lisboa", _analisa(pix(Pagador(), Recebedor(), 200000, agora, ip=novo_ip(REDE_LISBOA)))))
    saida.append(("sem_gps", _analisa(pix(Pagador(), Recebedor(), 200000, agora, gps=None))))

    recuado = Pagador()
    _analisa(pix(recuado, Recebedor(), 5000, base.isoformat()))
    saida.append(("data_recuada", _analisa(pix(recuado, Recebedor(), 5000, (base - timedelta(hours=3)).isoformat()))))

    # Cliente com historico pagando o mesmo recebedor de sempre: os redutores entram.
    fiel, aluguel = Pagador(), Recebedor()
    inicio = base - timedelta(days=120)
    historico(fiel, [150000] * 4, inicio, timedelta(days=30), recebedor=aluguel)
    saida.append(("aluguel_de_sempre", _analisa(pix(fiel, aluguel, 160000, base.isoformat()))))
    saida.append(("fiel_valor_fora", _analisa(pix(fiel, Recebedor(), 1500000, (base + timedelta(minutes=5)).isoformat()))))

    # Rajada: o mesmo pagador para varios recebedores em minutos.
    rajada = Pagador()
    for minuto in range(6):
        corpo = _analisa(pix(rajada, Recebedor(), 90000, (base + timedelta(minutes=minuto)).isoformat()))
    saida.append(("rajada", corpo))

    # Aparelho de outro titular.
    dono = Pagador()
    _analisa(pix(dono, Recebedor(), 5000, (base - timedelta(days=2)).isoformat()))
    saida.append(("aparelho_de_outro", _analisa(pix(Pagador(), Recebedor(), 300000, agora, aparelho=dono.aparelho))))

    # Muitos pagadores para a mesma conta nova.
    laranja = Recebedor(aberta_em=base - timedelta(days=3))
    for minuto in range(7):
        corpo = _analisa(pix(Pagador(), laranja, 80000, (base + timedelta(minutes=minuto)).isoformat()))
    saida.append(("conta_laranja", corpo))
    return saida


CENARIOS = None


def _cenarios():
    global CENARIOS
    if CENARIOS is None:
        CENARIOS = cenarios()
    return CENARIOS


def _ids():
    return ["honesto_pequeno", "madrugada_alto", "valor_enorme", "marcacao_critica", "alerta_externo", "lista_interna",
            "conta_destino_de_ontem", "ip_de_lisboa", "sem_gps", "data_recuada",
            "aluguel_de_sempre", "fiel_valor_fora", "rajada", "aparelho_de_outro", "conta_laranja"]


def _corpo(nome):
    return dict(_cenarios())[nome]


def _disparadas(corpo):
    return [r for r in corpo["metadata"]["rules"] if r["evaluation"] == "triggered"]


@pytest.mark.parametrize("nome", _ids())
def test_score_e_a_soma_dos_eixos_limitada_a_0_100(nome):
    meta = _corpo(nome)["metadata"]

    assert meta["risk_score"] == max(0, min(100, sum(meta["risk_axes"].values())))


@pytest.mark.parametrize("nome", _ids())
def test_cada_eixo_e_a_soma_das_suas_regras(nome):
    meta = _corpo(nome)["metadata"]
    somas = {eixo: 0 for eixo in meta["risk_axes"]}
    for resultado in meta["rules"]:
        if resultado["axis"] in somas:
            somas[resultado["axis"]] += resultado["effective_points"]

    assert somas == meta["risk_axes"]


@pytest.mark.parametrize("nome", _ids())
def test_so_uma_regra_conta_por_familia(nome):
    contam = {}
    for resultado in _disparadas(_corpo(nome)):
        if resultado["family"] != TRUST_FAMILY and resultado["effective_points"] > 0:
            contam.setdefault(resultado["family"], []).append(resultado["rule"])

    assert all(len(regras) == 1 for regras in contam.values()), contam


@pytest.mark.parametrize("nome", _ids())
def test_a_regra_que_conta_e_a_maior_da_familia(nome):
    # Dentro da familia so a maior conta. Se uma menor contou e a maior ficou
    # como correlata, o motor jogou pontos fora.
    for resultado in _disparadas(_corpo(nome)):
        if resultado["family"] == TRUST_FAMILY or resultado["raw_points"] <= 0:
            continue
        da_familia = [r for r in _disparadas(_corpo(nome)) if r["family"] == resultado["family"]]
        maior = max(r["raw_points"] for r in da_familia)
        contada = sum(r["effective_points"] for r in da_familia)
        resumo = [(r["rule"], r["raw_points"], r["effective_points"]) for r in da_familia]
        assert contada in (0, maior), (resultado["family"], resumo)


@pytest.mark.parametrize("nome", _ids())
def test_pontos_efetivos_nunca_passam_dos_brutos(nome):
    for resultado in _corpo(nome)["metadata"]["rules"]:
        if resultado["raw_points"] >= 0:
            assert 0 <= resultado["effective_points"] <= resultado["raw_points"], resultado
        else:
            assert resultado["raw_points"] <= resultado["effective_points"] <= 0, resultado
        if resultado["correlated"]:
            assert resultado["effective_points"] == 0, resultado


@pytest.mark.parametrize("nome", _ids())
def test_redutores_respeitam_o_teto_e_o_valor(nome):
    regras = _disparadas(_corpo(nome))
    desconto = -sum(r["effective_points"] for r in regras if r["family"] == TRUST_FAMILY)
    valor = sum(r["effective_points"] for r in regras if r["family"] == VALUE_FAMILY)

    assert 0 <= desconto <= min(REDUCERS_MAX, valor)


@pytest.mark.parametrize("nome", _ids())
def test_decisao_bate_com_a_tabela_da_politica(nome):
    corpo = _corpo(nome)
    meta = corpo["metadata"]
    regras = _disparadas(corpo)
    score, eixos = meta["risk_score"], meta["risk_axes"]
    fortes = sum(1 for total in eixos.values() if total >= REJECT_MIN_AXIS_POINTS)
    piso = max((r["authentication_floor"] for r in regras), key=NIVEIS.index, default="none")

    if any(r["hard_block"] for r in regras):
        esperado = ("rejected", "none")
    elif score >= REJECT and fortes >= REJECT_MIN_AXES:
        esperado = ("rejected", "none")
    elif eixos["destino"] >= REJECT_DESTINATION_ALONE and any(
            (r["rule"] in DESTINATION_CORROBORATION and r.get("kind") != "device") or r["rule"] == NEW_DESTINATION_CAP
            for r in regras):
        esperado = ("rejected", "none")
    elif score >= FACIAL_DOCUMENT or piso == "facial_document":
        esperado = ("two_factor_required", "facial_document")
    elif score >= FACIAL or piso == "facial":
        esperado = ("two_factor_required", "facial")
    else:
        esperado = ("approved", "none")

    assert (corpo["status"], meta["authentication"]["level"]) == esperado


@pytest.mark.parametrize("nome", _ids())
def test_verificacoes_pedidas_batem_com_o_nivel(nome):
    autenticacao = _corpo(nome)["metadata"]["authentication"]

    assert autenticacao["required_checks"] == CHECKS[autenticacao["level"]]
    assert (autenticacao["execution"] == "not_required") == (autenticacao["level"] == "none")


@pytest.mark.parametrize("nome", _ids())
def test_eixo_da_rejeicao_so_aparece_na_rejeicao(nome):
    corpo = _corpo(nome)
    eixo = corpo["metadata"]["rejection_axis"]

    if corpo["status"] != "rejected":
        assert eixo is None
    else:
        assert eixo in corpo["metadata"]["risk_axes"]


@pytest.mark.parametrize("nome", _ids())
def test_motivo_e_a_regra_que_mais_pesou(nome):
    meta = _corpo(nome)["metadata"]
    regras = _disparadas(_corpo(nome))
    bloqueios = [r["rule"] for r in regras if r["hard_block"]]
    com_pontos = [r for r in regras if r["effective_points"] > 0]

    if bloqueios:
        assert meta["reason"] in bloqueios
    elif com_pontos:
        maior = max(r["effective_points"] for r in com_pontos)
        assert meta["reason"] in [r["rule"] for r in com_pontos if r["effective_points"] == maior]
    elif meta["authentication"]["level"] == "none":
        assert meta["reason"] == "SEM_ALERTA"


@pytest.mark.parametrize("nome", _ids())
def test_get_devolve_a_mesma_analise_do_post(nome):
    corpo = _corpo(nome)
    lido = AntifraudApi.get(corpo["_pix_id"]).json()

    assert lido["key"] == corpo["key"]
    assert lido["status"] == corpo["status"]
    assert lido["metadata"]["risk_score"] == corpo["metadata"]["risk_score"]
    assert lido["metadata"]["rules"] == corpo["metadata"]["rules"]


# Metamorficos: duas formas do mesmo Pix.

def test_mesmo_instante_em_fusos_diferentes_da_a_mesma_analise():
    base = nova_base().replace(hour=23, minute=40)
    corpos = []
    for fuso in (-3, 0, 9, -10):
        momento = base.astimezone(timezone(timedelta(hours=fuso)))
        corpos.append(analisa(pix(Pagador(), Recebedor(), 600000, momento.isoformat())))

    assert len({c["metadata"]["risk_score"] for c in corpos}) == 1
    assert len({c["metadata"]["signals"]["local_time"] for c in corpos}) == 1
    assert len({c["status"] for c in corpos}) == 1


def test_documento_com_e_sem_mascara_e_a_mesma_pessoa():
    # O recebedor marcado tem que ser marcado nas duas grafias.
    com_mascara = analisa(pix(Pagador(), Recebedor(documento=RECEBEDOR_MARCACAO_CRITICA), 5000, nova_base().isoformat()))
    sem_mascara = analisa(pix(Pagador(), Recebedor(documento=RECEBEDOR_MARCACAO_CRITICA.replace(".", "").replace("-", "")),
                              5000, nova_base().isoformat()))

    assert com_mascara["status"] == sem_mascara["status"] == "rejected"


def test_historico_com_mascara_conta_para_o_pix_sem_mascara():
    # O mesmo pagador, uma vez com o CPF mascarado e outra sem: a rajada
    # tem que ser vista como de uma pessoa so.
    base = nova_base()
    pagador = Pagador()
    sem_mascara = Pagador(documento=pagador.documento.replace(".", "").replace("-", ""))
    sem_mascara.conta, sem_mascara.aparelho, sem_mascara.ip = pagador.conta, pagador.aparelho, pagador.ip
    for minuto in range(5):
        analisa(pix(pagador if minuto % 2 else sem_mascara, Recebedor(), 50000, (base + timedelta(minutes=minuto)).isoformat()))

    ultimo = analisa(pix(sem_mascara, Recebedor(), 50000, (base + timedelta(minutes=5)).isoformat()))
    assert any(r["rule"] == "VELOCITY" and r["evaluation"] == "triggered" for r in ultimo["metadata"]["rules"])


def test_replay_devolve_a_mesma_resposta_byte_a_byte():
    payload = pix(Pagador(), Recebedor(), 700000, nova_base().replace(hour=2).isoformat())
    primeira = AntifraudApi.post(payload)
    segunda = AntifraudApi.post(payload)

    assert (primeira.status_code, segunda.status_code) == (201, 200)
    assert primeira.json() == segunda.json()


# Monotonia: com o resto igual, valor maior nunca afrouxa a decisao.

ESCADA = [1000, 10000, 50000, 200000, 500000, 1000000, 3000000, 10000000]


def _nivel(corpo):
    if corpo["status"] == "rejected":
        return 3
    return NIVEIS.index(corpo["metadata"]["authentication"]["level"])


def test_valor_maior_sem_historico_nunca_afrouxa():
    base = nova_base()
    niveis = [_nivel(analisa(pix(Pagador(), Recebedor(), valor, base.isoformat()))) for valor in ESCADA]

    assert niveis == sorted(niveis), list(zip(ESCADA, niveis))


def test_valor_maior_com_historico_nunca_afrouxa():
    # Cada degrau e um cliente com o mesmo historico: 6 Pix de R$ 300 em 3
    # meses, para o mesmo recebedor. So o valor do Pix final muda.
    base = nova_base()
    niveis, scores = [], []
    for valor in ESCADA:
        pagador, recebedor = Pagador(), Recebedor()
        historico(pagador, [30000] * 6, base - timedelta(days=90), timedelta(days=15), recebedor=recebedor)
        corpo = analisa(pix(pagador, Recebedor(), valor, base.isoformat()))
        niveis.append(_nivel(corpo))
        scores.append(corpo["metadata"]["risk_score"])

    assert niveis == sorted(niveis), list(zip(ESCADA, niveis, scores))


def test_mais_um_sinal_ruim_nunca_baixa_o_score():
    # O mesmo Pix, e o mesmo Pix de madrugada, com IP de fora e sem GPS.
    base = nova_base()
    limpo = analisa(pix(Pagador(), Recebedor(), 300000, base.isoformat()))
    ruim = analisa(pix(Pagador(), Recebedor(), 300000, base.replace(hour=3).isoformat(), ip=novo_ip(REDE_LISBOA),
                       gps=None))

    assert ruim["metadata"]["risk_score"] >= limpo["metadata"]["risk_score"]
    assert _nivel(ruim) >= _nivel(limpo)


# Concorrencia no que nao e o Pix em si.

@pytest.mark.concurrency
def test_respostas_simultaneas_do_desafio_ficam_coerentes():
    payload = pix(Pagador(), Recebedor(), 2500000, nova_base().isoformat())
    assert analisa(payload)["status"] == "two_factor_required"
    corpos = [{"challenge_result": r, "event_date": payload["transaction_date"]}
              for r in ["approved_by_client", "reproved_by_client"] * 5]

    respostas = run_at_the_same_time(lambda corpo: AntifraudApi.patch(payload["id"], corpo), corpos)

    assert all(r.status_code in (200, 409) for r in respostas), [r.status_code for r in respostas]
    gravado = AntifraudApi.get(payload["id"]).json()["metadata"]["challenge"]["result"]
    for corpo, resposta in zip(corpos, respostas):
        assert (resposta.status_code == 200) == (corpo["challenge_result"] == gravado)


@pytest.mark.concurrency
def test_mesmo_id_com_conteudos_diferentes_ao_mesmo_tempo():
    pagador, base = Pagador(), nova_base()
    pix_id = f"pix-corrida-{base.timestamp():.0f}-{pagador.conta}"
    payloads = [pix(pagador, Recebedor(), 5000 + i, base.isoformat(), id=pix_id) for i in range(8)]

    respostas = run_at_the_same_time(AntifraudApi.post, payloads)
    codigos = sorted(r.status_code for r in respostas)

    assert codigos == [201] + [409] * 7, codigos
