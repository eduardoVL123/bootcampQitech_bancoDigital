from controllers.engine.context import DESTINO
from controllers.engine.rule import Rule
from utils.document_number import is_legal_person

MOCK = {"provider": "mock_company_registry", "is_mock": True}


def mascara_cpf(cpf: str) -> str:
    """O CPF como os dados abertos da Receita mostram o socio: so os seis do meio."""
    return f"***.{cpf[3:6]}.{cpf[6:9]}-**"


class ContasNovasDoGrupo(Rule):
    """O grupo do titular do destino tem muitas contas novas: a confirmacao que deixa o eixo destino reprovar.

    Decisao do time. A conta laranja nova e a loja nova na primeira semana
    recebem, as duas, de muita gente numa conta nova; o que separa as duas e
    o grupo. Todo CNPJ tem um CPF responsavel, e quem monta conta laranja
    abre varias, no CPF e nos CNPJs dele.

    O grupo: o destino, o CPF responsavel por ele (destino pessoa fisica: o
    proprio CPF) e os CNPJs desse CPF em aberto no instante do Pix. O vinculo
    vem do mock do cadastro de empresas; CNPJ sem vinculo vigente e um grupo
    de um so. Conta nova: aberta nos ultimos `new_account_days` dias, entre
    as que o motor ja viu, a do destino inclusive, uma por documento e
    instituicao.

    Nao soma pontos e nao bloqueia: com `min_new_accounts` contas novas, o
    eixo destino com `reject_destination_alone` ou mais reprova sozinho
    (controllers/engine/decision.py). Sem a confirmacao, facial e documento.
    """

    code = "CONTAS_NOVAS_DO_GRUPO"
    axis = DESTINO
    family = "grupo_do_titular"

    def evaluate(self, ctx, params):
        p = params[self.code]
        destino, cpf, vinculo, link = ctx.destination_document, ctx.destination_document, None, "self"
        if is_legal_person(destino):
            registros = ctx.registry.links_of_cnpj(destino)
            vigentes = [r for r in registros if r.available_from <= ctx.moment < r.expires_at]
            vinculo = vigentes[-1] if vigentes else None
            link = "found" if vinculo else ("not_in_force" if registros else "not_found")
            cpf = vinculo.responsible_cpf if vinculo else None
        empresas = ctx.registry.open_cnpjs_of(cpf, ctx.moment) if cpf else []
        documentos = sorted({destino, *(e.cnpj for e in empresas), *([cpf] if cpf else [])})
        novas = len(ctx.history.new_accounts_of(documentos, ctx.moment, p["new_account_days"]))
        usadas = list(empresas) + ([vinculo] if vinculo else [])
        evidencias = sorted({r.evidence_id for r in usadas})
        confirmado = novas >= p["min_new_accounts"]
        grupo = {**MOCK, "link": link, "responsible_cpf": mascara_cpf(cpf) if cpf else None,
                 "open_cnpjs": [e.cnpj for e in empresas], "new_accounts": novas,
                 "window_days": p["new_account_days"], "min_new_accounts": p["min_new_accounts"],
                 "confirmed": confirmado, "evidence_ids": evidencias,
                 "fixture_version": max((r.fixture_version for r in usadas), default=None)}
        quem = f"CPF {mascara_cpf(cpf)} e {len(empresas)} CNPJ(s) em aberto" if cpf else "CNPJ sem vinculo vigente no mock"
        detalhe = (f"Grupo do titular ({quem}): {novas} conta(s) nova(s) em {p['new_account_days']} dias, "
                   f"corte {p['min_new_accounts']}.")
        if not confirmado:
            return self.not_triggered(detalhe, group=grupo)
        return self.triggered(0, detalhe, data_origin="mock" if evidencias else "history",
                              evidence_ids=evidencias, group=grupo)
