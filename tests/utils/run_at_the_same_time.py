from concurrent.futures import ThreadPoolExecutor
from threading import Barrier


def run_at_the_same_time(funcao, lista_de_argumentos: list) -> list:
    """Dispara N chamadas no MESMO instante e devolve as N respostas.

    Thread sozinha nao basta: sem a barreira, a primeira requisicao
    costuma terminar antes de a ultima comecar, e o teste passaria com
    um codigo que nao aguenta concorrencia nenhuma.

    A barreira segura todas as threads ate a ultima chegar. So entao
    todas seguem juntas, e a disputa pela trava acontece de verdade.

    Use de 10 a 15 chamadas, nao milhares: o pool de conexoes da API e
    de 5 mais overflow, e cada requisicao parada esperando a trava
    segura uma conexao.
    """
    quantidade = len(lista_de_argumentos)
    portao = Barrier(quantidade)

    def espera_todos_e_chama(argumento):
        portao.wait()
        return funcao(argumento)

    with ThreadPoolExecutor(max_workers=quantidade) as executor:
        return list(executor.map(espera_todos_e_chama, lista_de_argumentos))
