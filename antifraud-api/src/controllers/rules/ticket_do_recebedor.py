from controllers.engine.context import DESTINO
from controllers.engine.profile import day_start, eligible, evaluate_amount
from controllers.engine.rule import Rule
from utils.document_number import is_legal_person
from utils.money import brl


class TicketDoRecebedor(Rule):
    """O valor fora do que se costuma pagar ao recebedor: a doceria nao recebe R$ 20 mil de uma vez.

    Duas referencias, a primeira que existir, sem somar:
    1. a regua do proprio recebedor: os creditos aprovados que OUTROS clientes
       da casa mandaram para a conta nos 90 dias ate o inicio de hoje, com a
       conta do PERFIL (mediana, MAD e amostra minima). O motor so ve o que os
       clientes da casa pagam; para "esse valor e normal para o que se paga
       aqui?", e a amostra certa;
    2. sem regua (conta nova, ou pouco paga pela casa), o teto de ticket da
       atividade: o CNAE principal do CNPJ, no mock de cadastro. Em producao,
       os dados abertos do CNPJ da Receita, pelo documento que o DICT devolve.
    Pessoa fisica sem regua nao tem com o que comparar.

    Quem ja pagou esse valor (ou mais) ao mesmo recebedor nao ganha pontos: e
    o cliente da encomenda grande de sempre. A regra so soma, nunca bloqueia
    e nao confirma o eixo destino sozinho: encomenda de casamento numa
    doceria existe. Ela dificulta (2FA); reprovar, so se outro eixo concordar.
    """

    code = "TICKET_DO_RECEBEDOR"
    axis = DESTINO
    family = "ticket_do_recebedor"

    def evaluate(self, ctx, params):
        p = params[self.code]
        ja_pagos = ctx.history.approved_to_document(ctx.source_document, ctx.destination_document, ctx.moment)
        if any(int(linha[0]) >= ctx.amount for linha in ja_pagos):
            return self.not_triggered("O pagador ja pagou esse valor, ou mais, a este recebedor.")

        creditos = ctx.history.approved_credits_from_others(ctx.destination_account.id, ctx.source_document,
                                                            day_start(ctx), p["window_days"])
        if eligible(ctx, creditos, p) and len({linha[2] for linha in creditos}) >= p["min_payers"]:
            ticket = evaluate_amount(ctx.amount, [int(linha[0]) for linha in creditos], "recebedor", p)
            if ticket.level is None:
                return self.not_triggered(**ticket.describe())
            return self.triggered(ticket.points, f"{brl(ctx.amount)} contra ticket mediano de {brl(round(ticket.m))} "
                                  f"do recebedor ({ticket.sample} creditos de outros clientes).", data_origin="history",
                                  **ticket.describe())

        if not is_legal_person(ctx.destination_document):
            return self.not_evaluable("Recebedor sem regua de creditos, e pessoa fisica nao tem CNAE.")
        cadastro = ctx.reputation.company(ctx.destination_document)
        teto = _teto_da_atividade(cadastro.cnae, p["cnae"]["ticket_ceiling"]) if cadastro else None
        if teto is None:
            return self.not_evaluable("Recebedor sem regua de creditos e sem teto de ticket para a atividade.")
        atividade = {"reference": "cnae", "cnae": cadastro.cnae, "ticket_ceiling": teto, "is_mock": True}
        if ctx.amount <= teto:
            return self.not_triggered(**atividade)
        nivel = "high" if ctx.amount > p["cnae"]["high_multiple"] * teto else "moderate"
        return self.triggered(p["cnae"]["points"][nivel], f"Mock: {brl(ctx.amount)} para a atividade {cadastro.cnae}, "
                              f"acima do ticket de {brl(teto)} dela.", data_origin="mock", **atividade)


def _teto_da_atividade(cnae: str, tetos: dict):
    """O teto da classe do CNAE (4 digitos), senao o da divisao (2)."""
    for prefixo in (cnae[:4], cnae[:2]):
        if prefixo in tetos:
            return tetos[prefixo]
    return None
