"""Dispara os episodios, julga cada resposta e escreve o relatorio.

A API e medida pelo resultado, nao pelo nome da regra:
  num golpe, "contido" e a decisao chegar ao contido_por da tipologia;
  num legitimo, falso positivo e rejeitar quem nao devia, e friccao
  indevida e pedir autenticacao alem do aceitavel_ate do perfil.
"""

import json
import statistics
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path

from laboratorio import api
from laboratorio.mundo import ORDEM

PASTA_RESULTADOS = Path(__file__).resolve().parents[1] / "resultados"
HISTORICO = PASTA_RESULTADOS / "historico.jsonl"


# ----------------------------------------------------------------------
# Execucao e julgamento
# ----------------------------------------------------------------------

def executar(cliente, episodios: list, aviso=None) -> list:
    """Manda os eventos em ordem de tempo e julga cada resposta.

    Quando a API pede selfie, quem esta com o aparelho responde como o
    evento manda (mundo.py): o titular confirma (approved_by_client), as vezes
    desiste; o golpista nao passa, e o titular de verdade as vezes contesta
    (reproved_by_client). So o Pix confirmado conta no historico da API.

    Com cliente.paralelo > 1, varios episodios andam ao mesmo tempo, cada um
    na sua ordem. Episodios nao dividem pessoas nem contas, entao a historia
    de cada um nao muda. O que muda e so a ordem entre episodios, que pesa
    apenas no que eles dividem de fato (os documentos do seed e a faixa de IP):
    para um A/B fino, rode a base e a comparacao do mesmo jeito.
    """
    if cliente.paralelo == 1 or len(episodios) == 1:
        eventos = sorted((ev for ep in episodios for ev in ep.eventos), key=lambda ev: ev.quando)
        registros = []
        for i, evento in enumerate(eventos, start=1):
            registros.append(_executar_evento(cliente, evento))
            if aviso and i % 250 == 0:
                aviso(f"  {i} de {len(eventos)} pedidos")
        return registros

    registros = []
    with ThreadPoolExecutor(max_workers=cliente.paralelo) as pool:
        # Os episodios mais longos primeiro: assim nenhum deles fica sozinho no fim.
        ordem = sorted(episodios, key=lambda ep: len(ep.eventos), reverse=True)
        tarefas = [pool.submit(_executar_episodio, cliente, ep) for ep in ordem]
        for feitos, tarefa in enumerate(as_completed(tarefas), start=1):
            registros.extend(tarefa.result())
            if aviso and feitos % 20 == 0:
                aviso(f"  {feitos} de {len(episodios)} episodios")
    return sorted(registros, key=lambda r: r["quando"])


def _executar_episodio(cliente, episodio) -> list:
    return [_executar_evento(cliente, evento) for evento in sorted(episodio.eventos, key=lambda ev: ev.quando)]


def _executar_evento(cliente, evento) -> dict:
    medir = evento.metodo == "POST" and evento.papel != "rotina" and cliente.conferir_get
    registro = julgar(evento, cliente.enviar(evento.metodo, evento.caminho, evento.corpo, evento.id if medir else None))
    acao = (evento.desafio or {}).get(registro["decisao"])
    registro["desafio"] = acao
    if acao in ("aprova", "contesta"):
        resultado = "approved_by_client" if acao == "aprova" else "reproved_by_client"
        aceito = cliente.responder_desafio(evento.id, evento.corpo["transaction_date"], resultado)
        registro["confirmado"] = aceito and acao == "aprova"
        if not aceito:
            registro["problemas"].append(f"PATCH {resultado} recusado")
    return registro


def _problemas(evento, resultado: dict, decisao: str) -> list:
    if resultado["falha"]:
        return [resultado["falha"]]
    if not 200 <= resultado["http"] < 300:
        return [f"HTTP {resultado['http']}: {resultado.get('erro') or ''}".strip()]
    if evento.metodo != "POST":
        return []
    corpo = resultado["corpo"]
    problemas = []
    atual, bruto = api.status(corpo), api.nivel_bruto(corpo)
    if atual not in api.STATUS:
        problemas.append(f"status fora do contrato: {atual!r}")
    if atual == "two_factor_required" and bruto not in api.NIVEIS:
        problemas.append(f"2FA sem nivel valido: {bruto!r}")
    if atual in ("approved", "rejected") and bruto not in (None, "none"):
        problemas.append(f"{atual} com nivel {bruto!r}")
    if resultado["consulta"] is not None and resultado["consulta"] != decisao:
        problemas.append(f"GET devolveu {resultado['consulta']}, POST devolveu {decisao}")
    return problemas


def julgar(evento, resultado: dict) -> dict:
    ok = resultado["http"] is not None and 200 <= resultado["http"] < 300
    if evento.metodo == "POST":
        decisao = api.decisao(resultado["corpo"]) if ok else "erro"
    else:
        decisao = "registrado" if ok else "erro"
    registro = {
        "id": evento.id, "episodio": evento.episodio, "perfil": evento.perfil, "metodo": evento.metodo,
        "rotulo": evento.rotulo, "papel": evento.papel, "valor": evento.valor, "quando": evento.quando.isoformat(),
        "contido_por": evento.contido_por, "aceitavel_ate": evento.aceitavel_ate, "regulatorio": evento.regulatorio,
        "decisao": decisao, "pontos": api.pontos(resultado["corpo"]), "regras": api.regras(resultado["corpo"]),
        "eixos": api.eixos(resultado["corpo"]), "piso": api.piso(resultado["corpo"]),
        "bloqueio": api.bloqueio(resultado["corpo"]), "regras_detalhadas": api.regras_detalhadas(resultado["corpo"]),
        "latencia": resultado["latencia"], "problemas": _problemas(evento, resultado, decisao),
        "bcb_violado": bool(evento.regulatorio) and decisao == "approved",
        "confirmado": False, "desafio": None,
    }
    return classificar(registro)


def classificar(registro: dict) -> dict:
    """Marca acerto e erro a partir da decisao. Separado do julgar para a simulacao de politica reusar."""
    decisao = registro["decisao"]
    decidiu = decisao in ORDEM
    teto = "rejected" if registro["regulatorio"] else registro["aceitavel_ate"]
    if registro["metodo"] != "POST":
        return registro
    if registro["rotulo"] == "fraude":
        contido = decidiu and ORDEM[decisao] >= ORDEM[registro["contido_por"]]
        registro.update(detectado=decidiu and decisao != "approved", contido=contido,
                        escapou=0 if contido else registro["valor"])
    elif registro["rotulo"] == "autoprotecao":
        protegido = decidiu and ORDEM[decisao] >= ORDEM[registro["contido_por"]]
        registro.update(protegido=protegido, excesso=decidiu and ORDEM[decisao] > ORDEM[teto],
                        exposto=0 if protegido else registro["valor"])
    elif registro["rotulo"] == "legitimo":
        registro.update(alerta=decidiu and decisao != "approved",
                        falso_positivo=decisao == "rejected" and teto != "rejected",
                        friccao_indevida=decisao in api.NIVEIS and ORDEM[decisao] > ORDEM[teto])
    return registro


# ----------------------------------------------------------------------
# Medidas
# ----------------------------------------------------------------------

def _taxa(parte, todo):
    return parte / todo if todo else None


def _percentil(valores: list, p: int):
    if not valores:
        return None
    if len(valores) == 1:
        return valores[0]
    return statistics.quantiles(valores, n=100, method="inclusive")[p - 1]


def _precisao(sensibilidade, taxa_alarme, base):
    """Quantos alertas seriam fraude se a fraude fosse `base` do trafego."""
    if sensibilidade is None or taxa_alarme is None:
        return None
    verdadeiros, falsos = sensibilidade * base, taxa_alarme * (1 - base)
    return verdadeiros / (verdadeiros + falsos) if verdadeiros + falsos else None


def resumir(registros: list) -> dict:
    pix = [r for r in registros if r["metodo"] == "POST"]
    fraudes = [r for r in pix if r["rotulo"] == "fraude"]
    legitimos = [r for r in pix if r["rotulo"] == "legitimo"]
    alvos = [r for r in legitimos if r["papel"] == "alvo"]
    valor_fraude = sum(r["valor"] for r in fraudes)
    escapou = sum(r["escapou"] for r in fraudes)
    deteccao = _taxa(sum(r["detectado"] for r in fraudes), len(fraudes))
    alarme = _taxa(sum(r["alerta"] for r in legitimos), len(legitimos))
    protecao = [r for r in pix if r["rotulo"] == "autoprotecao"]
    latencias = [r["latencia"] for r in registros]
    return {
        "autoprotecao": len(protecao),
        "protegido": _taxa(sum(r["protegido"] for r in protecao), len(protecao)),
        "protecao_em_excesso": _taxa(sum(r["excesso"] for r in protecao), len(protecao)),
        "valor_exposto": sum(r["exposto"] for r in protecao),
        "pedidos": len(registros), "fraudes": len(fraudes), "legitimos": len(legitimos), "legitimos_alvo": len(alvos),
        "contencao": _taxa(sum(r["contido"] for r in fraudes), len(fraudes)),
        "contencao_valor": _taxa(valor_fraude - escapou, valor_fraude),
        "deteccao": deteccao, "valor_fraude": valor_fraude, "valor_escapou": escapou,
        "falso_positivo": _taxa(sum(r["falso_positivo"] for r in legitimos), len(legitimos)),
        "falso_positivo_alvo": _taxa(sum(r["falso_positivo"] for r in alvos), len(alvos)),
        "friccao_indevida": _taxa(sum(r["friccao_indevida"] for r in legitimos), len(legitimos)),
        "valor_legitimo_barrado": sum(r["valor"] for r in legitimos if r["falso_positivo"]),
        "precisao_base_0_1": _precisao(deteccao, alarme, 0.001),
        "precisao_base_1": _precisao(deteccao, alarme, 0.01),
        "p50": _percentil(latencias, 50), "p95": _percentil(latencias, 95), "p99": _percentil(latencias, 99),
        "fora_do_contrato": sum(1 for r in registros if r["problemas"]),
        "desistencias": sum(1 for r in pix if r["rotulo"] in ("legitimo", "autoprotecao") and r.get("desafio") == "nada"),
        "desafios_honestos": sum(1 for r in pix if r["rotulo"] in ("legitimo", "autoprotecao") and r["decisao"] in api.NIVEIS),
        "contestacoes": sum(1 for r in pix if r.get("desafio") == "contesta"),
        "violacoes_bcb": sum(1 for r in pix if r["bcb_violado"]),
    }


def falha_geral(registros: list) -> bool:
    """Ha qualquer erro de julgamento, de contrato ou de regra do BCB?"""
    for r in registros:
        if r["problemas"] or r["bcb_violado"]:
            return True
        if r["metodo"] == "POST" and r["rotulo"] == "fraude" and not r["contido"]:
            return True
        if r["metodo"] == "POST" and r["rotulo"] == "legitimo" and (r["falso_positivo"] or r["friccao_indevida"]):
            return True
        if r["metodo"] == "POST" and r["rotulo"] == "autoprotecao" and (not r["protegido"] or r["excesso"]):
            return True
    return False


def piores_tipologias(registros: list, quantidade: int) -> list:
    escapou = Counter()
    for r in registros:
        if r["metodo"] == "POST" and r["rotulo"] == "fraude" and r["escapou"]:
            escapou[r["perfil"]] += r["escapou"]
    return [nome for nome, _ in escapou.most_common(quantidade)]


def falha_do_episodio(registros: list, tipo: str) -> float:
    """0 e acerto total, 1 e erro total.

    Num legitimo, friccao indevida pesa 1/4 de um falso positivo. Na
    autoprotecao, deixar sem protecao pesa 1 e proteger demais pesa 1/2.
    """
    if tipo == "autoprotecao":
        eventos = [r for r in registros if r["metodo"] == "POST" and r["rotulo"] == "autoprotecao"]
        if not eventos:
            return 0.0
        return sum(0.0 if r["protegido"] and not r["excesso"] else 0.5 if r["protegido"] else 1.0
                   for r in eventos) / len(eventos)
    if tipo == "fraude":
        fraudes = [r for r in registros if r["metodo"] == "POST" and r["rotulo"] == "fraude"]
        total = sum(r["valor"] for r in fraudes)
        return sum(r["escapou"] for r in fraudes) / total if total else 0.0
    alvos = [r for r in registros if r["metodo"] == "POST" and r["rotulo"] == "legitimo" and r["papel"] == "alvo"]
    if not alvos:
        return 0.0
    return sum(1.0 if r["falso_positivo"] else 0.25 if r["friccao_indevida"] else 0.0 for r in alvos) / len(alvos)


def _por_episodio(registros: list) -> dict:
    grupos = {}
    for r in registros:
        grupos.setdefault(r["episodio"], []).append(r)
    return grupos


def por_botao(registros: list, metas: dict, nome: str) -> list:
    """Falha media por opcao de botao, da pior para a melhor: (botao, opcao, falha, episodios)."""
    baldes = {}
    for ep_id, regs in _por_episodio(registros).items():
        meta = metas.get(ep_id)
        if not meta or meta["perfil"] != nome:
            continue
        if not any(r["metodo"] == "POST" and r["rotulo"] == meta["tipo"] and r["papel"] == "alvo" for r in regs):
            continue  # ex.: o controle legitimo dentro de uma tipologia de golpe
        falha = falha_do_episodio(regs, meta["tipo"])
        for botao, opcao in meta["botoes"].items():
            baldes.setdefault((botao, str(opcao)), []).append(falha)
    linhas = [(b, o, sum(v) / len(v), len(v)) for (b, o), v in baldes.items()]
    return sorted(linhas, key=lambda linha: (-linha[2], -linha[3]))


def contrastes(registros: list, metas: dict, nome: str) -> list:
    """Botoes que mudam o resultado: (botao, pior opcao, falha, melhor opcao, falha), do maior contraste ao menor."""
    por_nome = {}
    for botao, opcao, falha, _ in por_botao(registros, metas, nome):
        por_nome.setdefault(botao, []).append((falha, opcao))
    saida = []
    for botao, opcoes in por_nome.items():
        pior, melhor = max(opcoes), min(opcoes)
        if pior[0] > melhor[0]:
            saida.append((botao, pior[1], pior[0], melhor[1], melhor[0]))
    return sorted(saida, key=lambda c: c[4] - c[2])


def descreve_botoes(registros: list, metas: dict, nome: str, quantos: int = 2) -> str:
    achados = contrastes(registros, metas, nome)
    if achados:
        return "; ".join(f"{b}={p} ({_pct(fp)}) contra {b}={m} ({_pct(fm)})" for b, p, fp, m, fm in achados[:quantos])
    if any(falha > 0 for _, _, falha, _ in por_botao(registros, metas, nome)):
        return "qualquer combinacao sorteada"
    return ""


def pior_episodio(registros: list, metas: dict, nome: str):
    pior, pior_falha = None, -1.0
    for ep_id, regs in _por_episodio(registros).items():
        meta = metas.get(ep_id)
        if meta and meta["perfil"] == nome:
            falha = falha_do_episodio(regs, meta["tipo"])
            if falha > pior_falha:
                pior, pior_falha = meta, falha
    return pior, pior_falha


# ----------------------------------------------------------------------
# Relatorio
# ----------------------------------------------------------------------

def _pct(valor) -> str:
    return "n/d" if valor is None else f"{100 * valor:.1f}%".replace(".", ",")


def _reais(centavos) -> str:
    inteiro, resto = divmod(int(centavos), 100)
    return f"R$ {inteiro:,}".replace(",", ".") + f",{resto:02d}"


def _ms(valor) -> str:
    return "n/d" if valor is None else f"{valor:.0f} ms"


def comando_repetir(meta: dict) -> str:
    botoes = ",".join(f"{k}={v}" for k, v in meta["botoes"].items())
    return (f'python tools/laboratorio_antifraude.py repetir --perfil {meta["perfil"]} '
            f'--semente {meta["semente"]} --botoes "{botoes}"')


def _placar(resumo: dict, anterior: dict, margem: dict = None) -> list:
    margem = margem or {}

    def delta(chave):
        texto = ""
        if chave in margem:
            minimo, maximo = margem[chave]
            texto += f" [{_pct(minimo)} a {_pct(maximo)}]"
        if anterior and anterior.get(chave) is not None and resumo.get(chave) is not None:
            diferenca = 100 * (resumo[chave] - anterior[chave])
            texto += f" ({'+' if diferenca >= 0 else ''}{diferenca:.1f} pp)".replace(".", ",")
        return texto

    linhas = [
        "## Placar", "",
        "| medida | valor | leitura |", "|---|---|---|",
        f"| golpe contido | {_pct(resumo['contencao'])}{delta('contencao')} | barrado no nivel que de fato segura o golpe |",
        f"| golpe contido em valor | {_pct(resumo['contencao_valor'])}{delta('contencao_valor')} "
        f"| {_reais(resumo['valor_escapou'])} escaparam de {_reais(resumo['valor_fraude'])} |",
        f"| golpe detectado | {_pct(resumo['deteccao'])}{delta('deteccao')} | qualquer atrito, mesmo o que a vitima enganada atravessa |",
        f"| falso positivo | {_pct(resumo['falso_positivo'])}{delta('falso_positivo')} "
        f"| legitimo rejeitado; {_reais(resumo['valor_legitimo_barrado'])} barrados |",
        f"| friccao indevida | {_pct(resumo['friccao_indevida'])}{delta('friccao_indevida')} | autenticacao alem do razoavel |",
        f"| cliente protegido de si mesmo | {_pct(resumo['protegido'])}{delta('protegido')} "
        f"| pausa ou limite quando o padrao fica perigoso; em excesso: {_pct(resumo['protecao_em_excesso'])} |",
        f"| precisao com 0,1% / 1% de fraude | {_pct(resumo['precisao_base_0_1'])} / {_pct(resumo['precisao_base_1'])} "
        "| quantos alertas seriam fraude num trafego real |",
        f"| latencia p50 / p95 / p99 | {_ms(resumo['p50'])} / {_ms(resumo['p95'])} / {_ms(resumo['p99'])} | |",
        f"| pedidos fora do contrato | {resumo['fora_do_contrato']} | HTTP, status, nivel ou GET divergente |",
        f"| aprovados contra regra do BCB | {resumo['violacoes_bcb']} | limite noturno ou aparelho novo |",
        f"| honestos que desistiram na selfie | {resumo['desistencias']} de {resumo['desafios_honestos']} desafios "
        "| cada desistencia e um Pix que nao saiu e um cliente irritado |",
        f"| contestacoes \"nao fui eu\" | {resumo['contestacoes']} | o titular avisado de um desafio que ele nao pediu |",
        "",
        "Entre colchetes, a margem de erro com 95% de confianca (reamostrando os episodios). Para estreitar, "
        "aumente --por-perfil.",
        "",
    ]
    if not resumo["fraudes"]:
        linhas = [linha for linha in linhas if "golpe" not in linha and "precisao" not in linha]
    if not resumo["autoprotecao"]:
        linhas = [linha for linha in linhas if "protegido de si mesmo" not in linha]
    return linhas


def _tabela_fraudes(registros, metas, catalogo) -> list:
    linhas = ["## Golpes por tipologia", "",
              "| tipologia | episodios | Pix | detectado | contido | escapou | escapa mais com |", "|---|---|---|---|---|---|---|"]
    dados = []
    for nome, perfil in catalogo.items():
        regs = [r for r in registros if r["perfil"] == nome and r["metodo"] == "POST" and r["rotulo"] == "fraude"]
        if perfil.tipo != "fraude" or not regs:
            continue
        pior = descreve_botoes(registros, metas, nome, 1)
        contido = _taxa(sum(r["contido"] for r in regs), len(regs))
        dados.append((contido, nome, len({r["episodio"] for r in regs}), len(regs),
                      _taxa(sum(r["detectado"] for r in regs), len(regs)), sum(r["escapou"] for r in regs), pior))
    if not dados:
        return []
    for contido, nome, episodios, n, detectado, escapou, pior in sorted(dados):
        linhas.append(f"| {nome} | {episodios} | {n} | {_pct(detectado)} | {_pct(contido)} | {_reais(escapou)} | {pior} |")
    return linhas + [""]


def _tabela_legitimos(registros, metas, catalogo) -> list:
    linhas = ["## Clientes legitimos por perfil", "",
              "| perfil | Pix alvo | aprovado | friccao indevida | falso positivo | erra mais com |", "|---|---|---|---|---|---|"]
    dados = []
    for nome, perfil in catalogo.items():
        regs = [r for r in registros if r["perfil"] == nome and r["metodo"] == "POST"
                and r["rotulo"] == "legitimo" and r["papel"] == "alvo"]
        if perfil.tipo != "legitimo" or not regs:
            continue
        pior = descreve_botoes(registros, metas, nome, 1)
        fp = _taxa(sum(r["falso_positivo"] for r in regs), len(regs))
        dados.append((-(fp or 0), nome, len(regs), _taxa(sum(r["decisao"] == "approved" for r in regs), len(regs)),
                      _taxa(sum(r["friccao_indevida"] for r in regs), len(regs)), fp, pior))
    rotina = [r for r in registros if r["metodo"] == "POST" and r["papel"] == "rotina"]
    for _, nome, n, aprovado, friccao, fp, pior in sorted(dados):
        linhas.append(f"| {nome} | {n} | {_pct(aprovado)} | {_pct(friccao)} | {_pct(fp)} | {pior} |")
    if rotina:
        linhas.append(f"| historico (todos os perfis) | {len(rotina)} "
                      f"| {_pct(_taxa(sum(r['decisao'] == 'approved' for r in rotina), len(rotina)))} "
                      f"| {_pct(_taxa(sum(r['friccao_indevida'] for r in rotina), len(rotina)))} "
                      f"| {_pct(_taxa(sum(r['falso_positivo'] for r in rotina), len(rotina)))} | |")
    return linhas + [""]


def _tabela_protecao(registros, metas, catalogo) -> list:
    linhas = ["## Protecao do cliente contra ele mesmo", "",
              "Ninguem engana nem invade: o proprio titular decide algo que pode machucar. Protegido e a API fazer uma "
              "pausa (selfie) ou segurar o limite que o cliente escolheu; excesso e barrar alem disso.", "",
              "| perfil | Pix que pediam protecao | protegido | em excesso | R$ sem protecao | falha mais com |",
              "|---|---|---|---|---|---|"]
    achou = False
    for nome, perfil in catalogo.items():
        regs = [r for r in registros if r["perfil"] == nome and r["metodo"] == "POST" and r["rotulo"] == "autoprotecao"]
        if perfil.tipo != "autoprotecao" or not regs:
            continue
        achou = True
        desprotegidos = [r for r in regs if not r["protegido"]]
        linhas.append(f"| {nome} | {len(regs)} | {_pct(_taxa(len(regs) - len(desprotegidos), len(regs)))} "
                      f"| {_pct(_taxa(sum(r['excesso'] for r in regs), len(regs)))} "
                      f"| {_reais(sum(r['exposto'] for r in regs))} | {descreve_botoes(registros, metas, nome, 1)} |")
    if not achou:
        return []
    for nome, perfil in catalogo.items():
        desprotegidos = [r for r in registros if r["perfil"] == nome and r["metodo"] == "POST"
                         and r["rotulo"] == "autoprotecao" and not r["protegido"]]
        if perfil.tipo != "autoprotecao" or not desprotegidos:
            continue
        pior, _ = pior_episodio(registros, metas, nome)
        linhas += ["", f"### {nome}", "", perfil.descricao + ".", "",
                   f"- Sinais no payload: {', '.join(perfil.sinais)}",
                   f"- Regras que a API acionou nos Pix sem protecao: {_regras_em(desprotegidos)}",
                   f"- Sinais que o contrato nao carrega: {', '.join(perfil.ausente_no_contrato) or 'nenhum'}",
                   f"- O que ajudaria: {perfil.defesa}"]
        if pior:
            linhas.append(f"- Repetir: `{comando_repetir(pior)}`")
    return linhas + [""]


def _regras_em(regs: list) -> str:
    contagem = Counter(regra for r in regs for regra in (r["regras"] or ["nenhuma"]))
    return ", ".join(f"{regra} ({n})" for regra, n in contagem.most_common(6)) or "nenhuma"


def _o_que_falta(registros, metas, catalogo, limite: int = 6) -> list:
    escapes = []
    for nome, perfil in catalogo.items():
        regs = [r for r in registros if r["perfil"] == nome and r["metodo"] == "POST" and r["rotulo"] == "fraude"]
        escapou = sum(r["escapou"] for r in regs)
        if perfil.tipo == "fraude" and escapou:
            escapes.append((escapou, nome, regs))
    if not escapes:
        if not any(r["rotulo"] == "fraude" for r in registros):
            return []
        return ["## O que falta", "", "Nenhum golpe escapou nesta rodada. Rode o cacador para procurar os que escapam.", ""]
    linhas = ["## O que falta, do golpe que mais escapou para o que menos", ""]
    for escapou, nome, regs in sorted(escapes, reverse=True)[:limite]:
        perfil = catalogo[nome]
        contido = _taxa(sum(r["contido"] for r in regs), len(regs))
        botoes = descreve_botoes(registros, metas, nome, 3)
        pior, _ = pior_episodio(registros, metas, nome)
        linhas += [
            f"### {nome}: {_pct(contido)} contido, {_reais(escapou)} escaparam", "",
            perfil.descricao + ".", "",
            f"- Escapa mais com: {botoes or 'sem padrao claro de botao'}",
            f"- Sinais que o golpe deixa no payload: {', '.join(perfil.sinais)}",
            f"- Regras que a API acionou nos Pix que escaparam: {_regras_em([r for r in regs if not r['contido']])}",
            f"- Precisa ser barrado em: {perfil.contido_por} ou acima",
        ]
        if perfil.ausente_no_contrato:
            linhas.append(f"- Sinais que o contrato atual nao carrega: {', '.join(perfil.ausente_no_contrato)}")
        linhas += [f"- Defesa conhecida: {perfil.defesa}", f"- Fonte: {perfil.fonte}"]
        if pior:
            linhas.append(f"- Repetir o pior episodio: `{comando_repetir(pior)}`")
        linhas.append("")
    return linhas


def _onde_barra_demais(registros, metas, catalogo) -> list:
    linhas = ["## Onde a API barra quem nao devia", ""]
    for nome, perfil in catalogo.items():
        regs = [r for r in registros if r["perfil"] == nome and r["metodo"] == "POST" and r["papel"] == "alvo"
                and r["rotulo"] == "legitimo" and (r["falso_positivo"] or r["friccao_indevida"])]
        if perfil.tipo != "legitimo" or not regs:
            continue
        fps = sum(1 for r in regs if r["falso_positivo"])
        linhas.append(f"- **{nome}**: {fps} rejeitados e {len(regs) - fps} com friccao indevida. "
                      f"Erra mais com: {descreve_botoes(registros, metas, nome) or 'o historico do cliente'}. "
                      f"Regras que acenderam: {_regras_em(regs)}")
    historico = [r for r in registros if r["metodo"] == "POST" and r["papel"] == "rotina"
                 and (r["falso_positivo"] or r["friccao_indevida"])]
    if historico:
        linhas.append(f"- **historico comum** (compras de rotina de todos os perfis, inclusive das vitimas): "
                      f"{len(historico)} Pix com atrito. Regras que acenderam: {_regras_em(historico)}")
    if len(linhas) == 2:
        linhas.append("Nenhum cliente legitimo foi barrado alem do aceitavel nesta rodada.")
    return linhas + [""]


def _fora_do_contrato(registros) -> list:
    problemas = [r for r in registros if r["problemas"] or r["bcb_violado"]]
    if not problemas:
        return []
    linhas = ["## Fora do contrato ou da regra do BCB", "", "| perfil | id | problema |", "|---|---|---|"]
    for r in problemas[:15]:
        motivo = "; ".join(r["problemas"] + ([f"aprovou contra regra do BCB: {r['regulatorio']}"] if r["bcb_violado"] else []))
        linhas.append(f"| {r['perfil']} | {r['id']} | {motivo} |")
    if len(problemas) > 15:
        linhas.append(f"| ... | | mais {len(problemas) - 15} pedidos |")
    return linhas + [""]


def relatorio(registros: list, metas: dict, catalogo: dict, cabecalho: list, anterior: dict = None) -> str:
    from laboratorio import analise  # aqui dentro: analise tambem importa este modulo

    resumo = resumir(registros)
    partes = cabecalho + [""] + _placar(resumo, anterior, analise.intervalos(registros))
    partes += _tabela_fraudes(registros, metas, catalogo)
    partes += _tabela_legitimos(registros, metas, catalogo)
    partes += _tabela_protecao(registros, metas, catalogo)
    partes += _o_que_falta(registros, metas, catalogo)
    partes += _onde_barra_demais(registros, metas, catalogo)
    partes += analise.secao_politica(registros)
    partes += analise.secao_regras(registros)
    partes += _fora_do_contrato(registros)
    return "\n".join(partes)


# ----------------------------------------------------------------------
# Arquivos
# ----------------------------------------------------------------------

def carregar_rodada(base: str) -> dict:
    """Uma rodada salva: pela tag, ou "ultima" para a mais recente."""
    if base == "ultima":
        salvas = sorted(PASTA_RESULTADOS.glob("rodada-*.json"), key=lambda p: p.stat().st_mtime)
        if not salvas:
            raise SystemExit("Nenhuma rodada salva em tools/resultados. Rode antes: python tools/laboratorio_antifraude.py rodada")
        arquivo = salvas[-1]
    else:
        arquivo = PASTA_RESULTADOS / f"rodada-{base}.json"
        if not arquivo.exists():
            raise SystemExit(f"Nao achei {arquivo}")
    return json.loads(arquivo.read_text(encoding="utf-8"))


def ultima_rodada(perfis: list = None) -> dict:
    """O resumo da ultima rodada com os mesmos perfis, para o placar mostrar a evolucao."""
    if not HISTORICO.exists():
        return None
    rodadas = [json.loads(linha) for linha in HISTORICO.read_text(encoding="utf-8").splitlines() if linha.strip()]
    rodadas = [r for r in rodadas if r["modo"] == "rodada" and (perfis is None or r.get("perfis") == perfis)]
    return rodadas[-1]["resumo"] if rodadas else None


def guardar(tag: str, modo: str, semente, registros: list, metas: dict, texto: str, dia: str = None) -> Path:
    PASTA_RESULTADOS.mkdir(exist_ok=True)
    resumo = resumir(registros)
    with HISTORICO.open("a", encoding="utf-8") as arquivo:
        arquivo.write(json.dumps({"tag": tag, "modo": modo, "semente": semente,
                                  "em": datetime.now().isoformat(timespec="seconds"),
                                  "perfis": sorted({m["perfil"] for m in metas.values()}), "resumo": resumo}) + "\n")
    destino = PASTA_RESULTADOS / f"{modo}-{tag}.json"
    destino.write_text(json.dumps({"tag": tag, "semente": semente, "data": dia, "metas": metas, "registros": registros},
                                  ensure_ascii=False, indent=1), encoding="utf-8")
    (PASTA_RESULTADOS / f"{modo}-{tag}.md").write_text(texto + "\n", encoding="utf-8")
    return destino
