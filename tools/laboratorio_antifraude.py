"""Laboratorio da antifraud-api: rodadas sorteadas, cacador de burlas e regressao.

Subcomandos (todos black-box, falando so HTTP com a API):

  catalogo      lista os perfis legitimos e as tipologias de golpe, com botoes,
                sinais, defesa conhecida e fonte. Nao precisa da API.
  gerar         monta uma rodada e grava os payloads rotulados em
                tools/resultados/, sem mandar nada. Nao precisa da API.
  rodada        sorteia episodios de todos os perfis, manda para a API e mede.
  cacar         para cada tipologia, procura a combinacao de botoes que escapa.
  regressao     repete tudo o que ja escapou (tools/corpus_antifraude.json).
  metamorfico   roda gemeos do mesmo episodio e cobra coerencia da API.
  repetir       repete um episodio exato, Pix por Pix, para depurar.
  comparar      repete os episodios de uma rodada salva (mesmos perfis, botoes e
                sementes) contra a API de agora e mostra o que melhorou e o que
                piorou, episodio por episodio, com margem de erro.
  loop          rodada, cacada nos piores e regressao, sem parar, ate tres
                voltas seguidas sem erro (ou Ctrl+C).

Cada rodada usa CPFs, contas e aparelhos novos e um dia simulado sorteado no
ultimo ano, entao nao precisa limpar o banco entre uma e outra. A semente fica no relatorio: rodar de novo com
--semente repete a mesma historia com identidades novas.
"""

import argparse
import json
import os
import random
import sys
import uuid
from datetime import date, timedelta

from laboratorio import analise, avaliacao, cacador, dict_mock
from laboratorio.api import Cliente
from laboratorio.catalogo import construir, escolher, todos
from laboratorio.mundo import Mundo


def _tag() -> str:
    return uuid.uuid4().hex[:6]


def _cliente(args) -> Cliente:
    return Cliente(args.url, os.environ.get("INTERNAL_TOKEN", "default_token"), args.timeout,
                   paralelo=args.paralelo, conferir_get=not args.sem_get)


def _episodios(args, mundo, acaso) -> list:
    episodios = []
    for perfil in escolher(args.perfis):
        for _ in range(args.por_perfil):
            episodios.append(construir(mundo, perfil, perfil.botoes_aleatorios(acaso), acaso.randrange(10 ** 6)))
    return episodios


def _dia(args, semente: int = None) -> str:
    """O "hoje" simulado: o --data, ou um dia passado tirado da semente.

    Passado porque a API recusa Pix no futuro. Sorteado porque os documentos do
    seed sao os mesmos em todas as rodadas: no mesmo dia, as rodadas somariam
    pagamentos uns dos outros a fraude ativa e a vitima registrada.
    """
    if args.data:
        return args.data
    semente = random.randrange(10 ** 6) if semente is None else semente
    return (date.today() - timedelta(days=1 + semente % 365)).isoformat()


def _marcar_no_dict(args, episodios) -> dict:
    """Com --dict-marca, diz ao DICT de mentira quais contas criminosas outro banco ja marcou."""
    marcados = dict_mock.escolher(episodios, args.dict_marca)
    dict_mock.programar(args.mockserver, marcados)
    return marcados


def _cabecalho(titulo, tag, semente, dia, episodios) -> list:
    return [f"# {titulo} {tag}", "",
            f"semente {semente}, dia simulado {dia}, {len(episodios)} episodios, "
            f"{sum(len(e.eventos) for e in episodios)} pedidos"]


# ----------------------------------------------------------------------
# Subcomandos
# ----------------------------------------------------------------------

def cmd_catalogo(args):
    for perfil in escolher(args.perfis):
        print(f"## {perfil.nome} ({perfil.tipo})\n\n{perfil.descricao}.\n")
        for nome, opcoes in perfil.botoes.items():
            print(f"- botao `{nome}`: {', '.join(str(o) for o in opcoes)}")
        if perfil.tipo != "legitimo":
            print(f"- {'contido' if perfil.tipo == 'fraude' else 'protegido'} a partir de: {perfil.contido_por}")
            print(f"- sinais: {', '.join(perfil.sinais)}")
            if perfil.ausente_no_contrato:
                print(f"- fora do contrato: {', '.join(perfil.ausente_no_contrato)}")
            print(f"- defesa: {perfil.defesa}\n- fonte: {perfil.fonte}")
        print()
    return 0


def cmd_gerar(args):
    semente = args.semente if args.semente is not None else random.randrange(10 ** 9)
    tag = _tag()
    episodios = _episodios(args, Mundo(tag, _dia(args, semente), not args.ip_fixo), random.Random(semente))
    eventos = sorted((ev for ep in episodios for ev in ep.eventos), key=lambda ev: ev.quando)
    # Como na suite fixa: um arquivo so com o que vai para a API, outro com as respostas.
    payloads = [{"id": ev.id, "method": ev.metodo, "path": ev.caminho, "body": ev.corpo} for ev in eventos]
    gabarito = [{"id": ev.id, "perfil": ev.perfil, "episodio": ev.episodio, "rotulo": ev.rotulo, "papel": ev.papel,
                 "valor": ev.valor, "contido_por": ev.contido_por, "aceitavel_ate": ev.aceitavel_ate,
                 "regulatorio": ev.regulatorio, "resposta_ao_desafio": ev.desafio} for ev in eventos]
    avaliacao.PASTA_RESULTADOS.mkdir(exist_ok=True)
    for nome, conteudo in (("payloads", payloads), ("gabarito", gabarito)):
        destino = avaliacao.PASTA_RESULTADOS / f"massa-{tag}-{nome}.json"
        destino.write_text(json.dumps(conteudo, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"{len(conteudo)} itens em {destino}")
    contagem = {}
    for ev in eventos:
        contagem[ev.rotulo] = contagem.get(ev.rotulo, 0) + 1
    print(f"{len(episodios)} episodios ({contagem}), semente {semente}")
    return 0


def rodada(args, cliente, semente, silencioso=False):
    tag = _tag()
    dia = _dia(args, semente)
    mundo = Mundo(tag, dia, not args.ip_fixo)
    episodios = _episodios(args, mundo, random.Random(semente))
    metas = {ep.id: cacador.meta_de(ep) for ep in episodios}
    marcados = _marcar_no_dict(args, episodios)
    print(f"Rodada {tag}: {len(episodios)} episodios, {sum(len(e.eventos) for e in episodios)} pedidos")
    registros = avaliacao.executar(cliente, episodios, print)

    corpus = cacador.ler_corpus()
    por_episodio = {}
    for r in registros:
        por_episodio.setdefault(r["episodio"], []).append(r)
    novos = sum(cacador.registrar(corpus, metas[ep_id], regs, tag, "rodada")
                for ep_id, regs in por_episodio.items() if cacador.vale_guardar(corpus, metas[ep_id], regs))
    cacador.gravar_corpus(corpus)

    cabecalho = _cabecalho("Rodada", tag, semente, dia, episodios) + [f"{novos} falhas novas guardadas no corpus"]
    if args.dict_marca:
        cabecalho.append(f"DICT de mentira: {len(marcados)} contas criminosas ja marcadas por outro banco "
                         f"({args.dict_marca:.0%} dos episodios de golpe)")
    perfis = sorted({m["perfil"] for m in metas.values()})
    texto = avaliacao.relatorio(registros, metas, todos(), cabecalho, avaliacao.ultima_rodada(perfis))
    destino = avaliacao.guardar(tag, "rodada", semente, registros, metas, texto, dia)
    if not silencioso:
        print(texto)
    print(f"Relatorio em {destino.with_suffix('.md')}")
    return registros, metas


def cmd_rodada(args):
    semente = args.semente if args.semente is not None else random.randrange(10 ** 9)
    registros, _ = rodada(args, _cliente(args), semente)
    return 1 if avaliacao.falha_geral(registros) else 0


def cacada(args, cliente, perfis, semente):
    mundo = Mundo(_tag(), _dia(args, semente), not args.ip_fixo)
    corpus = cacador.ler_corpus()
    linhas = ["| perfil | provas | maior falha | botoes | repete em sementes novas |", "|---|---|---|---|---|"]
    for perfil in perfis:
        print(f"  cacando {perfil.nome}")
        provados = cacador.cacar(cliente, mundo, perfil, args.orcamento, semente, print)
        achados = [p for p in provados if p[0][0] > 0]
        if not achados:
            linhas.append(f"| {perfil.nome} | {len(provados)} | 0% | nada escapou | |")
            continue
        repeticoes = []
        for _, meta, regs in achados[:3]:
            repetiu = cacador.confirmar(cliente, mundo, perfil, meta, [semente + 1, semente + 2])
            cacador.registrar(corpus, meta, regs, mundo.tag, "cacador", nota=f"repetiu em {repetiu} de 2 sementes novas")
            repeticoes.append(repetiu)
        objetivo, meta, _ = achados[0]
        botoes = ",".join(f"{k}={v}" for k, v in meta["botoes"].items())
        linhas.append(f"| {perfil.nome} | {len(provados)} | {objetivo[0]:.0%} | {botoes} | {repeticoes[0]} de 2 |")
    cacador.gravar_corpus(corpus)
    return linhas


def cmd_cacar(args):
    semente = args.semente if args.semente is not None else random.randrange(10 ** 6)
    perfis = escolher(args.perfis, None if args.tipo == "todos" else args.tipo)
    linhas = cacada(args, _cliente(args), perfis, semente)
    print("\n".join(["", f"# Cacada (semente {semente})", ""] + linhas))
    print(f"\nAchados guardados em {cacador.CORPUS}. Repita com: python tools/laboratorio_antifraude.py regressao")
    return 0


def cmd_regressao(args):
    mundo = Mundo(_tag(), _dia(args, args.semente), not args.ip_fixo)
    if not cacador.ler_corpus():
        print("O corpus esta vazio. Rode uma rodada ou uma cacada primeiro.")
        return 0
    registros, metas, mudancas = cacador.regressao(_cliente(args), mundo, print)
    cabecalho = [f"# Regressao {mundo.tag}", "",
                 f"{mudancas['resolvidas']} resolvidas, {mudancas['abertas']} abertas, "
                 f"{mudancas['reabertas']} voltaram a falhar"]
    texto = avaliacao.relatorio(registros, metas, todos(), cabecalho)
    avaliacao.guardar(mundo.tag, "regressao", None, registros, metas, texto)
    print(texto)
    return 1 if mudancas["abertas"] or mudancas["reabertas"] else 0


def cmd_metamorfico(args):
    semente = args.semente if args.semente is not None else random.randrange(10 ** 9)
    mundo = Mundo(_tag(), _dia(args, semente), not args.ip_fixo)
    violacoes = cacador.metamorfico(_cliente(args), mundo, escolher(args.perfis), args.quantidade,
                                    random.Random(semente), print)
    print(f"\n# Metamorficos (semente {semente}): {len(violacoes)} violacoes em {args.quantidade} trios\n")
    for v in violacoes:
        botoes = ",".join(f"{k}={o}" for k, o in v["botoes"].items())
        if v["tipo"] == "identidade":
            print(f"- identidade, {v['perfil']} ({botoes}, semente {v['semente']}): {v['base']} virou {v['gemeo']}")
        else:
            print(f"- valor em dobro, {v['perfil']} ({botoes}, semente {v['semente']}): o Pix {v['posicao'] + 1} "
                  f"foi de {v['antes']} para {v['depois']}")
    return 1 if violacoes else 0


def cmd_repetir(args):
    catalogo = todos()
    if args.perfil not in catalogo:
        raise SystemExit(f"Perfil desconhecido: {args.perfil}")
    perfil = catalogo[args.perfil]
    mundo = Mundo(_tag(), _dia(args, args.semente), not args.ip_fixo)
    episodio = construir(mundo, perfil, perfil.ler_botoes(args.botoes), args.semente)
    registros = avaliacao.executar(_cliente(args), [episodio])
    print(f"# {perfil.nome}, semente {args.semente}, botoes {episodio.botoes}\n")
    print("| quando | papel | rotulo | valor | decisao | precisava | regras | pontos |")
    print("|---|---|---|---|---|---|---|---|")
    for r in registros:
        precisava = r["contido_por"] or r["aceitavel_ate"] or ""
        print(f"| {r['quando'][5:16]} | {r['papel']} | {r['rotulo']} | {avaliacao._reais(r['valor'])} | {r['decisao']} "
              f"| {precisava} | {', '.join(r['regras'])} | {'' if r['pontos'] is None else r['pontos']} |")
    print(f"\nfalha do episodio: {avaliacao.falha_do_episodio(registros, perfil.tipo):.0%}")
    return 0


def cmd_comparar(args):
    base = avaliacao.carregar_rodada(args.base)
    catalogo = todos()
    # O mesmo calendario da rodada base; as identidades sao novas, a historia e a mesma.
    dia = base.get("data") or _dia(args, base.get("semente") or 0)
    mundo = Mundo(_tag(), dia, not args.ip_fixo)
    pares, episodios, ignorados = [], [], 0
    for ep_id, meta in base["metas"].items():
        perfil = catalogo.get(meta["perfil"])
        if perfil is None or set(meta["botoes"]) != set(perfil.botoes):
            ignorados += 1  # o perfil mudou desde a rodada base
            continue
        episodio = construir(mundo, perfil, meta["botoes"], meta["semente"])
        pares.append((ep_id, episodio.id))
        episodios.append(episodio)
    marcados = _marcar_no_dict(args, episodios)
    print(f"Comparando com a rodada {base['tag']}: {len(episodios)} episodios ({ignorados} ignorados), "
          f"{len(marcados)} contas marcadas no DICT")
    registros = avaliacao.executar(_cliente(args), episodios, print)
    # A rodada nova tambem fica salva, com o relatorio inteiro: a simulacao de
    # politica e o efeito de cada regra saem dela, e ela serve de base depois.
    metas = {ep.id: cacador.meta_de(ep) for ep in episodios}
    cabecalho = _cabecalho("Rodada", mundo.tag, base.get("semente"), dia, episodios) + [
        f"Os mesmos episodios da rodada {base['tag']}, repetidos pelo comparar"]
    avaliacao.guardar(mundo.tag, "rodada", base.get("semente"), registros, metas,
                      avaliacao.relatorio(registros, metas, catalogo, cabecalho), dia)
    linhas = [f"# Comparacao {mundo.tag} com a rodada {base['tag']}", "",
              f"Mesmos perfis, botoes e sementes da rodada base (dia simulado {dia}), identidades novas. A API ja "
              "guarda o historico das rodadas anteriores, entao parte da diferenca pode vir disso, e nao de mudanca no "
              "codigo.", ""]
    linhas += analise.comparar(base["registros"], base["metas"], registros, pares)
    texto = "\n".join(linhas)
    avaliacao.PASTA_RESULTADOS.mkdir(exist_ok=True)
    destino = avaliacao.PASTA_RESULTADOS / f"comparacao-{mundo.tag}.md"
    destino.write_text(texto + "\n", encoding="utf-8")
    print(texto)
    print(f"Comparacao em {destino}")
    return 0


def cmd_loop(args):
    cliente = _cliente(args)
    acaso = random.Random(args.semente)
    volta, seguidas = 0, 0
    try:
        while not args.vezes or volta < args.vezes:
            volta += 1
            print(f"\n=== Volta {volta} ===")
            registros, _ = rodada(args, cliente, acaso.randrange(10 ** 9), silencioso=True)
            resumo = avaliacao.resumir(registros)
            piores = avaliacao.piores_tipologias(registros, args.cacar_piores)
            if piores:
                print("\n".join(cacada(args, cliente, escolher(",".join(piores)), acaso.randrange(10 ** 6))))
            _, _, mudancas = cacador.regressao(cliente, Mundo(_tag(), _dia(args), not args.ip_fixo), print)
            print(f"volta {volta}: contido {avaliacao._pct(resumo['contencao'])}, falso positivo "
                  f"{avaliacao._pct(resumo['falso_positivo'])}, friccao {avaliacao._pct(resumo['friccao_indevida'])}, "
                  f"corpus {mudancas['abertas'] + mudancas['reabertas']} abertos e {mudancas['resolvidas']} resolvidos")
            limpa = not avaliacao.falha_geral(registros) and not mudancas["abertas"] and not mudancas["reabertas"]
            seguidas = seguidas + 1 if limpa else 0
            if seguidas >= 3:
                print("Tres voltas seguidas sem erro contra este gerador. Hora de inventar tipologias novas.")
                break
    except KeyboardInterrupt:
        print("\nInterrompido. O corpus e o historico ja estao gravados.")
    return 0


# ----------------------------------------------------------------------

def main() -> int:
    host = os.environ.get("SERVER_LOCALHOST", "localhost").strip()
    porta = os.environ.get("ANTIFRAUD_API_PORT", "3020").strip()
    comum = argparse.ArgumentParser(add_help=False)
    comum.add_argument("--url", default=f"http://{host}:{porta}", help="endereco da antifraud-api")
    comum.add_argument("--timeout", type=float, default=10.0, help="segundos por pedido")
    comum.add_argument("--paralelo", type=int, default=8, help="episodios ao mesmo tempo; 1 manda tudo em fila")
    mock = os.environ.get("MOCKSERVER_PORT", "1080").strip()
    comum.add_argument("--mockserver", default=f"http://{host}:{mock}", help="Mockserver que faz o papel do DICT")
    comum.add_argument("--dict-marca", type=float, default=0.0,
                       help="fracao dos episodios de golpe cujas contas outro banco ja marcou no DICT (0 a 1)")
    comum.add_argument("--sem-get", action="store_true",
                       help="nao le o GET /pix/transaction/{id} de volta (mais rapido, sem conferir a gravacao)")
    comum.add_argument("--data", help="o 'hoje' simulado (AAAA-MM-DD); padrao: um dia do ultimo ano, tirado da semente")
    comum.add_argument("--perfis", help="lista separada por virgula; padrao: todos")
    comum.add_argument("--semente", type=int, help="repete a mesma historia; padrao: sorteada")
    comum.add_argument("--ip-fixo", action="store_true", help="usa o IP exato do seed em vez de variar na faixa")

    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = parser.add_subparsers(dest="comando", required=True)
    sub.add_parser("catalogo", parents=[comum]).set_defaults(funcao=cmd_catalogo)
    for nome, funcao in (("gerar", cmd_gerar), ("rodada", cmd_rodada)):
        p = sub.add_parser(nome, parents=[comum])
        p.add_argument("--por-perfil", type=int, default=3, help="episodios sorteados de cada perfil")
        p.set_defaults(funcao=funcao)
    p = sub.add_parser("cacar", parents=[comum])
    p.add_argument("--orcamento", type=int, default=25, help="episodios provados por perfil")
    p.add_argument("--tipo", choices=["fraude", "legitimo", "autoprotecao", "todos"], default="fraude")
    p.set_defaults(funcao=cmd_cacar)
    sub.add_parser("regressao", parents=[comum]).set_defaults(funcao=cmd_regressao)
    p = sub.add_parser("metamorfico", parents=[comum])
    p.add_argument("--quantidade", type=int, default=20, help="trios de episodios gemeos")
    p.set_defaults(funcao=cmd_metamorfico)
    p = sub.add_parser("repetir", parents=[comum])
    p.add_argument("--perfil", required=True)
    p.add_argument("--botoes", default="", help='ex.: "valor=1,fatias=8"; o que faltar fica na opcao ingenua')
    p.set_defaults(funcao=cmd_repetir, semente=0)
    p = sub.add_parser("comparar", parents=[comum])
    p.add_argument("--base", default="ultima", help="tag da rodada salva em tools/resultados, ou ultima")
    p.set_defaults(funcao=cmd_comparar)
    p = sub.add_parser("loop", parents=[comum])
    p.add_argument("--vezes", type=int, default=0, help="0 roda ate tres voltas limpas seguidas ou Ctrl+C")
    p.add_argument("--por-perfil", type=int, default=3)
    p.add_argument("--orcamento", type=int, default=15)
    p.add_argument("--cacar-piores", type=int, default=3, help="quantas tipologias cacar por volta")
    p.set_defaults(funcao=cmd_loop)

    args = parser.parse_args()
    return args.funcao(args)


if __name__ == "__main__":
    sys.exit(main())
