-- A politica versao 2 e o indice das confirmacoes, num banco antifraud que ja existe.
--
-- O banco nasce do database/antifraud.sql, que ja traz os dois. Este arquivo
-- e para o volume criado antes de 18/10/2026: aplica so o que falta e pode
-- rodar quantas vezes for preciso (o INSERT nao faz nada se a versao 2 ja
-- existe, e o indice so e criado se nao existir). A versao 1 e as analises
-- gravadas com ela nao mudam.
--
--     docker compose exec -T db psql -U bootcamp -d antifraud -v ON_ERROR_STOP=1 < antifraud-api/migrations/0002_politica_v2.sql

CREATE INDEX IF NOT EXISTS pix_challenge_result_approved_event ON pix_challenge_result (event_date)
    WHERE result = 'approved_by_client';

INSERT INTO fraud_policy (version, parameters)
SELECT 2, parameters || '{
    "decision": {"facial": 40, "facial_document": 60, "reject": 80, "reject_min_axis_points": 20, "reject_min_axes": 2,
                 "reject_destination_alone": 80, "destination_corroboration": ["REPUTACAO_EXTERNA", "REPUTACAO_INTERNA"],
                 "destination_warning_min": 40},
    "DISPERSAO_DE_SAIDA": {"window_hours": 24, "min_amount": 10000, "min_destinations": {"pf": 5, "pj": 20}, "points": 40},
    "CONTA_REATIVADA": {"min_account_age_days": 30, "idle_days": 60, "window_hours": 24, "burst_count": 3, "window_amount": 200000, "min_amount": 500000, "points": 30, "floor": "facial"},
    "NOTURNO": {"start_hour": 20, "end_hour": 6, "min_amount": 100000, "points": 25, "new_legal_person_days": 90},
    "APARELHO_NAO_CADASTRADO": {"per_pix": 20000, "per_day": 100000, "channels": ["app", "web"], "natural_person_channels": ["api"]},
    "DESTINO_NOVO": {"days": 30, "points": 20, "very_new_hours": 24, "very_new_points": 30, "very_new_floor": "facial", "very_new_floor_min_amount": 20000},
    "REPASSE_RAPIDO": {"windows": [{"minutes": 60, "min_payers": 3}, {"minutes": 1440, "min_payers": 5}], "share": 0.8, "points": 60, "inconclusive_points": 20, "min_base": 10000}
}'::jsonb
FROM fraud_policy WHERE version = 1
ON CONFLICT (version) DO NOTHING;
