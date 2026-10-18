"""Conversa com a antifraud-api e le a resposta.

A resposta da API e {"key", "status", "metadata"}, e o detalhe (nivel de
autenticacao, regras, score, cenario, latencia) mora em metadata. A leitura
tambem aceita esses campos na raiz, para nao quebrar se o contrato mudar.
"""

import threading
import time

NIVEIS = ("facial", "facial_document")
STATUS = ("approved", "two_factor_required", "rejected")


def _metadata(resposta: dict) -> dict:
    meta = resposta.get("metadata")
    return meta if isinstance(meta, dict) else {}


def _campo(resposta: dict, chave: str):
    valor = resposta.get(chave)
    return valor if valor is not None else _metadata(resposta).get(chave)


def status(resposta: dict):
    return resposta.get("status") or resposta.get("decision")


def nivel_bruto(resposta: dict):
    for fonte in (resposta, _metadata(resposta)):
        for chave in ("auth_level", "level", "authentication_level"):
            if fonte.get(chave):
                return fonte[chave]
        for chave in ("authentication", "two_factor"):
            bloco = fonte.get(chave)
            if isinstance(bloco, dict) and bloco.get("level"):
                return bloco["level"]
    return None


def nivel(resposta: dict):
    return nivel_bruto(resposta) or ("none" if status(resposta) == "approved" else None)


def regras(resposta: dict, com_correlatas: bool = False) -> list:
    """As regras disparadas que contaram pontos.

    A API suprime a regra que mede o mesmo fato de outra (correlated): ela
    disparou, mas os pontos ficam com a outra. com_correlatas=True devolve
    tambem essas, para quem quer saber se o sinal foi percebido.
    """
    for chave in ("rules", "triggered_rules", "reasons"):
        lista = _campo(resposta, chave)
        if isinstance(lista, list):
            codigos = []
            for regra in lista:
                if not isinstance(regra, dict):
                    codigos.append(regra)
                elif regra.get("evaluation", "triggered") == "triggered" and (com_correlatas or not regra.get("correlated")):
                    codigos.append(regra.get("rule") or regra.get("code") or regra.get("name"))
            return [c for c in codigos if c]
    return []


def pontos(resposta: dict):
    for chave in ("risk_score", "score", "total_score", "points"):
        valor = _campo(resposta, chave)
        if isinstance(valor, (int, float)):
            return float(valor)
    return None


def cenario(resposta: dict):
    return _campo(resposta, "scenario")


def latencia(resposta: dict):
    valor = _campo(resposta, "latency_ms")
    return float(valor) if isinstance(valor, (int, float)) else None


def _regras_disparadas(resposta: dict) -> list:
    lista = _campo(resposta, "rules")
    if not isinstance(lista, list):
        return []
    return [r for r in lista if isinstance(r, dict) and r.get("evaluation", "triggered") == "triggered"]


def eixos(resposta: dict) -> dict:
    """Os pontos por eixo (movimentacao, acesso, destino) que a API somou."""
    valor = _campo(resposta, "risk_axes")
    return {k: v for k, v in valor.items() if isinstance(v, (int, float))} if isinstance(valor, dict) else {}


def piso(resposta: dict) -> str:
    """O nivel minimo de verificacao que alguma regra impos, sem somar pontos."""
    ordem = ("none", "facial", "facial_document")
    pisos = [r.get("authentication_floor") for r in _regras_disparadas(resposta)]
    return max((p for p in pisos if p in ordem), key=ordem.index, default="none")


def bloqueio(resposta: dict) -> bool:
    """Se alguma regra rejeita sozinha (limite do cliente, teto, marcacao critica)."""
    return any(r.get("hard_block") for r in _regras_disparadas(resposta))


def regras_detalhadas(resposta: dict) -> list:
    """Cada regra disparada com eixo, pontos efetivos, bloqueio e piso: o que a decisao da API usou."""
    return [{"regra": r.get("rule"), "eixo": r.get("axis"), "pontos": r.get("effective_points") or 0,
             "bloqueio": bool(r.get("hard_block")), "piso": r.get("authentication_floor") or "none"}
            for r in _regras_disparadas(resposta)]


def decisao(resposta: dict) -> str:
    """approved, facial, facial_document, rejected ou erro."""
    atual = status(resposta)
    if atual in ("approved", "rejected"):
        return atual
    if atual == "two_factor_required":
        return nivel_bruto(resposta) if nivel_bruto(resposta) in NIVEIS else "facial"
    return "erro"


class Cliente:
    """paralelo: quantos episodios andam ao mesmo tempo. conferir_get: ler o GET de volta nos Pix medidos."""

    def __init__(self, base_url: str, token: str, timeout: float, paralelo: int = 1, conferir_get: bool = True):
        try:
            import requests
        except ImportError:
            raise SystemExit("O laboratorio precisa do pacote requests:  pip install requests") from None
        self._requests = requests
        self._erros = requests.exceptions
        self._token = token
        self._local = threading.local()
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.paralelo = max(1, paralelo)
        self.conferir_get = conferir_get

    @property
    def sessao(self):
        """Uma sessao HTTP por thread: a Session do requests nao e feita para ser dividida."""
        sessao = getattr(self._local, "sessao", None)
        if sessao is None:
            sessao = self._requests.Session()
            sessao.headers.update({"INTERNAL-TOKEN": self._token, "Content-Type": "application/json"})
            self._local.sessao = sessao
        return sessao

    def enviar(self, metodo: str, caminho: str, corpo: dict, pix_id: str = None) -> dict:
        """Manda o pedido e, com pix_id, le o GET /pix/transaction/{id} de volta."""
        inicio = time.perf_counter()
        try:
            resposta = self.sessao.request(metodo, self.base_url + caminho, json=corpo, timeout=self.timeout)
        except self._erros.ConnectionError:
            raise SystemExit(f"Nao consegui falar com a antifraud-api em {self.base_url}. Ela esta de pe?") from None
        except self._erros.Timeout:
            return {"http": None, "corpo": {}, "latencia": self.timeout * 1000, "consulta": None, "falha": "timeout",
                    "erro": None}
        ms = (time.perf_counter() - inicio) * 1000

        try:
            lido = resposta.json()
        except ValueError:
            lido = {}
        lido = lido if isinstance(lido, dict) else {}
        if latencia(lido) is not None:
            ms = latencia(lido)

        consulta = None
        if pix_id and resposta.ok:
            gravado = self.sessao.get(f"{self.base_url}/pix/transaction/{pix_id}", timeout=self.timeout)
            try:
                consulta = decisao(gravado.json()) if gravado.status_code == 200 else f"HTTP {gravado.status_code}"
            except ValueError:
                consulta = "GET sem JSON"
        erro = None if resposta.ok else resposta.text[:160]
        return {"http": resposta.status_code, "corpo": lido, "latencia": ms, "consulta": consulta, "falha": None,
                "erro": erro}

    def responder_desafio(self, pix_id: str, quando: str, resultado: str) -> bool:
        """approved_by_client (passou na selfie) ou reproved_by_client ("nao fui eu"). Devolve se a API aceitou."""
        resposta = self.sessao.patch(f"{self.base_url}/pix/transaction/{pix_id}", timeout=self.timeout,
                                     json={"challenge_result": resultado, "event_date": quando})
        return resposta.ok
