"""As informacoes de seguranca do DICT (Banco Central) sobre quem recebe.

E a peca que resolve o golpista que esta em OUTRO banco: a marcacao de fraude
que outra instituicao fez (conta laranja, conta de golpista, fraude de
cadastro, denuncia aberta) chega aqui antes da primeira vitima desta casa.

No projeto quem responde e o Mockserver, como os biros da onboarding-api. Na
vida real e o DICT, pela RSFN. O documento vai so no corpo do POST, nunca no
endereco nem no log.

Se o DICT nao responder a tempo, o Pix segue sem ele (falha aberta): a
marcacao e uma evidencia a mais, e o Pix nao pode esperar por ela. Depois de 3
falhas seguidas o circuito abre por 30 s, para o tempo limite nao somar em todo
Pix. Cada resposta fica 60 s em cache, por processo.
"""
import threading
import time

import requests

from constants import DICT_TIMEOUT_SECONDS, DICT_URL, INTERNAL_TOKEN

ENDPOINT = "/dict/v1/informacoes-seguranca"
CACHE_SEGUNDOS = 60
CACHE_MAXIMO = 10000
FALHAS_PARA_ABRIR = 3
CIRCUITO_ABERTO_SEGUNDOS = 30


class DictConnector:
    _cache = {}
    _falhas = 0
    _aberto_ate = 0.0
    _trava = threading.Lock()

    def security_information(self, document: str):
        """As estatisticas do documento, no formato do reputation_fixture, ou None (sem DICT ou fora do ar)."""
        if not DICT_URL:
            return None
        agora = time.monotonic()
        with DictConnector._trava:
            guardado = DictConnector._cache.get(document)
            if guardado and guardado[0] > agora:
                return guardado[1]
            if DictConnector._aberto_ate > agora:
                return None
        try:
            resposta = requests.post(DICT_URL.rstrip("/") + ENDPOINT, json={"document": document},
                                     headers={"INTERNAL-TOKEN": INTERNAL_TOKEN}, timeout=DICT_TIMEOUT_SECONDS)
            corpo = resposta.json() if resposta.status_code == 200 else None
        except (requests.RequestException, ValueError):
            corpo = None
        with DictConnector._trava:
            if not isinstance(corpo, dict) or not isinstance(corpo.get("statistics"), dict):
                DictConnector._falhas += 1
                if DictConnector._falhas >= FALHAS_PARA_ABRIR:
                    DictConnector._aberto_ate = agora + CIRCUITO_ABERTO_SEGUNDOS
                    DictConnector._falhas = 0
                return None
            DictConnector._falhas = 0
            if len(DictConnector._cache) >= CACHE_MAXIMO:
                DictConnector._cache.clear()
            DictConnector._cache[document] = (agora + CACHE_SEGUNDOS, corpo)
        return corpo
