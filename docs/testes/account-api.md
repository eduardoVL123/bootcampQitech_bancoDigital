# Plano de testes: conta, livro, transação e tarifa

Versão 1.0 · 07/10/2026 · cobre a RFC 02

Todo teste é **black box** (R1): fala com a API de pé só por HTTP, com `requests`, e não importa nada de `src/`. A única exceção é o `DbUtils.rollback()`, e só nos testes que contam linhas.

Cada teste **prepara pela porta da frente**: precisa de um cliente, faz `POST /internal/customer`; precisa de saldo, faz um depósito. Nunca `INSERT` direto no banco.

## Por que as fatias estão nesta ordem

Cada fatia torna a seguinte testável. Não dá para testar transferência sem conta, nem conta sem cliente.

| Fatia | O que entrega | Por que vem aqui |
|---|---|---|
| **F1** | abrir conta, ler saldo | sem conta não existe nada do resto |
| **F2** | `POST /internal/posting`: depósito | é o que faz o saldo deixar de ser zero. A rota que move dinheiro |
| **F3** | transferência com tarifa | os quatro lançamentos que somam zero |
| **F4** | extrato paginado por cursor | precisa de lançamentos, que vêm da F3 |
| **F5** | conciliação | soma tudo e tem de dar zero |
| **F6** | concorrência e idempotência | prova as garantias sob disputa real |

## F1. Abrir conta e ler saldo

Rotas: `POST /internal/account` e `GET /account/{account_key}`.

### Caminho feliz

| # | Teste | O que faz | Espera |
|---|---|---|---|
| F1-01 | `test_abre_conta_para_cliente_novo` | cria cliente, abre conta | `201`; `account_key` é UUID; `balance` 0; `status` `ACTIVE` |
| F1-02 | `test_resposta_traz_so_os_campos_do_contrato` | abre conta | as chaves são exatamente `account_key`, `balance`, `status`; **nenhum `id`** (R5) |
| F1-03 | `test_consulta_a_conta_recem_aberta` | abre, depois `GET` | `200` com a mesma `account_key` e `balance` 0 |
| F1-04 | `test_abertura_grava_o_evento_de_estado` | abre, `GET` | `status_events` tem uma entrada `ACTIVE` |

### Idempotência e unicidade

| # | Teste | O que faz | Espera |
|---|---|---|---|
| F1-05 | `test_abrir_duas_vezes_para_o_mesmo_cliente_devolve_a_mesma_conta` | abre duas vezes, mesmo cliente | a segunda responde `200` com a **mesma** `account_key`. É o contrato que a onboarding-api usa |
| F1-06 | `test_dois_pedidos_simultaneos_abrem_uma_conta_so` | duas chamadas no mesmo instante | uma `201` e uma `200`, mesma `account_key`. O índice único parcial é a rede |

### Recusas

| # | Teste | O que faz | Espera |
|---|---|---|---|
| F1-07 | `test_recusa_cliente_que_nao_existe` | `customer_key` inventada | `404 QIT002001` |
| F1-08 | `test_recusa_customer_key_fora_do_formato` | `customer_key` que não é UUID | `400 QIT000001` |
| F1-09 | `test_recusa_campo_a_mais` | manda `balance` no corpo | `400 QIT000001` (`additionalProperties: false`) |
| F1-10 | `test_conta_que_nao_existe_responde_404` | `GET` com chave inventada | `404 QIT002010` |
| F1-11 | `test_sem_token_do_aplicativo_nada_passa` | sem `INTERNAL-TOKEN` | `403 QIT000002` |

## F2. A rota que move dinheiro: `POST /internal/posting`

Entrega junto o `GET /internal/reconciliation`, porque sem ele não há como provar que o dinheiro fechou: conta técnica não tem coluna de saldo, e o saldo dela só existe como soma do livro.

| # | Teste | Espera |
|---|---|---|
| F2-01 | `test_deposito_credita_a_conta` | `201`, saldo vira o valor, dois lançamentos |
| F2-02 | `test_deposito_mantem_a_conciliacao_em_zero` | `total` 0 |
| F2-03 | `test_lancamento_numera_a_sequencia_da_conta` | `sequence` 1 e 2, `balance_after` acompanhando |
| F2-04 | `test_lancamento_de_conta_tecnica_nao_tem_sequencia` | `sequence` e `balance_after` nulos |
| F2-05 | `test_mesma_posting_key_nao_credita_duas_vezes` | `200`, saldo não muda |
| F2-06 | `test_recusa_conjunto_que_nao_soma_zero` | `422 QIT002017`, nada gravado |
| F2-07 | `test_recusa_conta_que_nao_existe` | `404 QIT002010` |
| F2-08 | `test_recusa_saldo_insuficiente` | `409 QIT002012`, saldo intacto |
| F2-09 | `test_recusa_lancamento_de_valor_zero` | `400 QIT000001` |
| F2-10 | `test_recusa_entrada_sem_conta_nenhuma` | `400 QIT000001` |
| F2-11 | `test_dez_saques_com_saldo_para_cinco_passam_exatamente_cinco` | cinco `201`, cinco `409`, nenhum `5xx`, saldo zero, conciliação zero |

**Mutações conferidas no F2-11**, que é o teste que sustenta o Principal desafio da RFC 02:

| O que eu quebrei | O que o teste respondeu |
|---|---|
| tirei o `with_for_update()` | `[201, 500, 500, 500, 500, 500, 201, 500, 500, 500]` |
| tirei só o `populate_existing()`, mantendo a trava | `[201, 201, 500, 500, 500, 500, 500, 500, 500, 500]` |

A segunda é a que mais importa: a trava estava certa no banco e a decisão saía errada, porque o identity map do SQLAlchemy devolvia o objeto com o saldo antigo. É a armadilha que o `CLAUDE.md` descreve, e agora tem teste que a pega.

## F3. Transação: transferência com tarifa e depósito

Rotas: `POST /transaction` (com o cabeçalho `Idempotency-Key`), `GET /transaction/{key}` e `POST /internal/fee_policy`.

A transação **não move dinheiro**. Ela decide a regra, grava o que foi pedido e pede o posting da F2.

| # | Teste | Espera |
|---|---|---|
| F3-01 | `test_transferencia_move_valor_e_cobra_tarifa` | Ana 89800, Bruno 10000, tarifa 200 |
| F3-02 | `test_transferencia_gera_quatro_lancamentos_somando_zero` | conciliação em zero |
| F3-03 | `test_tarifa_e_copiada_da_politica_vigente` | `fee_amount` e `fee_policy_key` registrados |
| F3-04 | `test_tarifa_antiga_preservada_depois_de_mudar_a_regra` | muda para 500, a transação velha segue com 200 |
| F3-05 | `test_recusa_saldo_que_nao_cobre_valor_mais_tarifa` | `409 QIT002012`, saldo intacto |
| F3-06 | `test_recusa_transferencia_para_a_propria_conta` | `422 QIT002019` |
| F3-07 | `test_recusa_transferencia_sem_destino` | `422 QIT002019` |
| F3-08 | `test_recusa_pedido_sem_chave_de_idempotencia` | `400 QIT002021` |
| F3-09 | `test_mesma_chave_com_outro_pedido_e_conflito` | `409 QIT002020`, nada movido |
| F3-10 | `test_deposito_credita_sem_cobrar_tarifa` | `fee_amount` 0 |
| F3-11 | `test_dez_cliques_com_a_mesma_chave_geram_uma_transferencia` | um `201`, um débito, uma tarifa, conciliação zero |

**Poluição entre testes, e como foi resolvida.** O F3-04 cria uma política de tarifa nova, e isso é configuração **global e append-only**: a partir dali, todo teste seguinte cobra o valor novo. Na primeira rodada o F3-09 e o F3-11 quebraram por isso, e só quebravam quando rodavam junto com o F3-04. Cada teste que afirma um valor de tarifa agora **define o valor antes**, com `define_tarifa()`. Conferido rodando a suíte três vezes em ordem aleatória com o `pytest-randomly`: 33 passando nas três.

**Mutação conferida no F3-05.** Troquei a conferência de saldo de "o total da conta neste posting" para "cada lançamento isolado". Numa transferência a origem aparece duas vezes, pelo valor e pela tarifa, e a conferência isolada deixa passar o pedido que só cabe sem a tarifa. O mutante devolveu `500` no lugar de `409`: o `CHECK (balance >= 0)` do banco segurou o saldo negativo, mas feio, com a API assumindo a culpa.

## F4. Extrato paginado por cursor

Rota: `GET /account/{account_key}/statement?limit=20&cursor=...`

| # | Teste | Espera |
|---|---|---|
| F4-01 | `test_traz_os_lancamentos_da_conta_do_mais_novo_para_o_mais_velho` | `sequence` 3, 2, 1 |
| F4-02 | `test_cada_linha_traz_o_saldo_depois_dela` | `balance_after` da primeira linha bate com o saldo atual |
| F4-03 | `test_pagina_por_cursor_sem_repetir_item` | páginas sem interseção |
| F4-04 | `test_ultima_pagina_se_anuncia` | `is_last_page` true, `next_cursor` nulo |
| F4-05 | `test_extrato_estavel_enquanto_chegam_lancamentos` | três lançamentos novos entre as páginas não duplicam nada |
| F4-06 | `test_recusa_cursor_adulterado` | `400 QIT002015` |
| F4-07 | `test_recusa_cursor_de_outra_conta` | `400 QIT002015` |
| F4-08 | `test_recusa_limite_fora_do_intervalo` | `400 QIT000001` para 0, 101 e texto |
| F4-09 | `test_conta_que_nao_existe_responde_404` | `404 QIT002010`, e não lista vazia |
| F4-10 | `test_conta_sem_movimento_tem_extrato_vazio` | `data` vazio, `is_last_page` true |

**Mutações conferidas.**

| O que eu quebrei | O que o teste respondeu |
|---|---|
| troquei o cursor por `OFFSET` | o F4-05 pegou um lançamento repetido nas duas páginas. **O F4-03 passou**, e é esse o ponto: paginação por offset só quebra quando chega escrita entre uma página e a seguinte |
| tirei a conferência da assinatura e do dono do cursor | o F4-06 e o F4-07 viraram `200` no lugar de `400`: daria para montar um cursor à mão e espiar o livro de outra conta |

A primeira é a mais instrutiva. Um teste de paginação que só lê não distingue cursor de offset. É preciso escrever no meio.

## F5. Conciliação

| # | Teste | Espera |
|---|---|---|
| F5-01 | `test_conciliacao_fecha_em_zero_no_sistema_vazio` | `total` 0 |
| F5-02 | `test_conciliacao_continua_zero_depois_de_depositos_e_transferencias` | `total` 0 |

## F6. Concorrência (marcador `concurrency`)

| # | Teste | Espera |
|---|---|---|
| F6-01 | `test_dez_transferencias_juntas_com_saldo_para_cinco` | exatamente cinco passam, saldo final zero, nunca negativo |
| F6-02 | `test_transferencias_cruzadas_nao_travam` | A para B e B para A juntas terminam, sem deadlock |
| F6-03 | `test_varias_origens_para_um_destino_somam_exato` | o destino recebe a soma exata |
| F6-04 | `test_conciliacao_fecha_em_zero_depois_da_corrida` | `total` 0 |
