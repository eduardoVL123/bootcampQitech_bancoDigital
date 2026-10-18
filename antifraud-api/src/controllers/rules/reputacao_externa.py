from controllers.engine.context import DESTINO
from controllers.engine.rule import Rule

MOCK = {"provider": "mock_bureau", "is_mock": True}


class ReputacaoExterna(Rule):
    """O que o mock de reputacao diz do recebedor, no formato do destination_statistics da QI.

    - marcacao critica: golpe ou conta laranja nos ultimos 90 dias, com papel
      de suspeito: bloqueio. Basta UM denunciante (`min_reporters` na
      politica): no DICT, `mule_accounts` e `scammer_accounts` contam
      marcacoes de fraude, que so existem depois de a instituicao do
      recebedor analisar e confirmar. Denuncia que ainda nao foi analisada e
      `open_reports`, e essa so soma pontos;
    - alerta: denuncia aberta, ou golpe ou laranja nos ultimos 12 meses: +40;
    - fraude de cadastro ou papel de vitima: 0 para a conta antiga. Quem
      teve a identidade roubada e a vitima, nao o fraudador. Conta NOVA nesse
      CPF e outra historia (ver _conta_nova_em_cpf_com_fraude_de_cadastro);
    So vale a evidencia vigente no instante do Pix (available_from e
    expires_at). Ficticio, deterministico e marcado como tal.
    """

    code = "REPUTACAO_EXTERNA"
    axis = DESTINO
    family = "reputacao"

    def evaluate(self, ctx, params):
        p = params[self.code]
        registros = ctx.reputation.fixtures(ctx.destination_document)
        if not registros:
            return self.not_triggered(reputation={**MOCK, "signal": "not_found"})
        vigentes = [r for r in registros if r.available_from <= ctx.moment < r.expires_at]
        if not vigentes:
            return self.not_triggered(reputation={**MOCK, "signal": "expired",
                                                  "fixture_version": registros[-1].fixture_version})
        registro = vigentes[-1]
        estatisticas = registro.statistics
        base = {**MOCK, "fixture_version": registro.fixture_version, "entity_role": registro.entity_role,
                "evidence_id": registro.evidence_id}

        def janela(campo, periodo):
            return int(estatisticas.get(campo, {}).get(periodo, 0))

        cadastro = self._conta_nova_em_cpf_com_fraude_de_cadastro(ctx, p, janela, registro, base)
        if cadastro is not None:
            return cadastro
        if registro.entity_role == "victim":
            return self.not_triggered("Papel de vitima no mock.", reputation={**base, "signal": "victim"})

        golpe_90 = janela("mule_accounts", "d90") + janela("scammer_accounts", "d90")
        golpe_12m = janela("mule_accounts", "m12") + janela("scammer_accounts", "m12")
        denunciantes = janela("distinct_fraud_reporters", "d90")
        if golpe_90 > 0 and denunciantes >= p["min_reporters"]:
            return self.triggered(0, f"Mock: marcacao critica do recebedor ({golpe_90} ocorrencias em 90 dias, "
                                  f"{denunciantes} denunciantes).", hard_block=True, data_origin="mock",
                                  evidence_ids=[registro.evidence_id],
                                  reputation={**base, "signal": "active_fraud_marker"})
        if int(estatisticas.get("open_reports", 0)) > 0 or golpe_12m > 0:
            return self.triggered(p["alert_points"], "Mock: alerta sobre o recebedor (denuncia aberta ou ocorrencia "
                                  "em 12 meses).", data_origin="mock", evidence_ids=[registro.evidence_id],
                                  reputation={**base, "signal": "risk_alert"})
        return self.not_triggered(reputation={**base, "signal": "no_relevant_alerts"})

    def _conta_nova_em_cpf_com_fraude_de_cadastro(self, ctx, p, janela, registro, base):
        """Fraude de cadastro: a PESSOA e vitima, mas a CONTA nova pode ser do fraudador.

        `application_frauds` conta contas abertas com o documento de alguem.
        O dono do CPF e vitima e nao vira fraudador (a conta antiga dele
        continua limpa). Mas o motor decide se manda dinheiro para ESTA conta,
        e uma conta aberta ha pouco num CPF que ja teve conta aberta por
        fraude e exatamente a conta que o fraudador abriu.

        Para o proprio titular, e o golpe da "conta segura": o golpista abre
        uma conta no nome da vitima e manda ela "proteger" o saldo ali. O
        nome e o CPF na tela tranquilizam, e a facial ela passa. Bloqueio.
        """
        if not (janela("application_frauds", "d90") or janela("application_frauds", "m12")):
            return None
        idade = (ctx.moment - ctx.destination_account.opening_date).days
        if idade >= p["application_fraud_new_account_days"]:
            return None
        sinal = {**base, "signal": "application_fraud_new_account"}
        if ctx.source_document == ctx.destination_document and idade < p["application_fraud_same_holder_days"]:
            return self.triggered(0, f"Mock: conta aberta ha {idade} dias no CPF de quem paga, que ja teve conta aberta "
                                  "por fraude de cadastro (golpe da conta segura).", hard_block=True, data_origin="mock",
                                  evidence_ids=[registro.evidence_id], reputation=sinal)
        return self.triggered(p["alert_points"], f"Mock: conta destino aberta ha {idade} dias num CPF com fraude de "
                              "cadastro; o titular e vitima, a conta nova pode ser do fraudador.", data_origin="mock",
                              evidence_ids=[registro.evidence_id], reputation=sinal)
