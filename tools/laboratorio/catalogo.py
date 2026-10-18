"""O catalogo de perfis: clientes legitimos e tipologias de golpe.

Cada perfil tem botoes, e cada botao tem uma lista de opcoes. A primeira
opcao e a mais comum (num legitimo) ou a mais ingenua (num golpe); as
seguintes sao as variacoes que um cliente real ou um golpista adaptado
usariam. A rodada sorteia as opcoes; o cacador anda por elas atras da
combinacao que engana a API.
"""

from dataclasses import dataclass

from laboratorio.mundo import Episodio, Mundo


@dataclass
class Perfil:
    nome: str
    tipo: str  # legitimo, fraude ou autoprotecao
    descricao: str
    botoes: dict
    construir: object
    contido_por: str = None
    sinais: tuple = ()
    defesa: str = ""
    ausente_no_contrato: tuple = ()
    fonte: str = ""

    def botoes_ingenuos(self) -> dict:
        return {nome: opcoes[0] for nome, opcoes in self.botoes.items()}

    def botoes_aleatorios(self, acaso) -> dict:
        return {nome: acaso.choice(opcoes) for nome, opcoes in self.botoes.items()}

    def vizinhos(self, botoes: dict) -> list:
        """Todas as combinacoes que mudam um botao so."""
        saida = []
        for nome, opcoes in self.botoes.items():
            for opcao in opcoes:
                if opcao != botoes[nome]:
                    saida.append({**botoes, nome: opcao})
        return saida

    def ler_botoes(self, texto: str) -> dict:
        """Le "valor=1,fatias=8" casando cada valor com uma opcao do botao."""
        botoes = self.botoes_ingenuos()
        for par in filter(None, (p.strip() for p in (texto or "").split(","))):
            nome, _, valor = par.partition("=")
            if nome not in self.botoes:
                raise SystemExit(f"{self.nome} nao tem o botao {nome!r}. Botoes: {', '.join(self.botoes)}")
            opcoes = {str(o): o for o in self.botoes[nome]}
            if valor not in opcoes:
                raise SystemExit(f"Opcoes de {nome}: {', '.join(opcoes)}")
            botoes[nome] = opcoes[valor]
        return botoes


CATALOGO = {}


def perfil(**dados):
    def registra(funcao):
        CATALOGO[dados["nome"]] = Perfil(construir=funcao, **dados)
        return funcao
    return registra


def todos() -> dict:
    # Os modulos registram os perfis ao serem importados.
    from laboratorio import fraudes, legitimos, protecao  # noqa: F401
    return CATALOGO


def escolher(nomes: str = None, tipo: str = None) -> list:
    catalogo = todos()
    if nomes:
        faltando = [n for n in nomes.split(",") if n.strip() not in catalogo]
        if faltando:
            raise SystemExit(f"Perfis desconhecidos: {', '.join(faltando)}. Veja a lista com o subcomando catalogo.")
        perfis = [catalogo[n.strip()] for n in nomes.split(",")]
    else:
        perfis = list(catalogo.values())
    return [p for p in perfis if tipo is None or p.tipo == tipo]


def construir(mundo: Mundo, perfil: Perfil, botoes: dict, semente: int, fator_valor: float = 1.0) -> Episodio:
    episodio = Episodio(mundo, perfil, botoes, semente, fator_valor)
    perfil.construir(episodio, episodio.botoes)
    return episodio


def chave_botoes(botoes: dict) -> str:
    return ",".join(f"{k}={botoes[k]}" for k in sorted(botoes))
