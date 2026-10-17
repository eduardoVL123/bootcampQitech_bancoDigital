"""Como os resultados das regras viram uma decisao.

A ordem dos passos e a politica, e cada um responde a uma pergunta:

1. Ha bloqueio prioritario? Limite do cliente, teto operacional ou marcacao
   critica do recebedor rejeitam sozinhos, e nada os desfaz.
2. Quanto vale cada familia? Regras da mesma familia medem o mesmo fato
   (limite e perfil olham, os dois, o valor), entao so a maior conta. As
   outras ficam registradas com 0 e `correlated`.
3. Quanto os redutores tiram? So da familia de valor individual, ate o
   teto da politica, e nunca deixando a familia negativa.
4. O score e a soma, limitado a 0..100, e cada eixo tem o seu total.
5. A tabela: rejeita com 80 ou mais SO SE dois eixos tiverem 20 ou mais.
   Risco alto concentrado num eixo pede a verificacao reforcada em vez de
   rejeitar: um sinal so, por mais forte, pode ter explicacao legitima.
   A excecao e o eixo destino com `reject_destination_alone` ou mais, e so
   com a confirmacao da CONTAS_NOVAS_DO_GRUPO (o grupo do titular com
   muitas contas novas): ali o 2FA nao protege, porque quem faz a
   verificacao e o pagador, e o pagador enganado (ou o dono da conta
   laranja repassando) passa nela. Sem a confirmacao, facial e documento:
   a loja nova na primeira semana tem a mesma cara (decisao do time).
6. Os pisos: uma regra pode exigir um nivel minimo de verificacao sem
   somar pontos. Piso nunca reduz a decisao.
"""
from dataclasses import dataclass

from controllers.engine.context import AXES, DESTINO, FACIAL, FACIAL_DOCUMENT, LEVELS, MOVIMENTACAO, NONE
from models import PixStatus

VALUE_FAMILY = "valor_individual"
TRUST_FAMILY = "confianca"

# Exceção entre famílias: a coordenação já conta o aparelho compartilhado
# pelos mesmos titulares, e ele não pode contar de novo como acesso.
SUPPRESSED_BY = {"COORDENACAO_ENTRE_CONTAS": ["APARELHO_COMPARTILHADO"]}

# A unica regra que deixa o eixo destino reprovar sozinho (passo 5). Ela
# nao soma pontos: e a confirmacao do grupo do titular.
DESTINATION_CONFIRMATION = "CONTAS_NOVAS_DO_GRUPO"


@dataclass
class Decision:
    status: str
    score: int
    axes: dict
    level: str
    reason: str
    reason_description: str
    destination_gate: str = "not_reached"


def _strongest_floor(floors) -> str:
    return max(floors, key=LEVELS.index, default=NONE)


def decide(results: list, params: dict) -> Decision:
    regras = params["decision"]
    disparadas = [r for r in results if r.is_triggered]

    for resultado in results:
        resultado.effective_points = 0
        resultado.correlated = False

    suprimidas = set()
    for regra, alvos in SUPPRESSED_BY.items():
        if any(r.rule == regra for r in disparadas):
            suprimidas.update(alvos)

    evidencias_vistas = set()
    maior_por_familia = {}
    for resultado in disparadas:
        if resultado.family == TRUST_FAMILY or resultado.raw_points <= 0:
            continue
        repetida = any(e in evidencias_vistas for e in resultado.evidence_ids)
        if resultado.rule in suprimidas or repetida:
            resultado.correlated = True
            continue
        evidencias_vistas.update(resultado.evidence_ids)
        atual = maior_por_familia.get(resultado.family)
        if atual is None or resultado.raw_points > atual.raw_points:
            if atual is not None:
                atual.correlated = True
            maior_por_familia[resultado.family] = resultado
        else:
            resultado.correlated = True

    for resultado in maior_por_familia.values():
        resultado.effective_points = resultado.raw_points

    valor = maior_por_familia.get(VALUE_FAMILY)
    espaco = min(valor.effective_points if valor else 0, params["reducers"]["max_total"])
    for resultado in disparadas:
        if resultado.family != TRUST_FAMILY:
            continue
        desconto = min(-resultado.raw_points, espaco)
        resultado.effective_points = -desconto
        espaco -= desconto

    eixos = {eixo: 0 for eixo in AXES}
    for resultado in results:
        if resultado.axis in eixos and resultado.effective_points:
            eixos[resultado.axis] += resultado.effective_points

    score = max(0, min(100, sum(eixos.values())))
    piso = _strongest_floor(r.floor for r in disparadas)
    bloqueios = [r for r in disparadas if r.hard_block]
    eixos_fortes = sum(1 for total in eixos.values() if total >= regras["reject_min_axis_points"])
    corte_destino = regras.get("reject_destination_alone")
    destino_sozinho = corte_destino is not None and eixos[DESTINO] >= corte_destino
    confirmado = any(r.rule == DESTINATION_CONFIRMATION for r in disparadas)
    portao = "not_reached"

    if bloqueios:
        status, nivel = PixStatus.REJECTED, NONE
    elif score >= regras["reject"] and eixos_fortes >= regras["reject_min_axes"]:
        status, nivel = PixStatus.REJECTED, NONE
    elif destino_sozinho and confirmado:
        status, nivel, portao = PixStatus.REJECTED, NONE, "rejected"
    elif destino_sozinho:
        # Decisao do time: sem a confirmacao do grupo, so facial e documento.
        status, nivel, portao = PixStatus.TWO_FACTOR_REQUIRED, FACIAL_DOCUMENT, "facial_document"
    elif score >= regras["facial_document"] or piso == FACIAL_DOCUMENT:
        status, nivel = PixStatus.TWO_FACTOR_REQUIRED, FACIAL_DOCUMENT
    elif score >= regras["facial"] or piso == FACIAL:
        status, nivel = PixStatus.TWO_FACTOR_REQUIRED, FACIAL
    else:
        status, nivel = PixStatus.APPROVED, NONE

    motivo = _reason(bloqueios, disparadas, piso, nivel)
    return Decision(status=status, score=score, axes=eixos, level=nivel,
                    reason=motivo.rule if motivo else "SEM_ALERTA",
                    reason_description=motivo.detail if motivo else "Nenhuma regra com pontos efetivos.",
                    destination_gate=portao)


def _reason(bloqueios, disparadas, piso, nivel):
    """A regra que melhor explica a decisao: o bloqueio, senao a de mais
    pontos efetivos, senao a que impos o piso."""
    if bloqueios:
        return bloqueios[0]
    com_pontos = [r for r in disparadas if r.effective_points > 0]
    if com_pontos:
        return max(com_pontos, key=lambda r: r.effective_points)
    if nivel != NONE:
        for resultado in disparadas:
            if resultado.floor == piso:
                return resultado
    return None


__all__ = ["Decision", "decide", "VALUE_FAMILY", "TRUST_FAMILY", "MOVIMENTACAO"]
