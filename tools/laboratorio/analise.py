"""Quanto confiar nos numeros, e o que mudaria com outra politica.

- intervalos: a margem de erro de cada taxa, reamostrando os episodios
  (bootstrap). Os Pix de um mesmo episodio nao sao independentes, entao a
  reamostragem e por episodio, nao por Pix.
- simular: refaz a decisao de cada Pix com outros cortes de pontos, a partir
  do que a propria API devolveu (score, pontos por eixo, piso e bloqueio). E
  aproximacao de primeira ordem: nao refaz o historico que a decisao nova
  teria mudado (um Pix barrado deixa de contar no perfil dos seguintes).
- efeito_das_regras: em quantos Pix cada regra foi decisiva (sem os pontos
  dela a decisao seria mais branda), separando golpe contido de cliente
  honesto atrapalhado.
- comparar: os mesmos episodios (perfil, botoes e semente) contra outra
  versao da API, episodio por episodio.
"""

import random
from collections import defaultdict

from laboratorio import avaliacao
from laboratorio.mundo import ORDEM

# A politica da API hoje (fraud_policy versao 1, no database/antifraud.sql). O
# reject_destination_alone veio depois; numa versao sem ele, ponha 101. Ate
# 17/10/2026 era rejeitar com 80 e 2 eixos: para relatar rodadas daquela
# epoca, volte reject para 80 e reject_min_axes para 2.
POLITICA_ATUAL = {"facial": 40, "facial_document": 60, "reject": 70, "reject_min_axis_points": 20, "reject_min_axes": 1,
                  "reject_destination_alone": 80}

# Quanto custa cada atrito num cliente honesto, em centavos. Sao valores de
# exemplo, para comparar politicas entre si: ajuste com o negocio. O golpe que
# passa custa o valor que escapou.
CUSTOS = {"facial": 300, "facial_document": 800, "rejected": 3000}

# reject_alone_axes: com um eixo forte so, quais eixos podem rejeitar sozinhos
# (sem a chave, todos). Movimentacao sozinha e o proprio dono mexendo no
# proprio dinheiro, e ai a selfie funciona; no destino, quem faz a selfie e a
# vitima enganada, e ela passa.
ALTERNATIVAS = [
    ("atual (rejeita com 70 e 1 eixo forte)", {}),
    ("antiga (rejeita com 80 e 2 eixos)", {"reject": 80, "reject_min_axes": 2}),
    ("rejeitar com 70 e 2 eixos", {"reject_min_axes": 2}),
    ("70 e 1 eixo, menos movimentacao sozinha", {"reject_alone_axes": ("destino", "acesso")}),
    ("70 e 1 eixo, so o destino sozinho", {"reject_alone_axes": ("destino",)}),
    ("rejeitar com 80 e 1 eixo forte", {"reject": 80}),
    ("rejeitar a partir de 60 e 1 eixo", {"reject": 60}),
    ("destino sozinho rejeita a partir de 60", {"reject_destination_alone": 60}),
    ("selfie a partir de 30", {"facial": 30}),
    ("selfie a partir de 50", {"facial": 50}),
]

PISOS = ("none", "facial", "facial_document")
ROTULOS = ("fraude", "legitimo", "autoprotecao")


def decidir(score, eixos: dict, piso: str, bloqueio: bool, politica: dict) -> str:
    """A mesma tabela do controllers/engine/decision.py da API."""
    if bloqueio:
        return "rejected"
    fortes = [eixo for eixo, total in eixos.items() if total >= politica["reject_min_axis_points"]]
    sozinhos = politica.get("reject_alone_axes")
    if score >= politica["reject"] and len(fortes) >= politica["reject_min_axes"]:
        if len(fortes) != 1 or sozinhos is None or fortes[0] in sozinhos:
            return "rejected"
    if eixos.get("destino", 0) >= politica.get("reject_destination_alone", 101):
        return "rejected"
    if score >= politica["facial_document"] or piso == "facial_document":
        return "facial_document"
    if score >= politica["facial"] or piso == "facial":
        return "facial"
    return "approved"


def _simulavel(r: dict) -> bool:
    return r["metodo"] == "POST" and r["rotulo"] in ROTULOS and r["pontos"] is not None and r["decisao"] in ORDEM


# ----------------------------------------------------------------------
# Somas e margem de erro
# ----------------------------------------------------------------------

def _somar(regs) -> dict:
    s = defaultdict(float)
    for r in regs:
        if r["metodo"] != "POST":
            continue
        if r["rotulo"] == "fraude":
            s["f_n"] += 1
            s["f_contido"] += r["contido"]
            s["f_valor"] += r["valor"]
            s["f_escapou"] += r["escapou"]
        elif r["rotulo"] == "legitimo":
            s["l_n"] += 1
            s["l_fp"] += r["falso_positivo"]
            s["l_fr"] += r["friccao_indevida"]
            s["l_custo"] += CUSTOS.get(r["decisao"], 0)
        elif r["rotulo"] == "autoprotecao":
            s["a_n"] += 1
            s["a_prot"] += r["protegido"]
            s["a_exc"] += r["excesso"]
    return s


def _razao(parte, todo):
    return parte / todo if todo else None


METRICAS = {
    "contencao": lambda s: _razao(s["f_contido"], s["f_n"]),
    "contencao_valor": lambda s: _razao(s["f_valor"] - s["f_escapou"], s["f_valor"]),
    "falso_positivo": lambda s: _razao(s["l_fp"], s["l_n"]),
    "friccao_indevida": lambda s: _razao(s["l_fr"], s["l_n"]),
    "protegido": lambda s: _razao(s["a_prot"], s["a_n"]),
}


def _quantil(valores: list, q: float):
    ordenados = sorted(valores)
    return ordenados[min(len(ordenados) - 1, int(q * len(ordenados)))]


def _reamostrar(grupos: list, sorteios: int, semente: int, medir) -> dict:
    acaso = random.Random(semente)
    amostras = defaultdict(list)
    for _ in range(sorteios):
        sorteados = [acaso.choice(grupos) for _ in grupos]
        for nome, valor in medir(sorteados).items():
            if valor is not None:
                amostras[nome].append(valor)
    return {nome: (_quantil(v, 0.025), _quantil(v, 0.975)) for nome, v in amostras.items() if len(v) >= sorteios // 2}


def intervalos(registros: list, sorteios: int = 500, semente: int = 0) -> dict:
    """{metrica: (minimo, maximo)} com 95% de confianca. Vazio com menos de 5 episodios."""
    grupos = [_somar(regs) for regs in avaliacao._por_episodio(registros).values()]
    if len(grupos) < 5:
        return {}

    def medir(sorteados):
        total = defaultdict(float)
        for grupo in sorteados:
            for chave, valor in grupo.items():
                total[chave] += valor
        return {nome: f(total) for nome, f in METRICAS.items()}

    return _reamostrar(grupos, sorteios, semente, medir)


# ----------------------------------------------------------------------
# Outra politica
# ----------------------------------------------------------------------

def simular(registros: list, mudancas: dict) -> list:
    politica = {**POLITICA_ATUAL, **mudancas}
    saida = []
    for r in registros:
        if _simulavel(r):
            novo = dict(r, decisao=decidir(r["pontos"], r.get("eixos") or {}, r.get("piso") or "none",
                                           r.get("bloqueio"), politica))
            avaliacao.classificar(novo)
            saida.append(novo)
        else:
            saida.append(r)
    return saida


def reproducao(registros: list):
    """Quanto da decisao real a tabela reproduz. Longe de 100% quer dizer que a politica mudou."""
    simulaveis = [r for r in registros if _simulavel(r)]
    iguais = sum(decidir(r["pontos"], r.get("eixos") or {}, r.get("piso") or "none", r.get("bloqueio"),
                         POLITICA_ATUAL) == r["decisao"] for r in simulaveis)
    return _razao(iguais, len(simulaveis))


def secao_politica(registros: list) -> list:
    if not any(_simulavel(r) for r in registros):
        return []
    pct, reais = avaliacao._pct, avaliacao._reais
    linhas = [
        "## E se a politica fosse outra?", "",
        f"A mesma rodada, com outros cortes de pontos. A tabela da API reproduz {pct(reproducao(registros))} das "
        "decisoes reais; a simulacao nao refaz o historico que a decisao nova mudaria. Custo estimado = golpe que "
        f"passou + {reais(CUSTOS['facial'])} por selfie, {reais(CUSTOS['facial_document'])} por documento e "
        f"{reais(CUSTOS['rejected'])} por bloqueio de cliente honesto (valores de exemplo, em analise.CUSTOS).", "",
        "| politica | golpe contido | R$ que escapou | falso positivo | friccao indevida | protegido | custo estimado |",
        "|---|---|---|---|---|---|---|",
    ]
    resultados = []
    for nome, mudancas in ALTERNATIVAS:
        s = _somar(simular(registros, mudancas))
        resultados.append((nome, s, s["f_escapou"] + s["l_custo"]))
    menor = min(custo for _, _, custo in resultados)
    for nome, s, custo in resultados:
        marca = " (menor)" if custo == menor else ""
        linhas.append(f"| {nome} | {pct(METRICAS['contencao'](s))} | {reais(s['f_escapou'])} "
                      f"| {pct(METRICAS['falso_positivo'](s))} | {pct(METRICAS['friccao_indevida'](s))} "
                      f"| {pct(METRICAS['protegido'](s))} | {reais(custo)}{marca} |")
    return linhas + [""]


# ----------------------------------------------------------------------
# Efeito de cada regra
# ----------------------------------------------------------------------

def efeito_das_regras(registros: list) -> dict:
    efeito = defaultdict(lambda: defaultdict(int))
    for r in registros:
        detalhes = r.get("regras_detalhadas") or []
        if not _simulavel(r) or not detalhes:
            continue
        for regra in detalhes:
            outras = [x for x in detalhes if x is not regra]
            eixos = dict(r.get("eixos") or {})
            if regra["eixo"] in eixos:
                eixos[regra["eixo"]] -= regra["pontos"]
            sem = decidir(max(0, min(100, r["pontos"] - regra["pontos"])), eixos,
                          max((x["piso"] for x in outras), key=PISOS.index, default="none"),
                          any(x["bloqueio"] for x in outras), POLITICA_ATUAL)
            decisiva = ORDEM[sem] < ORDEM[r["decisao"]]
            conta = efeito[regra["regra"]]
            conta[f"acendeu_{r['rotulo']}"] += 1
            if not decisiva:
                continue
            if r["rotulo"] == "fraude" and r["contido"]:
                conta["conteve"] += 1
            elif r["rotulo"] == "legitimo" and (r["falso_positivo"] or r["friccao_indevida"]):
                conta["atrapalhou"] += 1
            elif r["rotulo"] == "autoprotecao" and r["protegido"]:
                conta["protegeu"] += 1
    return efeito


def secao_regras(registros: list, limite: int = 15) -> list:
    efeito = efeito_das_regras(registros)
    if not efeito:
        return []
    linhas = [
        "## Efeito de cada regra", "",
        "Decisiva = sem os pontos (ou o piso, ou o bloqueio) desta regra, a decisao teria sido mais branda. "
        "Aproximado: tirar uma regra pode promover outra da mesma familia.", "",
        "| regra | acendeu em golpes | decisiva para conter golpe | acendeu em honestos | decisiva em atrito indevido "
        "| decisiva para proteger o cliente |",
        "|---|---|---|---|---|---|",
    ]
    ordem = sorted(efeito.items(), key=lambda item: (-item[1]["atrapalhou"], -item[1]["conteve"], item[0]))
    for regra, c in ordem[:limite]:
        linhas.append(f"| {regra} | {c['acendeu_fraude']} | {c['conteve']} | {c['acendeu_legitimo']} "
                      f"| {c['atrapalhou']} | {c['protegeu']} |")
    return linhas + [""]


# ----------------------------------------------------------------------
# A/B: os mesmos episodios contra outra versao
# ----------------------------------------------------------------------

def _resumo_decisoes(regs: list) -> str:
    alvos = [r["decisao"] for r in regs if r["metodo"] == "POST" and r["papel"] == "alvo"]
    contagem = defaultdict(int)
    for decisao in alvos:
        contagem[decisao] += 1
    return ", ".join(f"{d} {n}" for d, n in sorted(contagem.items()))


def comparar(regs_antes: list, metas_antes: dict, regs_depois: list, pares: list, limite: int = 10) -> list:
    """pares = [(episodio_antes, episodio_depois)]. Devolve as linhas do relatorio."""
    pct = avaliacao._pct
    antes = avaliacao._por_episodio(regs_antes)
    depois = avaliacao._por_episodio(regs_depois)
    pares = [(a, d) for a, d in pares if a in antes and d in depois]
    grupos = [(_somar(antes[a]), _somar(depois[d])) for a, d in pares]

    def total(lado):
        soma = defaultdict(float)
        for par in grupos:
            for chave, valor in par[lado].items():
                soma[chave] += valor
        return soma

    def medir(sorteados):
        a, d = defaultdict(float), defaultdict(float)
        for ga, gd in sorteados:
            for chave, valor in ga.items():
                a[chave] += valor
            for chave, valor in gd.items():
                d[chave] += valor
        saida = {}
        for nome, f in METRICAS.items():
            va, vd = f(a), f(d)
            saida[nome] = None if va is None or vd is None else vd - va
        return saida

    margem = _reamostrar(grupos, 500, 0, medir) if len(grupos) >= 5 else {}
    soma_antes, soma_depois = total(0), total(1)
    nomes = {"contencao": "golpe contido", "contencao_valor": "golpe contido em valor",
             "falso_positivo": "falso positivo", "friccao_indevida": "friccao indevida",
             "protegido": "cliente protegido de si mesmo"}
    linhas = ["| medida | antes | depois | diferenca | margem da diferenca (95%) |", "|---|---|---|---|---|"]
    for chave, nome in nomes.items():
        va, vd = METRICAS[chave](soma_antes), METRICAS[chave](soma_depois)
        if va is None or vd is None:
            continue
        faixa = margem.get(chave)
        texto_faixa = f"{100 * faixa[0]:+.1f} a {100 * faixa[1]:+.1f} pp".replace(".", ",") if faixa else "n/d"
        linhas.append(f"| {nome} | {pct(va)} | {pct(vd)} | {100 * (vd - va):+.1f} pp | {texto_faixa} |".replace(".", ","))

    mudancas = []
    for a, d in pares:
        tipo = metas_antes[a]["tipo"]
        fa, fd = avaliacao.falha_do_episodio(antes[a], tipo), avaliacao.falha_do_episodio(depois[d], tipo)
        if fa != fd:
            mudancas.append((fd - fa, metas_antes[a], fa, fd, _resumo_decisoes(antes[a]), _resumo_decisoes(depois[d])))
    pioraram = sorted((m for m in mudancas if m[0] > 0), key=lambda m: -m[0])
    melhoraram = sorted((m for m in mudancas if m[0] < 0), key=lambda m: m[0])
    linhas += ["", f"{len(pares)} episodios repetidos: {len(melhoraram)} melhoraram, {len(pioraram)} pioraram, "
               f"{len(pares) - len(mudancas)} iguais.", ""]
    for titulo, grupo in (("Pioraram", pioraram), ("Melhoraram", melhoraram)):
        if not grupo:
            continue
        linhas += [f"### {titulo}", "", "| perfil | botoes | falha antes | falha depois | decisoes antes | decisoes depois |",
                   "|---|---|---|---|---|---|"]
        for _, meta, fa, fd, da, dd in grupo[:limite]:
            botoes = ",".join(f"{k}={v}" for k, v in meta["botoes"].items())
            linhas.append(f"| {meta['perfil']} | {botoes} | {pct(fa)} | {pct(fd)} | {da} | {dd} |")
        linhas.append("")
    return linhas
