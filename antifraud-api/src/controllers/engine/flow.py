"""O dinheiro de terceiros que passou por uma conta: o que entrou, o que voltou e o que escoou.

E a projecao que o REPASSE_RAPIDO le. Nao e um ledger e nao grava nada:
ela e refeita a cada Pix a partir das analises e das confirmacoes que o
motor ja tem, so com o que estava disponivel no instante avaliado.

Dinheiro e fungivel, entao dizer de quem e cada centavo que sai e uma
atribuicao, nao um fato. A regra adotada (heuristica FIFO):
- cada entrada de outro titular vira um lote, numa fila global e na lista
  daquele titular;
- uma saida para quem pagou e devolucao so ate o credito que ele ainda tem
  na conta, e consome esse credito. Estar entre os pagadores nao basta: o
  destino que mandou R$ 0,01 tem R$ 0,01 de devolucao, e mais nada;
- o que passa disso escoa os lotes de terceiros mais antigos (FIFO). Lote
  consumido, por devolucao ou escoamento, nao volta;
- saida sem lote disponivel (dinheiro de antes da janela, ou que chegou de
  fora do motor) nao entra na conta.

Entrada do proprio titular nao e dinheiro de terceiros, e a transferencia
da conta para ela mesma nao move nada. Mandar para outra conta do mesmo
titular, porem, escoa os lotes de terceiros como qualquer outra saida.

Tudo em centavos inteiros. Cada lote entra uma vez em cada fila e sai uma
vez dela: a varredura e linear no numero de eventos.
"""
from collections import deque
from dataclasses import dataclass, field
from fractions import Fraction

INCOMING = "in"
OUTGOING = "out"


@dataclass
class _Lot:
    document: str
    remaining: int


@dataclass
class Flow:
    incoming: int = 0
    refunded: int = 0
    outflow: int = 0
    current_refund: int = 0
    current_outflow: int = 0
    received_by: dict = field(default_factory=dict)
    refunded_to: dict = field(default_factory=dict)

    @property
    def base(self) -> int:
        """B = I - R: o que entrou de terceiros e nao voltou para eles."""
        return self.incoming - self.refunded

    @property
    def qualified_payers(self) -> int:
        """Titulares ainda expostos: receberam de volta menos do que pagaram.

        O lote escoado continua contando como exposicao de quem pagou; quem
        foi devolvido por inteiro sai da conta.
        """
        return sum(1 for documento, total in self.received_by.items() if total > self.refunded_to.get(documento, 0))

    def reaches(self, share: Fraction) -> bool:
        """E / B >= share, sem ponto flutuante: E * den >= B * num."""
        return self.base > 0 and self.outflow * share.denominator >= self.base * share.numerator

    def identifies(self, min_payers: int, share: Fraction, min_base: int = 0) -> bool:
        """O repasse: pagadores suficientes, base material, o escoamento no corte e o Pix atual escoando o pool.

        `min_base` e o minimo da base da janela inteira, e nao de cada entrada
        ou saida: tres creditos de R$ 0,01 nao fazem repasse, e varios creditos
        pequenos somados fazem.
        """
        return (self.qualified_payers >= min_payers and self.base >= min_base and self.reaches(share)
                and self.current_outflow > 0)

    def describe(self) -> dict:
        return {
            "incoming": self.incoming, "refunded": self.refunded, "outflow": self.outflow, "base": self.base,
            "current_refund": self.current_refund, "current_outflow": self.current_outflow,
            "qualified_payers": self.qualified_payers,
        }


def project(events, account_id: int, owner_document: str, current) -> Flow:
    """A projecao dos eventos, e do Pix atual por ultimo, como saida candidata.

    `events`: (disponivel, id, lado, valor, documento da outra ponta, conta
    da outra ponta), ja em ordem de (disponivel, id). `current`: (valor,
    documento destino, conta destino) do Pix em analise, que nao foi gravado
    e entra uma vez so, depois dos empatados com ele.
    """
    fluxo = Flow()
    fila = deque()
    por_titular = {}
    disponivel = {}

    def entra(valor, documento):
        lote = _Lot(documento, valor)
        fila.append(lote)
        por_titular.setdefault(documento, deque()).append(lote)
        disponivel[documento] = disponivel.get(documento, 0) + valor
        fluxo.incoming += valor
        fluxo.received_by[documento] = fluxo.received_by.get(documento, 0) + valor

    def consome(lotes, valor) -> int:
        consumido = 0
        while valor > consumido and lotes:
            lote = lotes[0]
            if lote.remaining == 0:
                lotes.popleft()
                continue
            parte = min(valor - consumido, lote.remaining)
            lote.remaining -= parte
            disponivel[lote.document] -= parte
            consumido += parte
        return consumido

    def sai(valor, documento) -> tuple:
        devolvido = 0
        if documento != owner_document and disponivel.get(documento, 0) > 0:
            devolvido = consome(por_titular[documento], min(valor, disponivel[documento]))
            fluxo.refunded += devolvido
            fluxo.refunded_to[documento] = fluxo.refunded_to.get(documento, 0) + devolvido
        escoado = consome(fila, valor - devolvido)
        fluxo.outflow += escoado
        return devolvido, escoado

    for _disponivel, _id, lado, valor, documento, outra_conta in events:
        if outra_conta == account_id:
            continue
        if lado == INCOMING:
            if documento != owner_document:
                entra(int(valor), documento)
        else:
            sai(int(valor), documento)

    valor, documento, outra_conta = current
    if outra_conta != account_id:
        fluxo.current_refund, fluxo.current_outflow = sai(int(valor), documento)
    return fluxo
