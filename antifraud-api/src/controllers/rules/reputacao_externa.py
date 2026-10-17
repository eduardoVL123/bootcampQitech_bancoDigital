from controllers.engine.context import DESTINO
from controllers.engine.rule import Rule

MOCK = {"provider": "mock_bureau", "is_mock": True}


class ReputacaoExterna(Rule):
    """O que o mock de reputacao diz do recebedor, no formato do destination_statistics da QI.

    - marcacao critica: golpe ou conta laranja nos ultimos 90 dias, por pelo
      menos 2 denunciantes diferentes, com papel de suspeito: bloqueio;
    - alerta: denuncia aberta, ou golpe ou laranja nos ultimos 12 meses: +40;
    - fraude de cadastro ou papel de vitima: 0. Quem teve a identidade
      roubada e a vitima, nao o fraudador.
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
        if registro.entity_role == "victim":
            return self.not_triggered("Papel de vitima no mock.", reputation={**base, "signal": "victim"})

        def janela(campo, periodo):
            return int(estatisticas.get(campo, {}).get(periodo, 0))

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
