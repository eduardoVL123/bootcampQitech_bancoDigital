-- =====================================================================
-- Banco Digital · Bootcamp QI Tech 2026
-- Escopo: o minimo exigido pelo desafio (cliente, conta, transacao,
-- tarifa, extrato), mais a abertura de conta (onboarding, secao 7).
-- Investimento fica para depois.
--
-- Este arquivo roda SOZINHO, uma unica vez, quando o volume do Postgres
-- nasce. Mudou alguma coisa aqui? Entao:
--     docker compose down -v && docker compose up --build
-- Sem o -v o banco antigo continua la e a mudanca nao aparece. O erro
-- que voce vai ver e "relation ... does not exist", e ele mente: parece
-- erro de digitacao, mas e volume velho.
--
-- Convencoes, iguais em todas as tabelas:
--   id BIGSERIAL  -> chave interna, nunca sai numa resposta
--   ..._key CHAR(36) -> chave publica (UUID), e o que o cliente ve
--   dinheiro em BIGINT de centavos, nunca float
--   TIMESTAMPTZ em tudo que e data e hora
--   estado = tabela de lookup + tabela de evento com o historico
-- =====================================================================


-- =====================================================================
-- 1. CLIENTE
-- Tabelas que a customer-api do Eduardo ja espera: os models dele
-- (src/models/customer.py) apontam para estes nomes de tabela e de
-- coluna, e hoje elas nao existem no database.sql da branch dele.
-- Quem grava o cliente e a onboarding-api, no mesmo COMMIT da abertura
-- (RFC 05). O request_key recebe a onboarding_key da abertura. O RG da
-- abertura fica em onboarding_document (secao 7), e nao aqui.
-- =====================================================================

CREATE TABLE customer_type(
    id                  BIGSERIAL PRIMARY KEY,
    enumerator          VARCHAR(2) NOT NULL,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT(NOW()),
    UNIQUE(enumerator)
);

INSERT INTO customer_type (enumerator) VALUES ('PF'), ('PJ');


CREATE TABLE customer(
    id                  BIGSERIAL PRIMARY KEY,
    customer_key        CHAR(36) NOT NULL,
    -- Recebe a chave do pedido de quem chamou. E o que impede a mesma
    -- pessoa nascer duas vezes quando a rede cai e o pedido e repetido.
    request_key         CHAR(36) NOT NULL,
    type_id             BIGINT NOT NULL REFERENCES customer_type(id),
    name                VARCHAR(255) NOT NULL,
    document_number     VARCHAR(18) NOT NULL,
    birth_date          DATE,
    opening_date        DATE,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT(NOW()),
    updated_at          TIMESTAMPTZ,
    UNIQUE(customer_key),
    UNIQUE(request_key),
    UNIQUE(document_number),
    -- PF tem nascimento, PJ tem abertura. Nunca os dois, nunca nenhum.
    -- Isso e a regra virando constraint, em vez de um if no controller.
    CHECK ((birth_date IS NOT NULL) <> (opening_date IS NOT NULL))
);


-- EXTRA, fora do minimo do desafio: a foto do RG.
-- Conferida contra src/models/customer_document.py da branch
-- feat/customer-api-mvp: colunas, tipos, nulabilidade e nome do indice
-- unico batem com o model.
CREATE TABLE customer_document(
    id                  BIGSERIAL PRIMARY KEY,
    customer_id         BIGINT NOT NULL REFERENCES customer(id),
    document_type       VARCHAR(20) NOT NULL,
    -- Nulavel e VARCHAR(10) para bater com o model do Eduardo
    -- (src/models/customer_document.py). Com side nulo o Postgres trata
    -- cada NULL como distinto, entao o UNIQUE abaixo nao barra: e a
    -- escolha dele, e o schema segue o codigo que ja existe.
    side                VARCHAR(10),
    -- Caminho no bucket. A foto NUNCA entra no Postgres.
    object_key          VARCHAR(255) NOT NULL,
    content_type        VARCHAR(50) NOT NULL,
    size_bytes          BIGINT NOT NULL,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT(NOW()),
    -- Nome igual ao do model dele, para o erro de integridade chegar no
    -- controller com o nome que o codigo dele procura.
    CONSTRAINT uq_customer_document_side UNIQUE (customer_id, document_type, side),
    UNIQUE(object_key),
    CHECK (size_bytes > 0 AND size_bytes <= 5242880)
);


-- =====================================================================
-- 2. CONTA
-- =====================================================================

CREATE TABLE account_status(
    id                  BIGSERIAL PRIMARY KEY,
    enumerator          VARCHAR(20) NOT NULL,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT(NOW()),
    UNIQUE(enumerator)
);

INSERT INTO account_status (enumerator) VALUES ('ACTIVE'), ('BLOCKED'), ('CLOSED');


CREATE TABLE account_status_reason(
    id                  BIGSERIAL PRIMARY KEY,
    enumerator          VARCHAR(30) NOT NULL,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT(NOW()),
    UNIQUE(enumerator)
);

INSERT INTO account_status_reason (enumerator) VALUES ('OPERATOR'), ('SUSPICIOUS_ACTIVITY');


CREATE TABLE account(
    id                  BIGSERIAL PRIMARY KEY,
    account_key         CHAR(36) NOT NULL,
    -- Conta de cliente: customer_id preenchido, code nulo.
    -- Conta tecnica do banco: code preenchido, customer_id nulo.
    customer_id         BIGINT REFERENCES customer(id),
    code                VARCHAR(30),
    status_id           BIGINT NOT NULL REFERENCES account_status(id),
    -- Saldo em centavos. E um atalho de leitura: a verdade historica e
    -- o livro (ledger_entry). Os dois sao escritos no mesmo commit.
    -- NULO em conta tecnica, de proposito: sem linha de saldo nao ha o
    -- que travar, e a conta de tarifa deixa de serializar o banco todo.
    balance             BIGINT,
    -- Numera o livro DESTA conta. So conta de cliente usa.
    last_sequence       BIGINT NOT NULL DEFAULT 0,
    closed_at           TIMESTAMPTZ,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT(NOW()),
    updated_at          TIMESTAMPTZ,
    UNIQUE(account_key),
    UNIQUE(code),
    -- Ou e de cliente, ou e tecnica. Nunca as duas, nunca nenhuma.
    CHECK ((customer_id IS NULL) = (code IS NOT NULL)),
    -- Quem tem dono tem saldo; conta tecnica nao tem.
    CHECK ((customer_id IS NOT NULL) = (balance IS NOT NULL)),
    -- Ultima linha de defesa. A primeira e a trava no controller.
    CHECK (balance IS NULL OR balance >= 0)
);

-- No maximo UMA conta nao encerrada por cliente.
-- Indice parcial, e nao checagem no controller: entre o SELECT e o
-- INSERT cabe outra requisicao, e o indice nao deixa passar.
-- Usa closed_at em vez de status_id porque status_id e um numero que o
-- banco sorteou na tabela de lookup, e amarrar regra a numero sorteado
-- e o erro que a implementacao de referencia da QI recusa fazer.
CREATE UNIQUE INDEX account_one_open_per_customer
    ON account (customer_id)
    WHERE closed_at IS NULL AND customer_id IS NOT NULL;


CREATE TABLE account_status_event(
    id                  BIGSERIAL PRIMARY KEY,
    account_id          BIGINT NOT NULL REFERENCES account(id),
    status_id           BIGINT NOT NULL REFERENCES account_status(id),
    reason_id           BIGINT REFERENCES account_status_reason(id),
    event_datetime      TIMESTAMPTZ NOT NULL,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT(NOW())
);


-- As contas tecnicas do banco. Nascem com o schema porque o sistema
-- nao funciona sem elas: a tarifa de toda transferencia cai no
-- FEE_HOLD, e o depostito tem SETTLEMENT como contrapartida.
-- INVESTMENT_CUSTODY e YIELD_EXPENSE ficaram de fora: sao da caixinha,
-- que esta fora do escopo de agora.
INSERT INTO account (account_key, code, status_id)
SELECT gen_random_uuid()::TEXT,
       t.code,
       (SELECT id FROM account_status WHERE enumerator = 'ACTIVE')
  FROM (VALUES ('FEE_HOLD'), ('FEE_REVENUE'), ('SETTLEMENT')) AS t(code);


-- =====================================================================
-- 3. TRANSACAO E TARIFA
-- =====================================================================

CREATE TABLE transaction_type(
    id                  BIGSERIAL PRIMARY KEY,
    enumerator          VARCHAR(20) NOT NULL,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT(NOW()),
    UNIQUE(enumerator)
);

INSERT INTO transaction_type (enumerator) VALUES ('DEPOSIT'), ('WITHDRAWAL'), ('TRANSFER');


CREATE TABLE transaction_status(
    id                  BIGSERIAL PRIMARY KEY,
    enumerator          VARCHAR(20) NOT NULL,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT(NOW()),
    UNIQUE(enumerator)
);

INSERT INTO transaction_status (enumerator) VALUES ('PENDING'), ('COMPLETED'), ('FAILED');


-- Tarifa nao se edita: cria-se outra politica. E o que permite provar
-- depois por que aquela transferencia cobrou aquele valor.
CREATE TABLE fee_policy(
    id                  BIGSERIAL PRIMARY KEY,
    fee_policy_key      CHAR(36) NOT NULL,
    transfer_fee_cents  BIGINT NOT NULL,
    valid_from          TIMESTAMPTZ NOT NULL,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT(NOW()),
    UNIQUE(fee_policy_key),
    CHECK (transfer_fee_cents >= 0)
);

-- R$ 2,00, o valor do exemplo da apresentacao. E escolha do time, nao
-- regra da QI Tech.
INSERT INTO fee_policy (fee_policy_key, transfer_fee_cents, valid_from)
VALUES (gen_random_uuid()::TEXT, 200, NOW());


CREATE TABLE transaction(
    id                      BIGSERIAL PRIMARY KEY,
    transaction_key         CHAR(36) NOT NULL,
    -- Chave que o cliente manda. Mesma chave + mesmo pedido devolve o
    -- original; mesma chave + outro pedido e conflito. O request_hash
    -- guarda o SHA-256 do pedido, e nao o pedido: nada de CPF aqui.
    idempotency_key         VARCHAR(64) NOT NULL,
    request_hash            CHAR(64) NOT NULL,
    type_id                 BIGINT NOT NULL REFERENCES transaction_type(id),
    status_id               BIGINT NOT NULL REFERENCES transaction_status(id),
    fee_policy_id           BIGINT REFERENCES fee_policy(id),
    origin_account_id       BIGINT REFERENCES account(id),
    destination_account_id  BIGINT REFERENCES account(id),
    amount                  BIGINT NOT NULL,
    -- Copiado da politica no momento da operacao, nunca recalculado
    -- depois. E o que faz a tarifa antiga sobreviver a mudanca da regra.
    fee_amount              BIGINT NOT NULL DEFAULT 0,
    failure_code            VARCHAR(9),
    created_at              TIMESTAMPTZ NOT NULL DEFAULT(NOW()),
    updated_at              TIMESTAMPTZ,
    UNIQUE(transaction_key),
    UNIQUE(idempotency_key),
    CHECK (amount > 0),
    CHECK (fee_amount >= 0),
    -- Toda transacao mexe em pelo menos uma conta.
    CHECK (origin_account_id IS NOT NULL OR destination_account_id IS NOT NULL),
    -- Ninguem transfere para si mesmo.
    CHECK (origin_account_id IS DISTINCT FROM destination_account_id)
);
-- EM ABERTO, para decidir com o time: a regra "deposito nao tem origem,
-- saque nao tem destino, transferencia tem os dois" NAO esta aqui.
-- Um CHECK so enxerga as colunas da propria linha, e nao consegue ler o
-- enumerator la na transaction_type para saber de que tipo ela e.
-- As saidas sao: (a) uma trigger, (b) guardar o tipo como texto tambem
-- nesta linha, ou (c) deixar a regra no controller com teste cobrindo.
-- Os dois CHECK acima ja barram o pior caso.


CREATE TABLE transaction_status_event(
    id                  BIGSERIAL PRIMARY KEY,
    transaction_id      BIGINT NOT NULL REFERENCES transaction(id),
    status_id           BIGINT NOT NULL REFERENCES transaction_status(id),
    event_datetime      TIMESTAMPTZ NOT NULL,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT(NOW())
);


-- =====================================================================
-- 4. O LIVRO: onde o dinheiro realmente acontece
--
-- Um POSTING e um conjunto de lancamentos que SOMA ZERO, gravados numa
-- transacao ACID so. Uma transferencia de R$ 100 com R$ 2 de tarifa
-- vira quatro lancamentos: -10000 e -200 na origem, +10000 no destino,
-- +200 no FEE_HOLD. Somados: zero.
--
-- E isso que permite a conciliacao: somar TODOS os lancamentos de
-- TODAS as contas tem de dar zero. Se nao der, tem bug, e o teste
-- descobre sozinho.
-- =====================================================================

CREATE TABLE posting_type(
    id                  BIGSERIAL PRIMARY KEY,
    enumerator          VARCHAR(30) NOT NULL,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT(NOW()),
    UNIQUE(enumerator)
);

INSERT INTO posting_type (enumerator) VALUES
('DEPOSIT'), ('WITHDRAWAL'), ('TRANSFER'), ('FEE_APPROPRIATION');


CREATE TABLE posting(
    id                  BIGSERIAL PRIMARY KEY,
    posting_key         CHAR(36) NOT NULL,
    type_id             BIGINT NOT NULL REFERENCES posting_type(id),
    -- UNIQUE: uma transacao gera no maximo UM posting. E o indice que
    -- impede o clique duplo virar dois conjuntos de lancamentos.
    -- Quando a caixinha voltar ao escopo, esta coluna vira NULA para os
    -- postings de rendimento, que nao vem de transacao.
    transaction_id      BIGINT NOT NULL REFERENCES transaction(id),
    created_at          TIMESTAMPTZ NOT NULL DEFAULT(NOW()),
    UNIQUE(posting_key),
    UNIQUE(transaction_id)
);


CREATE TABLE ledger_entry(
    id                  BIGSERIAL PRIMARY KEY,
    entry_key           CHAR(36) NOT NULL,
    posting_id          BIGINT NOT NULL REFERENCES posting(id),
    account_id          BIGINT NOT NULL REFERENCES account(id),
    -- Centavos COM SINAL: negativo sai, positivo entra.
    amount              BIGINT NOT NULL,
    -- Saldo da conta depois deste lancamento. E o que faz o extrato
    -- provar o saldo sozinho, sem recalcular nada.
    balance_after       BIGINT,
    -- Numero de ordem dentro da conta. O extrato pagina por ele, e nao
    -- por offset: o livro recebe escrita o tempo todo, e offset
    -- duplicaria itens entre uma pagina e a seguinte.
    sequence            BIGINT,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT(NOW()),
    UNIQUE(entry_key),
    UNIQUE(account_id, sequence),
    CHECK (amount <> 0),
    -- Lancamento de conta tecnica nao tem numero nem saldo depois: e um
    -- INSERT puro, sem ler nada da linha da conta. E isso que impede a
    -- conta de tarifa de virar fila de espera do banco inteiro.
    CHECK ((sequence IS NULL) = (balance_after IS NULL))
);

CREATE INDEX ledger_entry_account_sequence ON ledger_entry (account_id, sequence DESC);


-- =====================================================================
-- 5. O QUE O BANCO RECUSA SOZINHO
-- =====================================================================

-- Append-only (restricao R4). Corrigir um lancamento errado e lancar
-- outro por cima, nunca editar o que ja aconteceu. Garantido aqui, e
-- nao por disciplina de quem escreve o controller.
-- Sem nenhum sinal de porcento na mensagem, de proposito: o
-- tests/utils/db_utils.py reexecuta este arquivo pelo psycopg2, que
-- trata porcento como marcador de parametro e quebra a suite inteira.
-- Por isso RAISE ... USING MESSAGE com concatenacao, e nao o formato
-- com placeholder.
CREATE OR REPLACE FUNCTION refuse_change() RETURNS TRIGGER AS $$
BEGIN
    RAISE EXCEPTION USING MESSAGE =
        'a tabela ' || TG_TABLE_NAME || ' e append-only: ' || TG_OP || ' nao e permitido';
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER posting_is_append_only
    BEFORE UPDATE OR DELETE ON posting
    FOR EACH STATEMENT EXECUTE FUNCTION refuse_change();

CREATE TRIGGER ledger_entry_is_append_only
    BEFORE UPDATE OR DELETE ON ledger_entry
    FOR EACH STATEMENT EXECUTE FUNCTION refuse_change();

CREATE TRIGGER fee_policy_is_append_only
    BEFORE UPDATE OR DELETE ON fee_policy
    FOR EACH STATEMENT EXECUTE FUNCTION refuse_change();


-- A soma zero. Um CHECK enxerga uma linha por vez, entao nao existe
-- CHECK que diga "a soma deste posting e zero". Uma CONSTRAINT TRIGGER
-- adiada consegue: ela so roda no COMMIT, quando os quatro lancamentos
-- ja estao todos la, e derruba a transacao inteira se nao fechar.
-- E a diferenca entre "a gente garante" e "o banco recusa".
CREATE OR REPLACE FUNCTION posting_must_sum_zero() RETURNS TRIGGER AS $$
DECLARE
    total BIGINT;
BEGIN
    SELECT SUM(amount) INTO total FROM ledger_entry WHERE posting_id = NEW.posting_id;
    IF total <> 0 THEN
        RAISE EXCEPTION USING MESSAGE =
            'posting ' || NEW.posting_id || ' nao soma zero: soma = ' || total;
    END IF;
    RETURN NULL;
END;
$$ LANGUAGE plpgsql;

CREATE CONSTRAINT TRIGGER ledger_entry_must_sum_zero
    AFTER INSERT ON ledger_entry
    DEFERRABLE INITIALLY DEFERRED
    FOR EACH ROW EXECUTE FUNCTION posting_must_sum_zero();


-- =====================================================================
-- 6. SAI ANTES DA ENTREGA
-- A entidade de exemplo que veio no projeto base. Fica enquanto o
-- codigo dela existir em src/, e sai junto com ele.
-- =====================================================================

CREATE TABLE sample_entity_status(
    id		                        SERIAL PRIMARY KEY,
    enumerator                      VARCHAR(50) NOT NULL,
    created_at                      TIMESTAMP NOT NULL DEFAULT(NOW()),
    UNIQUE(enumerator)
);

INSERT INTO sample_entity_status (enumerator) VALUES
('created'), ('pending'), ('success'), ('failed');

CREATE TABLE sample_entity(
    id                              SERIAL PRIMARY KEY,
    sample_entity_key               CHAR(36) NOT NULL,
    status_id                       INTEGER NOT NULL REFERENCES sample_entity_status(id),
    sample_entity_data              JSONB NOT NULL,
    name                            VARCHAR(255) NOT NULL,
    email                           VARCHAR(255) NOT NULL,
    document_number                 CHAR(14) NOT NULL,
    birthdate                       DATE NOT NULL,
    counter                         INTEGER NOT NULL,
    created_at                      TIMESTAMP NOT NULL DEFAULT(NOW()),
    UNIQUE(sample_entity_key),
    UNIQUE(document_number),
    UNIQUE(email)
);

CREATE TABLE sample_entity_status_event(
    id                              SERIAL PRIMARY KEY,
    sample_entity_id                INTEGER NOT NULL REFERENCES sample_entity(id),
    status_id                       INTEGER NOT NULL REFERENCES sample_entity_status(id),
    event_datetime                  TIMESTAMP NOT NULL,
    created_at                      TIMESTAMP NOT NULL DEFAULT(NOW())
);


-- =====================================================================
-- 7. ABERTURA DE CONTA (onboarding-api, RFC 05)
--
-- A onboarding-api e a dona do cliente: grava o customer e a abertura
-- no mesmo COMMIT, e o RG da abertura em onboarding_document. Renda, ocupacao e PEP
-- sao dados da analise desta abertura (KYC e PLD), e por isso moram aqui,
-- e nao no customer. Se a abertura vence sem terminar, eles sao apagados
-- junto com o cadastro (LGPD).
-- =====================================================================

CREATE TABLE onboarding_status(
    id                  BIGSERIAL PRIMARY KEY,
    enumerator          VARCHAR(20) NOT NULL,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT(NOW()),
    UNIQUE(enumerator)
);

INSERT INTO onboarding_status (enumerator) VALUES
('DRAFT'), ('PENDING_KYC'), ('ANALYSIS'), ('MANUAL_REVIEW'),
('APPROVED'), ('ACTIVE'), ('REJECTED'), ('EXPIRED');


CREATE TABLE onboarding(
    id                      BIGSERIAL PRIMARY KEY,
    onboarding_key          CHAR(36) NOT NULL,
    -- Nulo depois de vencer: o cadastro e apagado.
    customer_id             BIGINT REFERENCES customer(id),
    -- A chave do cliente, que fica depois de vencer: e por ela que a API
    -- reconhece o dono da abertura, porque a credencial traz a customer_key.
    -- E um UUID, e nao dado pessoal (decisao D24).
    customer_key            CHAR(36) NOT NULL,
    -- Repassada pelo gateway. O UNIQUE e a garantia final de que repetir
    -- o pedido nao cria outra abertura, mesmo se o Redis perder a chave.
    idempotency_key         VARCHAR(64) NOT NULL,
    -- SHA-256 do pedido: compara dois pedidos sem guardar os dados.
    request_hash            CHAR(64) NOT NULL,
    status_id               BIGINT NOT NULL REFERENCES onboarding_status(id),
    -- Dados do KYC e do PLD, em centavos a renda. Nulos depois de vencer.
    declared_monthly_income BIGINT,
    occupation              VARCHAR(100),
    pep_self_declared       BOOLEAN,
    -- Quem cria a conta e a account-api, pela rota interna. Sem FK: a
    -- tabela account e dela.
    account_key             CHAR(36),
    risk_level              VARCHAR(6),
    reason_codes            VARCHAR(200),
    analysis_attempts       INTEGER NOT NULL DEFAULT 0,
    next_attempt_at         TIMESTAMPTZ,
    lease_until             TIMESTAMPTZ,
    -- 20 minutos depois do POST /onboarding.
    expires_at              TIMESTAMPTZ NOT NULL,
    created_at              TIMESTAMPTZ NOT NULL DEFAULT(NOW()),
    updated_at              TIMESTAMPTZ,
    UNIQUE(onboarding_key),
    -- Uma abertura por cliente.
    UNIQUE(customer_id),
    UNIQUE(idempotency_key),
    CHECK (declared_monthly_income IS NULL OR declared_monthly_income >= 0),
    CHECK (risk_level IN ('LOW', 'MEDIUM', 'HIGH')),
    CHECK (analysis_attempts >= 0)
);


-- O RG da abertura: frente e verso, ou uma imagem com os dois lados. A
-- foto fica no bucket; aqui so o caminho, o tipo e o tamanho. Fica com a
-- abertura, e nao com o cliente: e o documento desta analise de KYC.
CREATE TABLE onboarding_document(
    id                  BIGSERIAL PRIMARY KEY,
    onboarding_id       BIGINT NOT NULL REFERENCES onboarding(id),
    document_type       VARCHAR(20) NOT NULL,
    side                VARCHAR(10) NOT NULL,
    -- Caminho no bucket. A foto NUNCA entra no Postgres.
    object_key          VARCHAR(255) NOT NULL,
    content_type        VARCHAR(50) NOT NULL,
    size_bytes          BIGINT NOT NULL,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT(NOW()),
    -- Dois envios do mesmo lado chegando juntos: so um passa.
    UNIQUE(onboarding_id, side),
    UNIQUE(object_key),
    CHECK (document_type IN ('RG')),
    CHECK (side IN ('FRONT', 'BACK', 'BOTH')),
    CHECK (content_type IN ('image/jpeg', 'image/png')),
    CHECK (size_bytes > 0 AND size_bytes <= 5242880)
);


-- O historico da abertura: cada mudanca de etapa grava uma linha, no
-- mesmo COMMIT da mudanca.
CREATE TABLE onboarding_status_event(
    id                  BIGSERIAL PRIMARY KEY,
    onboarding_id       BIGINT NOT NULL REFERENCES onboarding(id),
    status_id           BIGINT NOT NULL REFERENCES onboarding_status(id),
    reason_code         VARCHAR(40),
    actor               VARCHAR(20) NOT NULL,
    justification       VARCHAR(500),
    event_datetime      TIMESTAMPTZ NOT NULL,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT(NOW()),
    CHECK (actor IN ('api', 'worker', 'compliance'))
);

CREATE INDEX onboarding_status_event_onboarding ON onboarding_status_event (onboarding_id);
