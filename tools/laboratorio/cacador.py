"""Cacador de burlas, corpus de regressao e testes metamorficos.

O cacador faz o papel do golpista que aprende: parte da versao ingenua de
um golpe e muda um botao por vez, ficando com a mudanca que mais afrouxa a
decisao da API (usa o score da resposta, quando houver, como desempate).
Para no primeiro golpe que escapa ou quando acaba o orcamento. Com perfis
legitimos faz o inverso: procura o cliente honesto que a API barra.

Tudo o que escapa vai para tools/corpus_antifraude.json. O corpus e a
memoria do projeto: a regressao repete cada achado com identidades novas e
marca se ja foi resolvido, continua aberto ou voltou a falhar.
"""

import json
import random
from datetime import datetime
from pathlib import Path

from laboratorio import avaliacao
from laboratorio.catalogo import chave_botoes, construir, todos
from laboratorio.mundo import ORDEM

CORPUS = Path(__file__).resolve().parents[1] / "corpus_antifraude.json"


# ----------------------------------------------------------------------
# Corpus
# ----------------------------------------------------------------------

def ler_corpus() -> list:
    if not CORPUS.exists():
        return []
    return json.loads(CORPUS.read_text(encoding="utf-8"))


def gravar_corpus(corpus: list):
    CORPUS.write_text(json.dumps(corpus, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _resumo_decisoes(regs: list) -> str:
    alvos = [r for r in regs if r["metodo"] == "POST" and r["papel"] == "alvo"]
    contagem = {}
    for r in alvos:
        contagem[r["decisao"]] = contagem.get(r["decisao"], 0) + 1
    return ", ".join(f"{d} {n}" for d, n in sorted(contagem.items()))


def vale_guardar(corpus: list, meta: dict, regs: list, por_perfil: int = 8) -> bool:
    """A rodada so guarda o que ensina: golpe que escapou pela metade ou mais, ou legitimo rejeitado.

    E no maximo por_perfil achados abertos de cada perfil, para o corpus nao virar a rodada inteira.
    """
    abertos = sum(1 for item in corpus if item["perfil"] == meta["perfil"] and item["situacao"] != "resolvida")
    if abertos >= por_perfil:
        return False
    if meta["tipo"] in ("fraude", "autoprotecao"):
        return avaliacao.falha_do_episodio(regs, meta["tipo"]) >= 0.5
    return any(r.get("falso_positivo") for r in regs if r["papel"] == "alvo")


def registrar(corpus: list, meta: dict, regs: list, tag: str, origem: str, nota: str = "") -> bool:
    """Guarda o episodio que falhou. Devolve True se a combinacao era nova."""
    falha = avaliacao.falha_do_episodio(regs, meta["tipo"])
    if falha <= 0:
        return False
    chave = f"{meta['perfil']}|{chave_botoes(meta['botoes'])}"
    agora = datetime.now().isoformat(timespec="seconds")
    resultado = {"em": agora, "tag": tag, "falha": round(falha, 3), "decisoes": _resumo_decisoes(regs)}
    for item in corpus:
        if item["chave"] == chave:
            if item["situacao"] != "aberta":
                item["situacao"] = "reaberta"
            item["verificacoes"] = (item["verificacoes"] + [resultado])[-10:]
            return False
    corpus.append({
        "chave": chave, "perfil": meta["perfil"], "tipo": meta["tipo"], "botoes": meta["botoes"],
        "semente": meta["semente"], "origem": origem, "nota": nota, "achado_em": agora, "situacao": "aberta",
        "regras_acionadas": sorted({regra for r in regs for regra in r["regras"]}),
        "verificacoes": [resultado],
    })
    return True


def regressao(cliente, mundo, aviso) -> tuple:
    """Repete todo o corpus. Devolve (registros, metas, mudancas)."""
    corpus = ler_corpus()
    catalogo = todos()
    episodios, metas = [], {}
    for item in corpus:
        perfil = catalogo.get(item["perfil"])
        if perfil is None:
            continue
        episodio = construir(mundo, perfil, item["botoes"], item["semente"])
        episodios.append((item, episodio))
        metas[episodio.id] = meta_de(episodio)
    registros = avaliacao.executar(cliente, [e for _, e in episodios], aviso)
    por_episodio = {}
    for r in registros:
        por_episodio.setdefault(r["episodio"], []).append(r)
    mudancas = {"resolvidas": 0, "abertas": 0, "reabertas": 0}
    agora = datetime.now().isoformat(timespec="seconds")
    for item, episodio in episodios:
        regs = por_episodio.get(episodio.id, [])
        falha = avaliacao.falha_do_episodio(regs, item["tipo"])
        if falha > 0:
            item["situacao"] = "reaberta" if item["situacao"] == "resolvida" else "aberta"
        else:
            item["situacao"] = "resolvida"
        mudancas[{"resolvida": "resolvidas", "aberta": "abertas", "reaberta": "reabertas"}[item["situacao"]]] += 1
        item["verificacoes"] = (item["verificacoes"] + [{"em": agora, "tag": mundo.tag, "falha": round(falha, 3),
                                                         "decisoes": _resumo_decisoes(regs)}])[-10:]
    gravar_corpus(corpus)
    return registros, metas, mudancas


def meta_de(episodio) -> dict:
    return {"perfil": episodio.perfil.nome, "tipo": episodio.perfil.tipo, "botoes": episodio.botoes,
            "semente": episodio.semente}


# ----------------------------------------------------------------------
# Cacada
# ----------------------------------------------------------------------

def _objetivo(regs: list, tipo: str) -> tuple:
    """Quanto maior, melhor para quem quer enganar a API."""
    rotulo = tipo if tipo in ("fraude", "autoprotecao") else "legitimo"
    alvos = [r for r in regs if r["metodo"] == "POST" and r["rotulo"] == rotulo and r["papel"] == "alvo"]
    if not alvos:
        return (0.0, 0.0, 0.0)
    severidade = sum(ORDEM.get(r["decisao"], 0) for r in alvos) / len(alvos)
    com_pontos = [r["pontos"] for r in alvos if r["pontos"] is not None]
    pontos = sum(com_pontos) / len(com_pontos) if com_pontos else 0.0
    falha = avaliacao.falha_do_episodio(regs, tipo)
    if tipo in ("fraude", "autoprotecao"):
        return (falha, -severidade, -pontos)
    return (falha, severidade, pontos)


def cacar(cliente, mundo, perfil, orcamento: int, semente: int, aviso) -> list:
    """Busca gulosa por botoes, com reinicio aleatorio. Devolve [(objetivo, meta, registros)]."""
    acaso = random.Random(semente)
    provados = {}

    def provar(botoes):
        chave = chave_botoes(botoes)
        if chave not in provados:
            episodio = construir(mundo, perfil, botoes, semente)
            regs = avaliacao.executar(cliente, [episodio])
            provados[chave] = (_objetivo(regs, perfil.tipo), meta_de(episodio), regs)
        return provados[chave][0]

    atual = perfil.botoes_ingenuos()
    nota_atual = melhor = provar(atual)
    while len(provados) < orcamento and melhor[0] < 1.0:
        candidatos = [b for b in perfil.vizinhos(atual) if chave_botoes(b) not in provados]
        acaso.shuffle(candidatos)
        avaliados = []
        for botoes in candidatos:
            if len(provados) >= orcamento:
                break
            avaliados.append((provar(botoes), botoes))
        if avaliados:
            nota, botoes = max(avaliados, key=lambda a: a[0])
            if nota > nota_atual:
                atual, nota_atual = botoes, nota
                if nota > melhor:
                    melhor = nota
                    aviso(f"    {perfil.nome}: falha {nota[0]:.0%} com {chave_botoes(botoes)}")
                continue
        if len(provados) >= min(orcamento, _combinacoes(perfil)):
            break
        # Otimo local: recomeca de um ponto sorteado.
        atual = perfil.botoes_aleatorios(acaso)
        nota_atual = provar(atual)
        melhor = max(melhor, nota_atual)
    return sorted(provados.values(), key=lambda p: p[0], reverse=True)


def _combinacoes(perfil) -> int:
    total = 1
    for opcoes in perfil.botoes.values():
        total *= len(opcoes)
    return total


def confirmar(cliente, mundo, perfil, meta: dict, sementes: list) -> int:
    """Quantas sementes novas repetem a falha com os mesmos botoes (a burla e robusta?)."""
    repetiu = 0
    for semente in sementes:
        episodio = construir(mundo, perfil, meta["botoes"], semente)
        if avaliacao.falha_do_episodio(avaliacao.executar(cliente, [episodio]), perfil.tipo) > 0:
            repetiu += 1
    return repetiu


# ----------------------------------------------------------------------
# Metamorficos
# ----------------------------------------------------------------------

def _sequencia(regs: list) -> list:
    return [(r["rotulo"], r["decisao"]) for r in regs if r["metodo"] == "POST" and r["papel"] != "rotina"]


def metamorfico(cliente, mundo, perfis: list, quantidade: int, acaso, aviso) -> list:
    """Gemeos do mesmo episodio. Devolve a lista de violacoes encontradas.

    identidade: mesma historia, CPFs novos. A decisao tem de ser a mesma;
      se nao for, a API depende de algo que nao e o comportamento (estado
      vazado entre clientes, acaso, ordem de chegada).
    valor em dobro: os Pix medidos com o dobro do valor. A decisao nao pode
      ficar mais branda; se ficar, a pontuacao nao e monotona no valor.
    """
    violacoes = []
    for i in range(quantidade):
        perfil = acaso.choice(perfis)
        botoes, semente = perfil.botoes_aleatorios(acaso), acaso.randrange(10 ** 6)
        base = _sequencia(avaliacao.executar(cliente, [construir(mundo, perfil, botoes, semente)]))
        gemeo = _sequencia(avaliacao.executar(cliente, [construir(mundo, perfil, botoes, semente)]))
        dobro = _sequencia(avaliacao.executar(cliente, [construir(mundo, perfil, botoes, semente, fator_valor=2.0)]))
        meta = {"perfil": perfil.nome, "tipo": perfil.tipo, "botoes": botoes, "semente": semente}
        if base != gemeo:
            violacoes.append({"tipo": "identidade", **meta, "base": base, "gemeo": gemeo})
        for posicao, ((_, antes), (_, depois)) in enumerate(zip(base, dobro)):
            if antes in ORDEM and depois in ORDEM and ORDEM[depois] < ORDEM[antes]:
                violacoes.append({"tipo": "valor_em_dobro", **meta, "posicao": posicao, "antes": antes, "depois": depois})
                break
        if (i + 1) % 10 == 0:
            aviso(f"  {i + 1} de {quantidade} trios, {len(violacoes)} violacoes ate aqui")
    return violacoes
