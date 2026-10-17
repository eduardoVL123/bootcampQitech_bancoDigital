"""Massa de cenarios do antifraude Pix, montada por mutacao de um Pix normal.

Roda contra a antifraud-api de pe (docker compose up -d --build --wait):

    python tools/cenarios_antifraude.py

Cada cenario cria pessoas ficticias com historico gerado pela propria API
(o mesmo POST que a banca usa) e aplica uma mutacao: valor, horario, mes,
aparelho, rede, GPS, IP ou reputacao do recebedor. No fim, imprime uma
tabela em markdown, a taxa de aprovacao no trafego legitimo, a taxa de
retencao no fraudulento e a latencia do motor.

E massa SINTETICA: os numeros verificam que o motor faz o que o README
descreve. Nao medem eficacia contra fraude real.
"""
import os
import random
import sys
from datetime import timedelta
from statistics import median

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tests.utils.pix import (  # noqa: E402
    APARELHO_NA_WATCHLIST, RECEBEDOR_MARCACAO_CRITICA, RECEBEDOR_NA_WATCHLIST, RECEBEDOR_VITIMA, RECIFE_GPS,
    AntifraudApi, Pagador, Recebedor, analisa, historico, nova_base, novo_ip, paga, payload_do_documento, pix,
)

CASA = "99999999"
LATENCIAS = []


def _registra(corpo: dict) -> dict:
    LATENCIAS.append(corpo["metadata"]["latency_ms"])
    return corpo


def _post(payload: dict) -> dict:
    return _registra(analisa(payload))


def _cliente_regular(hoje):
    pagador = Pagador()
    valores = [random.randint(3000, 12000) for _ in range(14)]
    historico(pagador, valores, hoje - timedelta(days=9), timedelta(hours=14), recebedores_novos=True)
    return pagador


def _mes_anterior(data, meses):
    ano, mes = data.year, data.month - meses
    while mes < 1:
        ano, mes = ano - 1, mes + 12
    return data.replace(year=ano, month=mes)


# ----------------------------------------------------------------------
# Trafego legitimo: o que o motor NAO pode travar
# ----------------------------------------------------------------------

def compra_do_dia_a_dia():
    hoje = nova_base()
    return _post(pix(_cliente_regular(hoje), Recebedor(pj=True), 8000, hoje.isoformat()))


def aluguel_recorrente():
    hoje = nova_base().replace(day=5, hour=10)
    pagador, senhorio = _cliente_regular(hoje), Recebedor()
    for atras in range(5, 0, -1):
        paga(pix(pagador, senhorio, 250000, _mes_anterior(hoje, atras).isoformat()))
    return _post(pix(pagador, senhorio, 250000, hoje.isoformat()))


def fornecedor_de_sempre():
    hoje = nova_base()
    pagador, fornecedor = Pagador(), Recebedor(pj=True)
    historico(pagador, [4000000] * 5, hoje - timedelta(days=20), timedelta(days=4), recebedor=fornecedor)
    return _post(pix(pagador, fornecedor, 4200000, hoje.isoformat()))


def primeiro_aluguel():
    hoje = nova_base()
    return _post(pix(_cliente_regular(hoje), Recebedor(), 250000, hoje.isoformat()))


def para_a_propria_conta():
    hoje = nova_base()
    pagador = _cliente_regular(hoje)
    return _post(pix(pagador, Recebedor(documento=pagador.documento), 300000, hoje.isoformat()))


def empresa_pela_api_sem_gps():
    hoje = nova_base()
    empresa = Pagador(canal="api")
    return _post(pix(empresa, Recebedor(pj=True), 90000, hoje.isoformat(), gps=None))


def cliente_novo_valor_baixo():
    return _post(pix(Pagador(), Recebedor(), 10000, nova_base().isoformat()))


def loja_movimentada():
    hoje = nova_base().replace(hour=15)
    loja = Recebedor(pj=True)
    for dia in range(7, 0, -1):
        inicio = (hoje - timedelta(days=dia)).replace(hour=12)
        for indice in range(10):
            analisa(pix(Pagador(), loja, 5000, (inicio + timedelta(minutes=3 * indice)).isoformat()))
    ultimo = None
    for indice in range(10):
        ultimo = _post(pix(Pagador(), loja, 5000, (hoje + timedelta(minutes=3 * indice)).isoformat()))
    return ultimo


def payload_do_documento_oficial():
    return _post(payload_do_documento())


def clientes_da_mesma_operadora():
    """CGNAT: seis clientes no mesmo IP, cada um na rede de sempre, pagando um amigo as 21h."""
    hoje, ip, ultimo = nova_base().replace(hour=21, minute=0), novo_ip("100.64.12"), None
    for indice in range(6):
        amigo, cliente = Recebedor(), Pagador()
        cliente.ip = ip
        historico(cliente, [150000] * 3, hoje - timedelta(days=40), timedelta(days=3), recebedor=amigo)
        ultimo = _post(pix(cliente, amigo, 150000, (hoje + timedelta(minutes=indice)).isoformat()))
    return ultimo


def almoco_depois_do_2fa_do_carro():
    hoje = nova_base()
    pagador = _cliente_regular(hoje)
    _post(pix(pagador, Recebedor(pj=True), 2500000, hoje.isoformat()))
    return _post(pix(pagador, Recebedor(pj=True), 3000, (hoje + timedelta(minutes=10)).isoformat()))


def quem_nunca_manda_gps():
    hoje = nova_base()
    pagador = Pagador(gps=None)
    historico(pagador, [6000, 9000, 7000], hoje - timedelta(days=9), timedelta(days=3), recebedores_novos=True)
    return _post(pix(pagador, Recebedor(aberta_em=hoje - timedelta(days=20)), 8000, hoje.isoformat()))


# ----------------------------------------------------------------------
# Trafego fraudulento: o que o motor TEM de segurar
# ----------------------------------------------------------------------

def acima_do_teto():
    return _post(pix(Pagador(), Recebedor(), 15000000, nova_base().isoformat()))


def conta_tomada():
    hoje = nova_base()
    pagador = _cliente_regular(hoje)
    _post(pix(pagador, Recebedor(), 5000, hoje.isoformat()))
    return _post(pix(pagador, Recebedor(aberta_em=hoje - timedelta(days=2)), 400000,
                     (hoje + timedelta(minutes=15)).isoformat(), gps=RECIFE_GPS, aparelho="dvc-ladrao-" + pagador.conta))


def rajada_de_10():
    pagador, hoje, ultimo = Pagador(), nova_base(), None
    for indice in range(10):
        ultimo = _post(pix(pagador, Recebedor(), 5000, (hoje + timedelta(seconds=20 * indice)).isoformat()))
    return ultimo


def fatiamento():
    pagador, recebedor, hoje, ultimo = Pagador(), Recebedor(), nova_base(), None
    for indice in range(4):
        ultimo = _post(pix(pagador, recebedor, 290000, (hoje + timedelta(minutes=10 * indice)).isoformat()))
    return ultimo


def sondagem_de_limite():
    pagador, hoje, ultimo = Pagador(), nova_base(), None
    for indice, valor in enumerate([3000000, 2500000, 1900000]):
        ultimo = _post(pix(pagador, Recebedor(), valor, (hoje + timedelta(minutes=3 * indice)).isoformat()))
    return ultimo


def conta_laranja():
    hoje = nova_base()
    laranja, ultimo = Recebedor(aberta_em=hoje - timedelta(days=5)), None
    for indice in range(10):
        ultimo = _post(pix(Pagador(), laranja, 50000, (hoje + timedelta(minutes=indice)).isoformat()))
    return ultimo


def repasse_rapido():
    hoje = nova_base()
    conta = Recebedor(participante=CASA)
    for indice in range(4):
        _post(pix(Pagador(), conta, 100000, (hoje + timedelta(minutes=indice)).isoformat()))
    return _post(pix(conta.como_pagador(), Recebedor(aberta_em=hoje - timedelta(hours=3)), 380000,
                     (hoje + timedelta(minutes=10)).isoformat()))


def coordenacao_entre_contas():
    hoje = nova_base()
    aparelho, destino, ultimo = f"dvc-fazenda-{random.randint(0, 10**9)}", Recebedor(aberta_em=hoje - timedelta(days=2)), None
    for indice in range(3):
        ultimo = _post(pix(Pagador(), destino, 80000, (hoje + timedelta(minutes=indice)).isoformat(), aparelho=aparelho))
    return ultimo


def recebedor_com_marcacao_critica():
    return _post(pix(Pagador(), Recebedor(documento=RECEBEDOR_MARCACAO_CRITICA), 5000, nova_base().isoformat()))


def aparelho_na_lista_interna():
    return _post(pix(Pagador(), Recebedor(), 50000, nova_base().isoformat(), aparelho=APARELHO_NA_WATCHLIST))


def acima_do_limite_do_cliente():
    pagador, hoje = Pagador(), nova_base()
    corpo = pagador.conta_json()
    corpo.update({"amount": 200000, "requested_at": hoje.isoformat()})
    AntifraudApi.put_limit(corpo)
    return _post(pix(pagador, Recebedor(), 300000, (hoje + timedelta(minutes=5)).isoformat()))


def noite_valor_alto_sem_gps():
    return _post(pix(Pagador(), Recebedor(), 2500000, nova_base().replace(hour=23).isoformat(), gps=None))


def falsa_central_para_conta_confirmada():
    """A vitima paga do celular e do lugar de sempre, um valor do perfil dela."""
    hoje = nova_base()
    vitima = Pagador()
    historico(vitima, [200000, 250000, 300000, 350000, 400000, 280000, 320000, 260000, 310000, 290000],
              hoje - timedelta(days=12), timedelta(days=1), recebedores_novos=True)
    return _post(pix(vitima, Recebedor(documento=RECEBEDOR_NA_WATCHLIST, aberta_em=hoje - timedelta(days=3)), 300000,
                     hoje.isoformat()))


def conta_segura_no_proprio_cpf():
    """O golpista abriu uma conta no nome da vitima e manda ela proteger o saldo ali."""
    hoje = nova_base()
    vitima = Pagador(documento=RECEBEDOR_VITIMA)
    conta_do_golpista = Recebedor(documento=RECEBEDOR_VITIMA, aberta_em=hoje - timedelta(hours=3),
                                  participante="12345678")
    return _post(pix(vitima, conta_do_golpista, 1500000, hoje.isoformat()))


def datas_recuando():
    """Seis Pix mandados agora, com a transaction_date recuando uma hora cada."""
    pagador, base, ultimo = Pagador(), nova_base(), None
    for indice in range(6):
        ultimo = _post(pix(pagador, Recebedor(), 5000, (base - timedelta(hours=indice)).isoformat()))
    return ultimo


def aparelho_sem_cadastro():
    hoje = nova_base()
    pagador = _cliente_regular(hoje)
    return _post(pix(pagador, Recebedor(), 50000, hoje.isoformat(), aparelho=f"dvc-novo-{pagador.conta}"))


LEGITIMOS = [
    ("compra do dia a dia", compra_do_dia_a_dia, {"approved"}),
    ("aluguel recorrente (5 meses)", aluguel_recorrente, {"approved"}),
    ("fornecedor de sempre (R$ 42 mil)", fornecedor_de_sempre, {"approved"}),
    ("transferencia para a propria conta", para_a_propria_conta, {"approved", "facial"}),
    ("empresa pela api, sem GPS", empresa_pela_api_sem_gps, {"approved"}),
    ("cliente novo, R$ 100", cliente_novo_valor_baixo, {"approved"}),
    ("loja que recebe de 10 clientes por hora", loja_movimentada, {"approved"}),
    ("primeiro aluguel (R$ 2.500)", primeiro_aluguel, {"approved", "facial", "facial_document"}),
    ("payload do documento oficial", payload_do_documento_oficial, {"facial"}),
    ("6 clientes da mesma operadora (CGNAT), 21h", clientes_da_mesma_operadora, {"approved"}),
    ("almoco de R$ 30 depois do 2FA do carro", almoco_depois_do_2fa_do_carro, {"approved"}),
    ("quem nunca manda GPS, destino de 20 dias", quem_nunca_manda_gps, {"approved"}),
]

FRAUDES = [
    ("acima do teto operacional", acima_do_teto, {"rejected"}),
    ("acima do limite do cliente", acima_do_limite_do_cliente, {"rejected"}),
    ("recebedor com marcacao critica (mock)", recebedor_com_marcacao_critica, {"rejected"}),
    ("noite, R$ 25 mil, sem GPS", noite_valor_alto_sem_gps, {"rejected"}),
    ("conta tomada (aparelho novo, Recife em 15 min)", conta_tomada, {"rejected", "facial_document"}),
    ("rajada de 10 Pix em 5 min", rajada_de_10, {"facial_document"}),
    ("sondagem: R$ 30 mil, 25 mil, 19 mil", sondagem_de_limite, {"facial_document", "rejected"}),
    ("conta laranja: 10 pagadores, conta nova", conta_laranja, {"facial_document", "rejected"}),
    ("repasse rapido para conta de 3 horas", repasse_rapido, {"facial_document", "rejected"}),
    ("coordenacao: 3 titulares, 1 aparelho", coordenacao_entre_contas, {"facial", "facial_document", "rejected"}),
    ("fatiamento: 4 x R$ 2.900 em 30 min", fatiamento, {"facial", "facial_document"}),
    ("aparelho na lista interna", aparelho_na_lista_interna, {"facial", "facial_document", "rejected"}),
    ("falsa central para conta confirmada (lista interna)", falsa_central_para_conta_confirmada, {"rejected"}),
    ("conta segura no proprio CPF (fraude de cadastro)", conta_segura_no_proprio_cpf, {"rejected"}),
    ("6 Pix com a data recuando 1 h cada", datas_recuando, {"facial_document", "rejected"}),
    ("aparelho sem cadastro, R$ 500", aparelho_sem_cadastro, {"facial", "facial_document", "rejected"}),
]


def _resultado(corpo: dict) -> str:
    if corpo["status"] == "two_factor_required":
        return corpo["metadata"]["authentication"]["level"]
    return corpo["status"]


def _regras(corpo: dict) -> str:
    """As regras que mudaram a decisao: pontos, bloqueio ou piso (as de piso nao somam pontos)."""
    def pesou(r):
        return r["effective_points"] or r["hard_block"] or (r["evaluation"] == "triggered"
                                                            and r["authentication_floor"] != "none")

    def texto(r):
        if r["hard_block"]:
            return f"{r['rule']} (bloqueio)"
        if not r["effective_points"]:
            return f"{r['rule']} (piso {r['authentication_floor']})"
        return f"{r['rule']} {r['effective_points']:+d}"

    com_pontos = [r for r in corpo["metadata"]["rules"] if pesou(r)]
    com_pontos.sort(key=lambda r: (-r["hard_block"], -abs(r["effective_points"])))
    return ", ".join(texto(r) for r in com_pontos[:4])


def roda(grupo):
    linhas = []
    for nome, cenario, esperado in grupo:
        corpo = cenario()
        obtido = _resultado(corpo)
        linhas.append((nome, esperado, obtido, corpo["metadata"]["risk_score"], corpo["metadata"]["scenario"],
                       _regras(corpo), obtido in esperado))
    return linhas


def imprime(titulo, linhas):
    print(f"\n### {titulo}\n")
    print("| Cenario | Esperado | Obtido | Score | Cenario deduzido | Regras que pesaram | Ok |")
    print("|---|---|---|---:|---|---|:-:|")
    for nome, esperado, obtido, score, deduzido, regras, ok in linhas:
        print(f"| {nome} | {' ou '.join(sorted(esperado))} | {obtido} | {score} | {deduzido} | {regras} | "
              f"{'sim' if ok else 'NAO'} |")


def main():
    legitimos, fraudes = roda(LEGITIMOS), roda(FRAUDES)
    imprime("Trafego legitimo", legitimos)
    imprime("Trafego fraudulento", fraudes)

    aprovados = sum(1 for linha in legitimos if linha[2] == "approved")
    retidos = sum(1 for linha in fraudes if linha[2] != "approved")
    corretos = sum(1 for linha in legitimos + fraudes if linha[6])
    ordenadas = sorted(LATENCIAS)
    p95 = ordenadas[int(0.95 * (len(ordenadas) - 1))]
    print("\n### Resumo (massa sintetica)\n")
    print(f"- Legitimos aprovados sem friccao: {aprovados} de {len(legitimos)}")
    print(f"- Fraudes retidas (2FA ou rejeicao): {retidos} de {len(fraudes)}")
    print(f"- Cenarios no resultado esperado: {corretos} de {len(legitimos) + len(fraudes)}")
    print(f"- Latencia do motor em {len(ordenadas)} analises: p50 {median(ordenadas):.0f} ms, p95 {p95:.0f} ms")
    return 0 if corretos == len(legitimos) + len(fraudes) else 1


if __name__ == "__main__":
    sys.exit(main())
