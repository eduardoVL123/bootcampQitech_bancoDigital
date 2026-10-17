-- ============================================================
-- O banco do antifraude Pix (antifraud-api)
-- ============================================================
--
-- Um banco proprio, ao lado do `bootcamp` da fase 1, no mesmo container.
-- O antifraude nao le nenhuma tabela do banco digital: tudo de que ele
-- precisa chega no payload ou e o historico que ele mesmo gravou.
--
-- Este arquivo roda uma vez so, quando o volume do Postgres nasce (o
-- Dockerfile o copia como 02.sql, depois do 01.sql da fase 1). Mudou
-- alguma coisa aqui: docker compose down -v.

CREATE DATABASE antifraud;

\connect antifraud

-- ------------------------------------------------------------
-- 1. O BANCO RECUSA REESCREVER O PASSADO
-- ------------------------------------------------------------
-- A mesma funcao da fase 1 (database.sql): analise gravada nao muda.
-- Corrigir e gravar coisa nova. TRUNCATE continua livre, e e por ele
-- que os testes zeram o banco.

CREATE OR REPLACE FUNCTION refuse_change() RETURNS TRIGGER AS $$
BEGIN
    RAISE EXCEPTION 'A tabela % e append-only: % nao e permitido', TG_TABLE_NAME, TG_OP;
END;
$$ LANGUAGE plpgsql;

-- ------------------------------------------------------------
-- 2. A POLITICA E OS STATUS
-- ------------------------------------------------------------

CREATE TABLE pix_status(
    id SMALLSERIAL PRIMARY KEY,
    enumerator VARCHAR(30) NOT NULL UNIQUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

INSERT INTO pix_status (enumerator) VALUES ('APPROVED'), ('TWO_FACTOR_REQUIRED'), ('REJECTED');

-- Todos os cortes, pesos e janelas das regras moram aqui, e nao no
-- codigo. Mudar um parametro e gravar uma versao nova; a analise guarda
-- a versao que usou, e o GET de um Pix antigo continua batendo com a
-- regra que valia quando ele chegou. Valores em centavos.
CREATE TABLE fraud_policy(
    id SERIAL PRIMARY KEY,
    version INTEGER NOT NULL UNIQUE,
    parameters JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TRIGGER fraud_policy_is_append_only
    BEFORE UPDATE OR DELETE ON fraud_policy
    FOR EACH ROW EXECUTE FUNCTION refuse_change();

INSERT INTO fraud_policy (version, parameters) VALUES (1, '{
    "timezone": "America/Sao_Paulo",
    "decision": {"facial": 40, "facial_document": 60, "reject": 80, "reject_min_axis_points": 20, "reject_min_axes": 2},
    "reducers": {"max_total": 20},
    "LIMITE_POR_PIX": {"high": 2000000, "points": 40, "ceiling": 10000000},
    "PERFIL": {
        "window_days": 90, "min_difference": 50000,
        "references": {
            "pair": {"min_payments": 5, "min_days": 3, "min_span_days": 14, "window_days": 365},
            "calendar_phase": {"min_payments": 10, "min_days": 3},
            "payer": {"min_payments": 10, "min_days": 3}
        },
        "mad": {"moderate": {"z": 3.5, "multiple": 2, "points": 30}, "high": {"z": 7, "multiple": 3, "points": 50}},
        "mad_zero": {"moderate": {"multiple": 3, "points": 30}, "high": {"multiple": 6, "points": 50}}
    },
    "PERFIL_SEM_HISTORICO": {"min_amount": 500000, "points": 20},
    "VELOCITY": {
        "windows_minutes": [5, 30],
        "fallback_window_minutes": 5,
        "fallback": [{"count": 10, "points": 60, "floor": "facial_document"}, {"count": 5, "points": 40, "floor": "facial"}, {"count": 3, "points": 25, "floor": "none"}],
        "moderate": {"minimum": 3, "multiple": 2, "k": 3, "points": 40},
        "high": {"minimum": 5, "multiple": 3, "k": 6, "points": 60}
    },
    "reference": {"days": 30, "min_active_days": 7, "min_events": 20},
    "MONTANTE_24H": {"limit": 5000000, "points": 40, "deviation": {"multiple": 2, "k": 3, "floor": 100000}},
    "FATIAMENTO": {"window_minutes": 60, "min_prior": 3, "limit": 1000000, "points": 40, "deviation": {"multiple": 2, "k": 3, "floor": 50000}},
    "MONTANTE_DIARIO_ATIPICO": {"days": 30, "min_days": 7, "multiple": 3, "min_excess": 100000, "points": 30},
    "ORIGEM_NOVA": {"max_age_hours": 48, "min_amount": 100000, "points": 25},
    "CONTA_REATIVADA": {"min_account_age_days": 30, "idle_days": 60, "burst_minutes": 60, "burst_count": 3, "min_amount": 500000, "points": 30},
    "AUMENTO_PENDENTE": {"delay_hours": 24, "ratio": 0.5, "points": 40},
    "SONDAGEM_DE_LIMITE": {"window_minutes": 15, "one": 30, "two": 50},
    "NOTURNO": {"start_hour": 20, "end_hour": 6, "min_amount": 100000, "points": 25},
    "PADRAO_MENSAL": {"months": 3, "min_amount": 100000, "tolerance_days": 2, "share": 0.6, "min_per_month": 2, "multiple": 3, "points": 25},
    "APARELHO_NOVO": {"min_prior_attempts": 3, "points": 20},
    "REDE_NOVA": {"min_prior_attempts": 3, "points": 15},
    "VIAGEM_IMPOSSIVEL": {"max_kmh": 900, "min_km_gps": 100, "min_km_ip": 500, "points": 40},
    "GEO_IP_DIVERGENTE": {"km": 500, "points": 30},
    "AMBIENTE_INCOERENTE": {"points": 20},
    "GEO_AUSENTE": {"points": {"app": 20, "web": 20, "api": 0}},
    "APARELHO_COMPARTILHADO": {"days": 30, "min_documents": 3, "points": 25},
    "IP_COMPARTILHADO": {"window_minutes": 60, "min_documents": 5, "points": 15},
    "DESTINO_NOVO": {"days": 30, "points": 20, "very_new_hours": 24, "very_new_points": 30},
    "CONTRAPARTE_INEDITA": {"min_amount": 100000, "points": 15},
    "CONTA_LARANJA": {
        "window_minutes": 60, "new_destination_days": 30,
        "fallback_new": [{"count": 10, "points": 60}, {"count": 5, "points": 40}],
        "fallback_old": [{"count": 10, "points": 30}, {"count": 5, "points": 20}],
        "moderate": {"minimum": 5, "multiple": 2, "k": 3, "points": 40},
        "high": {"minimum": 10, "multiple": 3, "k": 6, "points": 60}
    },
    "REPASSE_RAPIDO": {"window_minutes": 60, "min_payers": 3, "share": 0.8, "points": 60, "inconclusive_points": 20},
    "COORDENACAO_ENTRE_CONTAS": {"window_minutes": 10, "min_documents": 3, "destination_max_days": 7, "points": 40},
    "REDE_SUSPEITA": {"days": 30, "points": 30},
    "REPUTACAO_EXTERNA": {"alert_points": 40, "min_reporters": 1, "application_fraud_new_account_days": 90, "application_fraud_same_holder_days": 30},
    "REPUTACAO_INTERNA": {"points": 40},
    "MESMA_TITULARIDADE": {"discount": 10},
    "DESTINO_CONFIAVEL": {"discount": 10, "min_payments": 3, "min_days": 3, "min_span_days": 7},
    "DATA_RETROATIVA": {"tolerance_seconds": 300},
    "RUPTURA_DE_CONTEXTO": {"far_km": 50, "geo_min_points": 5, "geo_min_days": 3, "geo_window_days": 90, "history_min_payments": 10, "history_min_days": 3}
}');

-- ------------------------------------------------------------
-- 3. AS CONTAS QUE O MOTOR JA VIU
-- ------------------------------------------------------------
-- Uma linha por conta (instituicao + agencia + numero). A conta pagadora
-- chega sem `participant`: ela leva o ISPB da casa (OWN_PARTICIPANT).
-- O documento fica so em digitos: a mascara nao define outra pessoa.

CREATE TABLE pix_account(
    id BIGSERIAL PRIMARY KEY,
    participant CHAR(8) NOT NULL,
    branch VARCHAR(4) NOT NULL,
    account_number VARCHAR(20) NOT NULL,
    opening_date TIMESTAMPTZ NOT NULL,
    owner_document VARCHAR(14) NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT pix_account_unique UNIQUE (participant, branch, account_number)
);

-- ------------------------------------------------------------
-- 4. A ANALISE DE CADA PIX
-- ------------------------------------------------------------
-- O id do Pix e a chave do replay. Os documentos e o IP sao repetidos
-- aqui, em vez de lidos pela conta, porque sao as colunas das consultas
-- de historico que rodam em todo Pix, e cada uma tem o seu indice.

CREATE TABLE pix_analysis(
    id BIGSERIAL PRIMARY KEY,
    analysis_key CHAR(36) NOT NULL UNIQUE,
    pix_id VARCHAR(64) NOT NULL UNIQUE,
    request_hash CHAR(64) NOT NULL,
    status_id SMALLINT NOT NULL REFERENCES pix_status(id),
    risk_score SMALLINT NOT NULL CHECK (risk_score BETWEEN 0 AND 100),
    authentication_level VARCHAR(20) NOT NULL CHECK (authentication_level IN ('none', 'facial', 'facial_document')),
    scenario VARCHAR(40) NOT NULL,
    reason VARCHAR(40) NOT NULL,
    source_account_id BIGINT NOT NULL REFERENCES pix_account(id),
    destination_account_id BIGINT NOT NULL REFERENCES pix_account(id),
    source_document VARCHAR(14) NOT NULL,
    destination_document VARCHAR(14) NOT NULL,
    amount BIGINT NOT NULL CHECK (amount > 0),
    transaction_date TIMESTAMPTZ NOT NULL,
    device_id VARCHAR(64) NOT NULL,
    channel VARCHAR(10) NOT NULL,
    ip INET NOT NULL,
    ip_network CIDR NOT NULL,
    latitude NUMERIC(9, 6),
    longitude NUMERIC(9, 6),
    ip_latitude NUMERIC(9, 6),
    ip_longitude NUMERIC(9, 6),
    ip_location_source VARCHAR(10) NOT NULL,
    policy_id INTEGER NOT NULL REFERENCES fraud_policy(id),
    metadata JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX pix_analysis_source_account ON pix_analysis (source_account_id, transaction_date DESC);
CREATE INDEX pix_analysis_destination_account ON pix_analysis (destination_account_id, transaction_date DESC);
CREATE INDEX pix_analysis_source_document ON pix_analysis (source_document, transaction_date DESC);
CREATE INDEX pix_analysis_destination_document ON pix_analysis (destination_document, transaction_date DESC);
CREATE INDEX pix_analysis_device ON pix_analysis (device_id, transaction_date DESC);
CREATE INDEX pix_analysis_ip ON pix_analysis (ip, transaction_date DESC);
CREATE INDEX pix_analysis_ip_network ON pix_analysis (ip_network, transaction_date DESC);

CREATE TRIGGER pix_analysis_is_append_only
    BEFORE UPDATE OR DELETE ON pix_analysis
    FOR EACH ROW EXECUTE FUNCTION refuse_change();

-- Uma linha por regra avaliada, inclusive as que nao dispararam: e a
-- fotografia de como a decisao foi tomada.
CREATE TABLE pix_rule_result(
    id BIGSERIAL PRIMARY KEY,
    analysis_id BIGINT NOT NULL REFERENCES pix_analysis(id),
    rule VARCHAR(40) NOT NULL,
    evaluation VARCHAR(15) NOT NULL CHECK (evaluation IN ('triggered', 'not_triggered', 'not_evaluable')),
    axis VARCHAR(15),
    family VARCHAR(30),
    raw_points SMALLINT NOT NULL,
    effective_points SMALLINT NOT NULL,
    hard_block BOOLEAN NOT NULL,
    authentication_floor VARCHAR(20) NOT NULL,
    detail TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT pix_rule_result_unique UNIQUE (analysis_id, rule)
);

CREATE TRIGGER pix_rule_result_is_append_only
    BEFORE UPDATE OR DELETE ON pix_rule_result
    FOR EACH ROW EXECUTE FUNCTION refuse_change();

-- ------------------------------------------------------------
-- 5. O LIMITE QUE O PROPRIO CLIENTE ESCOLHE
-- ------------------------------------------------------------
-- Reduzir vale na hora; aumentar so vale 24 horas depois do pedido. O
-- limite vigente num instante e a linha de effective_from mais recente
-- que ja comecou a valer.

CREATE TABLE account_limit(
    id BIGSERIAL PRIMARY KEY,
    account_id BIGINT NOT NULL REFERENCES pix_account(id),
    amount BIGINT NOT NULL CHECK (amount > 0),
    change_type VARCHAR(10) NOT NULL CHECK (change_type IN ('initial', 'decrease', 'increase', 'same')),
    requested_at TIMESTAMPTZ NOT NULL,
    effective_from TIMESTAMPTZ NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CHECK (effective_from >= requested_at)
);

CREATE INDEX account_limit_account ON account_limit (account_id, effective_from DESC);

CREATE TRIGGER account_limit_is_append_only
    BEFORE UPDATE OR DELETE ON account_limit
    FOR EACH ROW EXECUTE FUNCTION refuse_change();

-- ------------------------------------------------------------
-- 6. REPUTACAO: O MOCK EXTERNO E A LISTA INTERNA
-- ------------------------------------------------------------
-- O mock imita o formato do `destination_statistics` da API Pix da QI
-- (contadores de fraude do DICT por janela: d90, m12, m60). E ficticio,
-- determinístico e marcado como tal.

CREATE TABLE reputation_fixture(
    id SERIAL PRIMARY KEY,
    document VARCHAR(14) NOT NULL,
    scope VARCHAR(10) NOT NULL CHECK (scope IN ('person', 'owner')),
    statistics JSONB NOT NULL,
    entity_role VARCHAR(30) NOT NULL CHECK (entity_role IN ('suspected_perpetrator', 'victim', 'unknown')),
    evidence_id VARCHAR(40) NOT NULL UNIQUE,
    available_from TIMESTAMPTZ NOT NULL,
    expires_at TIMESTAMPTZ NOT NULL,
    fixture_version VARCHAR(30) NOT NULL,
    is_mock BOOLEAN NOT NULL DEFAULT TRUE,
    CHECK (expires_at > available_from)
);

CREATE INDEX reputation_fixture_document ON reputation_fixture (document);

-- A lista interna: casos confirmados, semeados, ou o "nao fui eu" do
-- titular depois de um desafio. Nunca a decisao do proprio motor.
CREATE TABLE watchlist(
    id BIGSERIAL PRIMARY KEY,
    kind VARCHAR(10) NOT NULL CHECK (kind IN ('device', 'document')),
    value VARCHAR(64) NOT NULL,
    report_type VARCHAR(12) NOT NULL CHECK (report_type IN ('fraud', 'compliance')),
    creator VARCHAR(10) NOT NULL CHECK (creator IN ('client', 'external')),
    evidence_id VARCHAR(80) NOT NULL UNIQUE,
    available_from TIMESTAMPTZ NOT NULL,
    expires_at TIMESTAMPTZ NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CHECK (expires_at > available_from)
);

CREATE INDEX watchlist_lookup ON watchlist (kind, value, available_from, expires_at);

CREATE TRIGGER watchlist_is_append_only
    BEFORE UPDATE OR DELETE ON watchlist
    FOR EACH ROW EXECUTE FUNCTION refuse_change();

-- ------------------------------------------------------------
-- 7. ONDE FICA CADA FAIXA DE IP
-- ------------------------------------------------------------
-- No hackathon, faixas de documentacao com lugares ficticios (mock). Em
-- producao, a mesma tabela receberia uma base real de geolocalizacao de
-- IP, e o motor nao mudaria.

CREATE TABLE ip_range_location(
    id SERIAL PRIMARY KEY,
    network CIDR NOT NULL UNIQUE,
    latitude NUMERIC(9, 6) NOT NULL,
    longitude NUMERIC(9, 6) NOT NULL,
    country CHAR(2) NOT NULL,
    source VARCHAR(10) NOT NULL CHECK (source IN ('mock', 'dbip')),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX ip_range_location_network ON ip_range_location USING gist (network inet_ops);

-- ------------------------------------------------------------
-- 8. O RESULTADO DO DESAFIO (2FA), QUANDO O CLIENTE INFORMA
-- ------------------------------------------------------------

CREATE TABLE pix_challenge_result(
    id BIGSERIAL PRIMARY KEY,
    analysis_id BIGINT NOT NULL UNIQUE REFERENCES pix_analysis(id),
    result VARCHAR(25) NOT NULL CHECK (result IN ('approved_by_client', 'reproved_by_client')),
    event_date TIMESTAMPTZ NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TRIGGER pix_challenge_result_is_append_only
    BEFORE UPDATE OR DELETE ON pix_challenge_result
    FOR EACH ROW EXECUTE FUNCTION refuse_change();

-- ------------------------------------------------------------
-- 9. SEEDS DE DEMONSTRACAO (TODOS FICTICIOS)
-- ------------------------------------------------------------

INSERT INTO reputation_fixture (document, scope, statistics, entity_role, evidence_id, available_from, expires_at, fixture_version) VALUES
    ('52998224725', 'person',
     '{"mule_accounts": {"d90": 1, "m12": 1, "m60": 1}, "scammer_accounts": {"d90": 0, "m12": 0, "m60": 0}, "application_frauds": {"d90": 0, "m12": 0, "m60": 0}, "distinct_fraud_reporters": {"d90": 2, "m12": 2, "m60": 2}, "open_reports": 1, "rejected_reports": {"d90": 0, "m12": 0, "m60": 0}, "settlements": {"d90": 3, "m12": 3, "m60": 3}}',
     'suspected_perpetrator', 'mock-evidence-001', '2020-01-01T00:00:00-03:00', '2030-01-01T00:00:00-03:00', '2026-10-17-v1'),
    ('11144477735', 'person',
     '{"mule_accounts": {"d90": 0, "m12": 0, "m60": 0}, "scammer_accounts": {"d90": 0, "m12": 0, "m60": 0}, "application_frauds": {"d90": 0, "m12": 0, "m60": 0}, "distinct_fraud_reporters": {"d90": 1, "m12": 1, "m60": 1}, "open_reports": 1, "rejected_reports": {"d90": 0, "m12": 0, "m60": 0}, "settlements": {"d90": 40, "m12": 120, "m60": 300}}',
     'suspected_perpetrator', 'mock-evidence-002', '2020-01-01T00:00:00-03:00', '2030-01-01T00:00:00-03:00', '2026-10-17-v1'),
    ('39053344705', 'person',
     '{"mule_accounts": {"d90": 1, "m12": 1, "m60": 1}, "scammer_accounts": {"d90": 0, "m12": 0, "m60": 0}, "application_frauds": {"d90": 0, "m12": 0, "m60": 0}, "distinct_fraud_reporters": {"d90": 3, "m12": 3, "m60": 3}, "open_reports": 2, "rejected_reports": {"d90": 0, "m12": 0, "m60": 0}, "settlements": {"d90": 0, "m12": 0, "m60": 0}}',
     'suspected_perpetrator', 'mock-evidence-003', '2018-01-01T00:00:00-03:00', '2019-01-01T00:00:00-03:00', '2026-10-17-v1'),
    ('12345678909', 'person',
     '{"mule_accounts": {"d90": 0, "m12": 0, "m60": 0}, "scammer_accounts": {"d90": 0, "m12": 0, "m60": 0}, "application_frauds": {"d90": 2, "m12": 2, "m60": 2}, "distinct_fraud_reporters": {"d90": 2, "m12": 2, "m60": 2}, "open_reports": 0, "rejected_reports": {"d90": 0, "m12": 0, "m60": 0}, "settlements": {"d90": 10, "m12": 30, "m60": 80}}',
     'victim', 'mock-evidence-004', '2020-01-01T00:00:00-03:00', '2030-01-01T00:00:00-03:00', '2026-10-17-v1'),
    -- Uma marcacao de laranja confirmada em 90 dias, por um denunciante so.
    ('37024556803', 'person',
     '{"mule_accounts": {"d90": 1, "m12": 1, "m60": 1}, "scammer_accounts": {"d90": 0, "m12": 0, "m60": 0}, "application_frauds": {"d90": 0, "m12": 0, "m60": 0}, "distinct_fraud_reporters": {"d90": 1, "m12": 1, "m60": 1}, "open_reports": 0, "rejected_reports": {"d90": 0, "m12": 0, "m60": 0}, "settlements": {"d90": 12, "m12": 12, "m60": 12}}',
     'suspected_perpetrator', 'mock-evidence-005', '2020-01-01T00:00:00-03:00', '2030-01-01T00:00:00-03:00', '2026-10-17-v2');

INSERT INTO watchlist (kind, value, report_type, creator, evidence_id, available_from, expires_at) VALUES
    ('document', '27548438923', 'fraud', 'external', 'seed-watchlist-document-001', '2020-01-01T00:00:00-03:00', '2030-01-01T00:00:00-03:00'),
    ('device', 'dvc-watchlist-0001', 'fraud', 'external', 'seed-watchlist-device-001', '2020-01-01T00:00:00-03:00', '2030-01-01T00:00:00-03:00');

INSERT INTO ip_range_location (network, latitude, longitude, country, source) VALUES
    ('198.51.100.0/24', -23.560000, -46.650000, 'BR', 'mock'),
    ('203.0.113.0/24', -8.050000, -34.900000, 'BR', 'mock'),
    ('192.0.2.0/24', 38.720000, -9.140000, 'PT', 'mock');
