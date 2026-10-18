"""O "DICT de mentira" no Mockserver: quanto vale saber o que outros bancos ja marcaram.

A conta laranja costuma ser reutilizada: a mesma conta recebe de vitimas de
varios bancos, e algum deles ja marcou fraude no DICT. Este modulo programa o
Mockserver para responder, sobre uma fracao das contas criminosas de cada
rodada, "esta conta ja tem marcacao de outro banco". Rodar a mesma rodada com
fracao 0 e com fracao 0,5 mostra quanto a consulta ao DICT acrescenta.

Contas de clientes honestos nunca sao marcadas aqui: o DICT nao certifica
conta boa, e a ausencia de marcacao e o caso normal.
"""

import random

ENDPOINT = "/dict/v1/informacoes-seguranca"


def _estatisticas(acaso) -> dict:
    """70% marcacao recente (90 dias, bloqueia); 30% so antiga (12 meses, alerta)."""
    recente = acaso.random() < 0.7
    laranja = {"d90": 1 if recente else 0, "m12": acaso.randint(1, 3), "m60": acaso.randint(1, 4)}
    denunciantes = acaso.randint(1, 4)
    return {
        "mule_accounts": laranja,
        "scammer_accounts": {"d90": 0, "m12": 0, "m60": 0},
        "application_frauds": {"d90": 0, "m12": 0, "m60": 0},
        "distinct_fraud_reporters": {"d90": denunciantes if recente else 0, "m12": denunciantes, "m60": denunciantes},
        "open_reports": acaso.randint(0, 2),
        "rejected_reports": {"d90": 0, "m12": 0, "m60": 0},
        "linked_accounts": acaso.randint(2, 6),
    }


def escolher(episodios: list, fracao: float) -> dict:
    """{documento: estatisticas} das contas criminosas ja marcadas. Mesma semente, mesma escolha."""
    marcados = {}
    if fracao <= 0:
        return marcados
    for episodio in episodios:
        acaso = random.Random(f"{episodio.perfil.nome}:{episodio.semente}:dict")
        if not episodio.recebedores_do_golpe or acaso.random() >= fracao:
            continue
        for documento in sorted(episodio.recebedores_do_golpe):
            marcados[documento] = _estatisticas(acaso)
    return marcados


def programar(url: str, marcados: dict) -> None:
    """Uma expectativa por documento, acima da resposta padrao "sem marcacao"."""
    if not marcados:
        return
    import requests

    expectativas = [{
        "httpRequest": {"method": "POST", "path": ENDPOINT,
                        "body": {"type": "JSON", "json": {"document": documento}, "matchType": "ONLY_MATCHING_FIELDS"}},
        "httpResponse": {"statusCode": 200, "headers": {"Content-Type": ["application/json"]},
                         "body": {"type": "JSON", "json": {"statistics": estatisticas,
                                                           "evidence_id": f"dict-lab-{documento[-6:]}"}}},
        "priority": 10,
    } for documento, estatisticas in marcados.items()]
    for inicio in range(0, len(expectativas), 200):
        try:
            resposta = requests.put(url.rstrip("/") + "/mockserver/expectation", json=expectativas[inicio:inicio + 200],
                                    timeout=30)
        except requests.exceptions.ConnectionError:
            raise SystemExit(f"Nao consegui falar com o Mockserver em {url}. Ele esta de pe?") from None
        if resposta.status_code not in (200, 201):
            raise SystemExit(f"O Mockserver recusou as marcacoes do DICT: HTTP {resposta.status_code} {resposta.text[:200]}")
