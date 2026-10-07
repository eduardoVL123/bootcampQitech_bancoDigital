# Plano de testes black box: onboarding-api

| | |
|---|---|
| **Base** | RFC 05 v0.7 (onboarding-api), com as regras gerais da RFC 00 e o contrato de `POST /internal/account` da RFC 02 |
| **Data** | 07/10/2026 |
| **Versão** | 0.2 (F4 verde: três testes novos, F4-21 a F4-23, e as decisões D22 e D23) |
| **Onde ficam os testes** | `tests/onboarding_api/`, com as ferramentas em `tests/utils/onboarding_api.py` |

Este plano diz **o que** cada teste prova, **como** ele prova e **qual regra da RFC** ele protege. Ele vem antes de qualquer teste escrito. Se um teste daqui mudar, a RFC muda junto, e o contrário também.

## 1. Regras de todos os testes

- **Só por HTTP (R1).** O teste fala com a onboarding-api na porta 3005 e com a API de controle do Mockserver na porta 1080. Ele nunca importa nada de `src/`, nunca lê o banco e nunca lê o bucket.
- **O teste faz o papel do gateway.** Como a onboarding-api é testada sozinha, o teste manda o que o gateway mandaria: `INTERNAL-TOKEN`, `X-Idempotency-Key` (UUID novo a cada pedido) e `X-Forwarded-For` (um IP aleatório por teste, para que os contadores de origem de um teste não atrapalhem outro).
- **Cada teste cria o próprio mundo.** CPF ou CNPJ novo, chave nova, IP novo. As expectativas do Mockserver ficam presas ao documento do teste. Nenhum teste chama `/mockserver/reset`.
- **Prepara, age, confere.** A preparação é feita pela API (`POST`, nunca `INSERT`).
- **Cada regra tem os dois lados.** O caso que passa e o caso que é barrado. Limites numéricos são testados dos dois lados da borda (por exemplo: 18 anos hoje passa, 18 anos amanhã não passa).
- **Teste em português, fácil de ler.** O nome diz o comportamento, sem acento (`test_recusa_pf_menor_de_18_anos`). Cada teste marca `# prepara`, `# age` e `# confere`, e a docstring diz a regra numa frase, com o ID do plano. Caso parametrizado tem nome legível (`[CPF sem mascara]`). O código da API continua em inglês, como a base.
- **Mockserver só no lugar de quem está fora:** Receita, sanções, PEP, account-api e webhook-api. A customer-api não existe mais (v0.5): o cliente mora na própria onboarding-api, então não há o que simular.

## 2. Ambiente

| Peça | Endereço nos testes | Papel |
|---|---|---|
| onboarding-api | `http://127.0.0.1:3005` | Quem está sendo testado |
| onboarding-worker | sem porta | O mesmo código, em outro processo: KYC, prazo e eventos |
| PostgreSQL | `bootcamp` | O banco único do grupo; as tabelas da onboarding estão na seção 7 do `database/database.sql` (o teste não lê) |
| Redis | só dentro do compose | Limites por documento e por origem, circuit breaker |
| LocalStack | só dentro do compose | Bucket privado `rg-documentos`, criado por `localstack/init-bucket.sh`. Imagem fixa na 4.14.0, a última que sobe sem conta no LocalStack |
| Mockserver | `http://127.0.0.1:1080` | Receita, sanções, PEP, account-api e webhook-api |

| Variável | Onde | Para quê |
|---|---|---|
| `AUTH_SECRET` | API e pytest, mesmo valor | O teste confere a assinatura do JWT e fabrica credenciais vencidas, adulteradas e de compliance |
| `SERVICE_TOKEN` | API e pytest, mesmo valor | O teste confere que o worker se apresenta à account-api e à webhook-api |
| `SIMULATED_CLOCK_ENABLED=true` | API e pytest | Liga o cabeçalho `X-Simulated-Now` (marcador `simulated_clock`) |
| `FAULT_INJECTION_ENABLED=true` | API e pytest | Liga `X-Fault-Injection: bucket_unavailable` e `redis_unavailable` (marcador `fault_injection`) |
| `MOCKSERVER_URL` | pytest | Onde o teste programa e confere o Mockserver |

**Marcadores do pytest.**

| Marcador | O que faz |
|---|---|
| `concurrency` | Dispara pedidos juntos de verdade (`run_at_the_same_time`) |
| `fault_injection` | Pula se `FAULT_INJECTION_ENABLED` não estiver ligado |
| `simulated_clock` | Pula se `SIMULATED_CLOCK_ENABLED` não estiver ligado |
| `slow` | Espera uma retentativa real (1 minuto) ou o circuito aberto (30 s). Para o dia a dia: `pytest -m "not slow"` |
| `global_state` | Mexe em algo que vale para todos (circuito aberto, teste de saúde dos birôs). O `conftest.py` joga esses testes para o fim da fila |

### 2.1 Como o teste enxerga o que não tem rota

| O quê | Como o teste vê |
|---|---|
| A etapa que o worker colocou | `GET /onboarding/{key}` repetido a cada 0,5 s até a etapa esperada, com limite de 20 s (`wait_for_status`) |
| As chamadas aos birôs, à account-api e à webhook-api | `PUT /mockserver/retrieve` filtrado pelo documento, pela `customer_key` ou pela `onboarding_key`; `PUT /mockserver/verify` para contar |
| O prazo de 20 minutos e a espera de 24 horas | `X-Simulated-Now` no `POST /onboarding` e no envio do RG: o pedido acontece "no passado", e o relógio de verdade faz o resto |
| Bucket ou Redis fora do ar | `X-Fault-Injection` |
| Birô, account-api ou webhook-api fora do ar | Expectativa do Mockserver com `503`, atraso de 3 s ou conexão derrubada, presa ao documento do teste |
| Dado pessoal apagado depois do prazo | O mesmo CPF volta a abrir conta (`201`), e `GET /customer/{key}` com credencial de compliance responde `404` |

### 2.2 Contratos simulados no Mockserver (proposta, a entrar na RFC)

A RFC 05 diz que os birôs são "simulados no Mockserver com o mesmo contrato", mas não escreve o contrato. Proposta:

| Quem | Rota | Pedido | Resposta normal |
|---|---|---|---|
| Receita | `POST /receita/v1/consulta` | `document_number` | `200` com `situacao`, `name`, `birth_date` (PF) ou `opening_date` (PJ) e `protocol` |
| Sanções | `POST /sancoes/v1/consulta` | `document_number`, `name` | `200` com `match` (`true` ou `false`) e `protocol` |
| PEP | `POST /pep/v1/consulta` | `document_number` | `200` com `pep` (`true` ou `false`) e `protocol` |
| Teste de saúde dos birôs | `GET /receita/v1/health`, `GET /sancoes/v1/health`, `GET /pep/v1/health` | nada | `200` |
| account-api | `POST /internal/account` | `customer_key`, `type`; cabeçalhos `SERVICE-TOKEN` e `X-Idempotency-Key` | `201` com `account_key`, `customer_key`, `type` e `status` `ACTIVE` |
| webhook-api | `POST /internal/event` | `event_id`, `event_type`, `occurred_at`, `data`; cabeçalho `SERVICE-TOKEN` | `202` |

Valores de `situacao` na Receita. CPF: `REGULAR`, `SUSPENSA`, `CANCELADA`, `TITULAR_FALECIDO`, `NULA`, `PENDENTE_REGULARIZACAO`. CNPJ: `ATIVA`, `SUSPENSA`, `INAPTA`, `BAIXADA`, `NULA`. Para os dois: `NAO_ENCONTRADO`.

As rotas de saúde têm uma resposta padrão `200`, carregada quando o Mockserver sobe. Todo o resto é programado pelo próprio teste, preso ao documento dele. Um pedido sem expectativa recebe o `404` vazio do Mockserver, e isso nunca pode virar aprovação.

## 3. Fatias

Cada fatia segue a mesma ordem: testes vermelhos pelo motivo certo, código, testes verdes, commit. Os testes de credencial (`401` e `403`) são parametrizados pelas rotas: cada fatia que cria uma rota com credencial acrescenta a rota a essa lista.

### F0. O serviço sobe

Arquivo `test_service.py`.

| ID | Teste | Prepara e age | Espera | Regra |
|---|---|---|---|---|
| F0-01 | `test_pagina_inicial_diz_qual_servico_e` | `GET /` sem token | `200`, `service` = `onboarding-api` | Rotas |
| F0-02 | `test_health_check_responde_sem_token` | `GET /health_check` sem token | `204` | Rotas |
| F0-03 | `test_sem_token_do_aplicativo_nada_passa` | `POST /onboarding` sem `INTERNAL-TOKEN` | `403 ONB000002` | RFC 00 |
| F0-04 | `test_rota_que_nao_existe_responde_404_com_corpo_de_erro` | `GET /nao_existe` com token | `404 ONB000404`, corpo de erro completo | Formato de erro |

### F1. `POST /onboarding`: cadastro e começo da abertura

Arquivo `test_post_onboarding.py`.

**Caminho feliz**

| ID | Teste | Prepara e age | Espera | Regra |
|---|---|---|---|---|
| F1-01 | `test_pf_valida_cadastra_e_comeca_abertura_em_draft` | PF válida | `201`; `onboarding_key` e `customer_key` são UUID; `status` `DRAFT`; `next_step` `SEND_DOCUMENT`; `expires_at` é agora mais 20 min (tolerância de 1 min) | Rotas, prazo |
| F1-02 | `test_pj_valida_cadastra_e_comeca_abertura_em_draft` | PJ válida, com CNPJ e `opening_date` | `201`, `DRAFT` | Rotas |
| F1-03 | `test_resposta_traz_so_os_campos_do_contrato` | PF válida | As chaves são exatamente `onboarding_key`, `customer_key`, `status`, `expires_at`, `access_token`, `next_step`; nenhum `id`, CPF ou renda | R5, LGPD |
| F1-04 | `test_credencial_e_um_jwt_hs256_do_cliente` | PF válida, decodifica o token com `AUTH_SECRET` | `sub` = `customer_key`; `scope` = `onboarding`; `exp` menos `iat` = 3600; `jti` é UUID; só esses cinco campos | Credencial |
| F1-05 | `test_aceita_pf_que_completa_18_anos_hoje` | Nascida há 18 anos, hoje | `201` | Borda da idade |
| F1-06 | `test_aceita_pj_aberta_hoje` | `opening_date` de hoje | `201` | Borda da data futura |
| F1-07 | `test_aceita_renda_zero` | `declared_monthly_income_cents` = 0 | `201` | Borda do mínimo |

**Campo obrigatório ausente: `400 ONB005001`**

| ID | Teste | Prepara e age | Espera | Regra |
|---|---|---|---|---|
| F1-08 | `test_recusa_campo_obrigatorio_ausente_e_diz_qual` | Parametrizado: tira `type`, `name`, `document_number`, `declared_monthly_income_cents`, `pep_self_declared`; na PF, `birth_date` e `occupation`; na PJ, `opening_date` | `400 ONB005001`; `errors` traz `{field, rule: required}` do campo | Formato de erro |
| F1-09 | `test_corpo_vazio_lista_todos_os_obrigatorios` | Corpo `{}` | `400 ONB005001`, com os cinco campos comuns em `errors` | Formato de erro |
| F1-10 | `test_campo_ausente_vem_antes_do_campo_torto` | Um campo ausente e outro torto | `400 ONB005001` | Ordem do fluxo |

**Campo fora do formato: `400 ONB000001`, com `field` e `rule`**

| ID | Teste | Prepara e age | Espera | Regra |
|---|---|---|---|---|
| F1-11 | `test_recusa_campo_fora_do_formato` | Parametrizado, um caso por linha abaixo | `400 ONB000001` com o campo e a regra | Schema |
| | | `type` = `PX` | `type`, `format` | |
| | | CPF sem máscara (`12345678909`) | `document_number`, `format` | |
| | | PF com máscara de CNPJ; PJ com máscara de CPF | `document_number`, `format` | |
| | | `birth_date` = `17/05/1990`; `opening_date` = `2020-1-5` | o campo, `format` | |
| | | `name` vazio; `name` com 256 caracteres | `name`, `minimum`; `name`, `maximum` | |
| | | `occupation` com 101 caracteres | `occupation`, `maximum` | |
| | | renda `-1` | `declared_monthly_income_cents`, `minimum` | |
| | | renda `1000.5` e renda `"1000"` | `declared_monthly_income_cents`, `type` (dinheiro nunca é `float`, R6) | |
| | | renda acima do teto | `declared_monthly_income_cents`, `maximum` | |
| | | `pep_self_declared` = `"sim"` | `pep_self_declared`, `type` | |
| F1-12 | `test_recusa_campo_que_nao_existe` | Campo `email` a mais | `400 ONB000001`, `email`, `format` | `additionalProperties: false` |
| F1-13 | `test_recusa_campo_do_outro_tipo_de_cliente` | PF com `opening_date`; PJ com `birth_date` ou `occupation` | `400 ONB000001` | LGPD: só o necessário |
| F1-14 | `test_recusa_corpo_que_nao_e_json` | Corpo `abc` | `400 ONB000001` | Schema |

**Valor impossível: `422`**

| ID | Teste | Prepara e age | Espera | Regra |
|---|---|---|---|---|
| F1-15 | `test_recusa_cpf_com_digito_errado` | CPF com o último dígito trocado | `422 ONB005004`, `cpf_check_digit` | Dígitos |
| F1-16 | `test_recusa_cpf_com_todos_os_digitos_iguais` | `111.111.111-11` | `422 ONB005004` | Dígitos |
| F1-17 | `test_recusa_cnpj_com_digito_errado` | CNPJ com o último dígito trocado | `422 ONB005004`, `cnpj_check_digit` | Dígitos |
| F1-18 | `test_recusa_data_que_nao_existe` | `birth_date` = `2001-02-30`; `opening_date` = `2021-13-01` | `422 ONB005005`, `valid_date` | Datas |
| F1-19 | `test_recusa_nascimento_no_futuro` | Amanhã | `422 ONB005005` | Datas |
| F1-20 | `test_recusa_abertura_da_empresa_no_futuro` | Amanhã | `422 ONB005005` | Datas |

**Idade, duplicidade e "nada é gravado"**

| ID | Teste | Prepara e age | Espera | Regra |
|---|---|---|---|---|
| F1-21 | `test_recusa_pf_menor_de_18_anos` | Completa 18 anos amanhã | `400 ONB005002`, `minimum_age` | Idade |
| F1-22 | `test_recusa_cpf_que_ja_e_cliente` | Mesmo CPF, outra chave | `409 ONB005003` | `UNIQUE` |
| F1-23 | `test_recusa_cnpj_que_ja_e_cliente` | Mesmo CNPJ, outra chave | `409 ONB005003` | `UNIQUE` |
| F1-24 | `test_cadastros_simultaneos_do_mesmo_cpf_criam_um_so` | 5 pedidos juntos, mesmo CPF, chaves diferentes (5 é o limite por documento da F2) | Um `201`, quatro `409 ONB005003`, nenhum `500` | `concurrency` |
| F1-25 | `test_pedido_recusado_nao_grava_nada` | `422` por data impossível; depois, o mesmo CPF certo | `201` | Nada é gravado |
| F1-26 | `test_recusa_nao_gasta_a_chave` | `409` com a chave K; depois, K com um CPF novo | `201` | Nada é gravado |

**Idempotência**

| ID | Teste | Prepara e age | Espera | Regra |
|---|---|---|---|---|
| F1-27 | `test_mesma_chave_e_mesmo_pedido_devolvem_a_mesma_abertura` | Repete o pedido com a mesma chave | `200`; mesma `onboarding_key` e `customer_key`; `access_token` novo e válido (`jti` diferente) | `UNIQUE(idempotency_key)` |
| F1-28 | `test_mesma_chave_com_outro_pedido_e_recusada` | Mesma chave, outro CPF | `409 ONB000012`; o CPF do segundo pedido continua livre | `request_hash` |
| F1-29 | `test_ordem_dos_campos_nao_muda_o_pedido` | Mesmo conteúdo, campos em outra ordem | `200`, a mesma abertura | Hash canônico |
| F1-30 | `test_exige_a_chave_idempotente` | Sem o cabeçalho | `400 ONB000011` | Decisão D7 |
| F1-31 | `test_recusa_chave_que_nao_e_uuid` | `X-Idempotency-Key: abc` | `400 ONB000011` | Decisão D7 |
| F1-32 | `test_pedidos_simultaneos_com_a_mesma_chave_criam_uma_abertura` | 10 pedidos juntos, mesma chave | Um `201`, nove `200`, todos com a mesma `onboarding_key` | `concurrency` |

**Formato de erro**

| ID | Teste | Prepara e age | Espera | Regra |
|---|---|---|---|---|
| F1-33 | `test_corpo_de_erro_tem_os_campos_do_contrato` | Qualquer recusa | `code`, `title`, `description`, `translation`, `request_id` (igual ao cabeçalho `X-Request-ID`) e `errors` | Formato de erro |
| F1-34 | `test_erro_nunca_repete_documento_nem_renda` | Recusas `400`, `409` e `422` | O corpo não contém o CPF ou CNPJ (com e sem máscara) nem a renda | LGPD |

### F2. Limites de pedidos no Redis

Arquivo `test_rate_limit.py`.

| ID | Teste | Prepara e age | Espera | Regra |
|---|---|---|---|---|
| F2-01 | `test_sexta_tentativa_do_mesmo_documento_na_hora_e_recusada` | 5 tentativas com o mesmo CPF (um `201` e quatro `409`) | A sexta: `429 ONB005013`, com `Retry-After` maior que zero | 5 por hora |
| F2-02 | `test_limite_de_um_documento_nao_atrapalha_outro` | Depois do `429`, outro CPF da mesma origem | `201` | Limite por documento |
| F2-03 | `test_vinte_recusas_bloqueiam_a_origem` | 20 CPFs já cadastrados por outra origem; a origem X tenta os 20 (vinte `409`) | O 21º pedido de X, válido e novo: `429 ONB005013`, com `Retry-After` | 20 em 10 min |
| F2-04 | `test_dezenove_recusas_nao_bloqueiam_a_origem` | 19 recusas | O 20º pedido, válido: `201` | Borda |
| F2-05 | `test_origem_bloqueada_nao_bloqueia_as_outras` | Origem X bloqueada; pedido da origem Y | `201` | Limite por origem |
| F2-06 | `test_sem_redis_os_limites_desligam_e_a_api_continua` | `X-Fault-Injection: redis_unavailable`; sexta tentativa do mesmo CPF | `409 ONB005003`, e não `429`; um CPF novo continua `201` | Redis fora (`fault_injection`) |
| F2-07 | `test_repetir_uma_tentativa_ja_contada_recebe_a_mesma_resposta` | Cinco tentativas com chaves diferentes; repete a quinta chave; manda uma sexta chave nova | A repetição recebe o mesmo `409 ONB005003`; só a chave nova recebe `429` | Mesma chave, mesma resposta |

### F3. Credencial, leitura da abertura e do cliente

Arquivos `test_get_onboarding.py`, `test_get_customer.py` e `test_credential.py`.

| ID | Teste | Prepara e age | Espera | Regra |
|---|---|---|---|---|
| F3-01 | `test_dono_ve_a_propria_abertura_em_draft` | Dono lê a própria abertura | `200` com `status` `DRAFT`, `next_step`, `expires_at`, `documents` vazio, `checks` vazio, `reason_codes` vazio, `risk_level` e `account_key` nulos e `status_events` com `DRAFT` | `GET /onboarding` |
| F3-02 | `test_abertura_nao_mostra_dado_pessoal` | Dono lê | Sem CPF, nome, renda ou data de nascimento | LGPD |
| F3-03 | `test_abertura_de_outra_pessoa_responde_404` | Credencial de outro cliente | `404 ONB005006` | R8 |
| F3-04 | `test_abertura_que_nao_existe_responde_igual_a_de_outra_pessoa` | UUID que ninguém criou | `404 ONB005006`, mesmo corpo do F3-03 (menos o `request_id`) | R8 |
| F3-05 | `test_compliance_ve_qualquer_abertura` | Credencial de compliance | `200` | Escopo |
| F3-06 | `test_cliente_ve_o_proprio_cadastro` | Dono lê o cadastro | `200` com exatamente `customer_key`, `type`, `name`, `document_number`, `birth_date` e `created_at`; sem credencial, renda ou ocupação | `GET /customer` |
| F3-07 | `test_empresa_mostra_a_data_de_abertura` | PJ lê | `opening_date`, sem `birth_date` | `GET /customer` |
| F3-08 | `test_cadastro_de_outra_pessoa_responde_404` | Credencial de outro cliente | `404 ONB005007` | R8 |
| F3-09 | `test_cadastro_que_nao_existe_responde_404` | UUID que ninguém criou | `404 ONB005007` | R8 |
| F3-10 | `test_compliance_ve_qualquer_cadastro` | Credencial de compliance | `200` | Escopo |

**Matriz de credencial**, parametrizada por rota (`GET /onboarding/{key}`, `GET /customer/{key}`, `PUT .../document`, `GET /onboardings`, `PUT .../decision`, `POST /admin/onboardings/retry`):

| ID | Teste | Prepara e age | Espera | Regra |
|---|---|---|---|---|
| F3-11 | `test_sem_credencial_responde_401` | Sem `Authorization` | `401 ONB000003`, `WWW-Authenticate: Bearer realm="banco"` | OAuth |
| F3-12 | `test_credencial_assinada_com_outro_segredo_responde_401` | JWT assinado com outro segredo | `401 ONB000006`, `error="invalid_token"` | OAuth |
| F3-13 | `test_credencial_mal_formada_responde_401` | `Bearer abc` e `Basic abc` | `401 ONB000006` | OAuth |
| F3-14 | `test_credencial_sem_assinatura_responde_401` | JWT com `alg: none` | `401 ONB000006` | OAuth |
| F3-15 | `test_credencial_vencida_responde_401` | JWT com `exp` no passado | `401 ONB000007`, `error="invalid_token"`, `error_description="token expirado"` | OAuth |
| F3-16 | `test_credencial_de_cliente_em_rota_de_compliance_responde_403` | Credencial `onboarding` nas três rotas de compliance | `403 ONB000008`, `error="insufficient_scope"`, `scope="compliance"` | Escopo |

O F3-16 só pode ser escrito quando existir a primeira rota exclusiva de compliance, que nasce na F8 (`GET /onboardings`).

### F4. Envio do RG, frente e verso

Arquivo `test_put_document.py`. Imagens geradas no próprio teste (bytes mínimos de JPEG e PNG). **Verde em 07/10** (branch `feat/onboarding-rg`), com o `PUT .../document` também na matriz de credencial (F3-11 a F3-15). Fica para a F5: o `410 ONB005010` no envio de uma abertura vencida e o `next_attempt_at` que o worker vai ler.

| ID | Teste | Prepara e age | Espera | Regra |
|---|---|---|---|---|
| F4-01 | `test_frente_e_verso_juntos_completam_o_rg` | `front` e `back` no mesmo envio | `202`, `PENDING_KYC`, `next_step` `WAIT` | RG completo |
| F4-02 | `test_uma_imagem_com_os_dois_lados_completa_o_rg` | Só `both` | `202`, `PENDING_KYC` | RG completo |
| F4-03 | `test_so_a_frente_mantem_draft_e_pede_o_verso` | Só `front` | `200`, `DRAFT`, `next_step` `SEND_BACK` | Falta um lado |
| F4-04 | `test_verso_depois_da_frente_completa_o_rg` | `front`, depois `back` | `202`, `PENDING_KYC` | RG completo |
| F4-05 | `test_abertura_mostra_os_lados_recebidos` | `front`; depois `back` | `documents` com `FRONT`; depois `FRONT` e `BACK` | `GET /onboarding` |
| F4-06 | `test_aceita_png` | `front` PNG, `back` JPEG | `202` | Tipos aceitos |
| F4-07 | `test_aceita_arquivo_de_exatamente_5_mb` | 5 × 1024 × 1024 bytes | Aceito | Borda do tamanho |
| F4-08 | `test_recusa_arquivo_acima_de_5_mb` | 5 MB mais 1 byte | `413 ONB005011`; `documents` continua vazio | Tamanho |
| F4-09 | `test_recusa_arquivo_que_nao_e_jpeg_nem_png` | Bytes de PDF | `422 ONB005012` | Tipo |
| F4-10 | `test_tipo_do_arquivo_vem_dos_bytes_e_nao_do_nome` | PDF chamado `rg.jpg` com `image/jpeg`; JPEG chamado `rg.pdf` | O primeiro `422 ONB005012`; o segundo aceito | Primeiros bytes |
| F4-11 | `test_recusa_envio_sem_arquivo` | Nenhum arquivo | `400 ONB005001` | Obrigatório |
| F4-12 | `test_recusa_mais_de_duas_imagens` | Parametrizado: `front`, `back` e `both` no mesmo envio; `front` e depois `front` e `back` | `409 ONB005009` | Máximo de 2 |
| F4-13 | `test_recusa_lado_repetido` | Parametrizado: `front` e depois `front`; `front` e depois `both`; `front` duas vezes no mesmo envio; `front` e `both` no mesmo envio | `409 ONB005009` | Lado repetido |
| F4-14 | `test_envio_recusado_nao_muda_nada` | Parametrizado: frente de novo com o verso junto (`409`); verso grande com a frente boa junto (`413`); verso em PDF com a frente boa junto (`422`) | `documents` e `status` iguais aos de antes, nem a imagem boa é guardada | Nada enviado |
| F4-15 | `test_recusa_envio_fora_de_draft` | RG já completo, novo envio | `409 ONB005008` | Etapa |
| F4-16 | `test_envio_para_abertura_de_outra_pessoa_responde_404` | Parametrizado: credencial de outro cliente; UUID que ninguém criou; credencial de compliance | `404 ONB005006`, e a abertura da dona continua sem documento | R8 e escopo |
| F4-17 | `test_bucket_fora_responde_503_e_nao_grava_nada` | `X-Fault-Injection: bucket_unavailable`; depois repete sem a falha | `503 ONB005015` e `DRAFT` sem documentos; a repetição dá `202` | Bucket fora (`fault_injection`) |
| F4-18 | `test_envios_simultaneos_do_mesmo_lado_gravam_um_so` | 5 envios de `front` juntos | Um `200`, quatro `409 ONB005009`, nenhum `500` | `UNIQUE(onboarding_id, side)` (`concurrency`) |
| F4-19 | `test_envio_exige_a_chave_idempotente` | Sem o cabeçalho | `400 ONB000011` | Decisão D7 |
| F4-20 | `test_rg_completo_entra_no_historico` | RG completo | `status_events`: `DRAFT`, `PENDING_KYC` | Histórico |
| F4-21 | `test_so_o_verso_mantem_draft_e_pede_a_frente` | Só `back` | `200`, `DRAFT`, `next_step` `SEND_FRONT` | Decisão D23 |
| F4-22 | `test_frente_e_verso_em_envios_simultaneos_completam_o_rg` | `front` e `back` em pedidos separados, juntos, em cinco aberturas | Cinco `200` e cinco `202`; cada abertura em `PENDING_KYC`, com um evento só | Trava da abertura (`concurrency`) |
| F4-23 | `test_frente_e_imagem_com_os_dois_lados_juntas_gravam_uma_so` | `front` e `both` em pedidos separados, juntos, em cinco aberturas | Em cada abertura, um passa e o outro dá `409`; um documento só | Conferência depois da trava (`concurrency`) |

### F5. Prazo de 20 minutos

Arquivo `test_expiration.py`, marcador `simulated_clock`.

| ID | Teste | Prepara e age | Espera | Regra |
|---|---|---|---|---|
| F5-01 | `test_envio_depois_do_prazo_responde_410` | `POST` com `X-Simulated-Now` de 21 min atrás; envio do RG agora | `410 ONB005010` | Prazo |
| F5-02 | `test_consulta_depois_do_prazo_responde_410` | Mesma preparação; `GET /onboarding` | `410 ONB005010` | Prazo |
| F5-03 | `test_envio_pouco_antes_do_prazo_e_aceito` | `POST` de 19 min atrás; envio do RG agora | `202` | Borda do prazo |
| F5-04 | `test_worker_apaga_os_dados_da_abertura_vencida` | `POST` de 21 min atrás, `front` enviado "antes" do prazo; espera o worker (até 70 s) | `GET /customer` com compliance: `404 ONB005007`; `GET /onboarding`: `410` | LGPD, prazo (`slow`) |
| F5-05 | `test_documento_fica_livre_depois_do_vencimento` | Depois do F5-04, o mesmo CPF | `201` | Prazo |
| F5-06 | `test_prazo_para_de_contar_depois_do_rg_completo` | `POST` de 25 min atrás; RG completo "há 10 min" (antes de vencer); `GET` agora | Não é `410`: a abertura segue para a análise | Prazo só vale em `DRAFT` |
| F5-07 | `test_repetir_o_cadastro_de_abertura_vencida_responde_410` | Repete o `POST` da abertura vencida, com a mesma chave | `410 ONB005010` | Decisão D9 |

### F6. Worker: KYC, PLD e abertura da conta

Arquivo `test_kyc_worker.py`. O teste programa a Receita, as sanções e o PEP para o documento dele, manda o RG completo e espera a etapa com `wait_for_status`.

| ID | Teste | Prepara e age | Espera | Regra |
|---|---|---|---|---|
| F6-01 | `test_pessoa_regular_e_aprovada_e_ganha_conta` | Tudo regular | `ACTIVE`; `account_key` igual à do mock; `risk_level` `LOW`; `checks` `RECEITA`, `SANCTIONS`, `PEP` e `PLD` com `PASS`; histórico `DRAFT`, `PENDING_KYC`, `ANALYSIS`, `APPROVED`, `ACTIVE` | Caminho feliz |
| F6-02 | `test_biros_sao_consultados_em_ordem` | Tudo regular | No Mockserver: Receita, depois sanções, depois PEP, uma vez cada | Ordem |
| F6-03 | `test_conta_e_pedida_com_a_chave_da_abertura` | Tudo regular | Uma chamada a `POST /internal/account` com `customer_key` e `type`, `SERVICE-TOKEN` e `X-Idempotency-Key` igual à `onboarding_key` | Contrato RFC 02 |
| F6-04 | `test_empresa_regular_e_aprovada` | PJ `ATIVA` | `ACTIVE` | PJ |
| F6-05 | `test_cpf_irregular_e_recusado` | Parametrizado: `SUSPENSA`, `CANCELADA`, `TITULAR_FALECIDO`, `NULA`, `PENDENTE_REGULARIZACAO` | `REJECTED`, `RECEITA_<situação>` | Receita |
| F6-06 | `test_cnpj_irregular_e_recusado` | Parametrizado: `SUSPENSA`, `INAPTA`, `BAIXADA`, `NULA` | `REJECTED`, `RECEITA_CNPJ_<situação>` | Receita |
| F6-07 | `test_documento_desconhecido_e_recusado` | `NAO_ENCONTRADO` | `REJECTED`, `RECEITA_NAO_ENCONTRADO` | Receita |
| F6-08 | `test_recusa_da_receita_para_antes_das_listas` | Qualquer recusa da Receita | Sanções, PEP e account-api: nenhuma chamada | Ordem |
| F6-09 | `test_dados_divergentes_vao_para_revisao` | Receita devolve outro nome; em outro caso, outra data | `MANUAL_REVIEW`, `RECEITA_DADOS_DIVERGENTES` | Receita |
| F6-10 | `test_comparacao_do_nome_ignora_maiuscula_e_acento` | `JOSÉ DA SILVA` na Receita, `Jose da Silva` no cadastro | `ACTIVE` | Decisão D13 |
| F6-11 | `test_pessoa_sancionada_e_recusada` | Sanções com `match` | `REJECTED`, `SANCTIONS_MATCH`; account-api nunca chamada | Sanções |
| F6-12 | `test_pep_na_lista_vai_para_revisao` | PEP com `pep` | `MANUAL_REVIEW`, `PEP_MATCH`, `HIGH` | PEP |
| F6-13 | `test_pep_declarado_vai_para_revisao` | `pep_self_declared` verdadeiro | `MANUAL_REVIEW`, `PEP_SELF_DECLARED`, `HIGH` | PEP |
| F6-14 | `test_pf_jovem_com_renda_alta_vai_para_revisao` | 20 anos, renda 3.000.001 centavos | `MANUAL_REVIEW`, `INCOME_PROFILE`, `MEDIUM` | PLD |
| F6-15 | `test_pf_jovem_no_limite_da_renda_e_aprovada` | 20 anos, renda 3.000.000 | `ACTIVE` | Borda da renda |
| F6-16 | `test_pf_que_completa_21_hoje_com_renda_alta_e_aprovada` | 21 anos hoje, renda 3.000.001 | `ACTIVE` | Borda da idade |
| F6-17 | `test_renda_acima_de_500_mil_vai_para_revisao` | Renda 50.000.001; em outro caso, 50.000.000 | `MANUAL_REVIEW` `INCOME_PROFILE`; o outro `ACTIVE` | PLD e borda |
| F6-18 | `test_empresa_nova_com_faturamento_alto_vai_para_revisao` | PJ de 179 dias com 30.000.001; 180 dias com 30.000.001; 179 dias com 30.000.000 | Só o primeiro vai a `MANUAL_REVIEW` `INCOME_PROFILE`; os outros `ACTIVE` | PLD e bordas |
| F6-19 | `test_duas_regras_dao_risco_alto` | 20 anos, renda 50.000.001 (as duas regras de renda) | `MANUAL_REVIEW`, `HIGH` | Nível de risco |
| F6-20 | `test_pep_e_renda_listam_os_dois_motivos` | PEP declarado e renda alta | `reason_codes` com os dois motivos, `HIGH` | Motivos |
| F6-21 | `test_verificacoes_nunca_mostram_os_dados_consultados` | Qualquer análise | Cada `check` tem só `check_type`, `result` e `reason_code` | LGPD |
| F6-22 | `test_account_api_fora_mantem_aprovada_e_tenta_de_novo` | account-api com `503` na primeira chamada e `201` depois | `APPROVED` enquanto falha; depois `ACTIVE`; duas chamadas com a mesma `X-Idempotency-Key` | Retentativa (`slow`) |
| F6-23 | `test_conta_que_ja_existe_e_reaproveitada` | account-api responde `200` com uma conta já existente | `ACTIVE` com essa `account_key` | Uma conta por cliente |
| F6-24 | `test_cada_abertura_e_analisada_uma_vez` | 10 aberturas completas juntas | Cada documento consultado uma vez na Receita; uma conta pedida por abertura | `SKIP LOCKED` (`concurrency`) |

### F7. Birô fora do ar

Arquivo `test_bureau_down.py`.

| ID | Teste | Prepara e age | Espera | Regra |
|---|---|---|---|---|
| F7-01 | `test_biro_fora_mantem_em_analise` | Receita com `503` para o CPF | Três chamadas (uma mais 2 retentativas); `ANALYSIS`; account-api nunca chamada | Na dúvida, não aprova |
| F7-02 | `test_timeout_do_biro_conta_como_falha` | Receita com atraso de 3 s | `ANALYSIS` | Timeout de 2 s |
| F7-03 | `test_conexao_derrubada_conta_como_falha` | Conexão derrubada | `ANALYSIS` | Falha |
| F7-04 | `test_biro_de_volta_retoma_a_analise` | Receita com `503` três vezes e depois regular | `ACTIVE` em até 75 s | Nova tentativa em 1 min (`slow`) |
| F7-05 | `test_biro_fora_por_24h_vai_para_revisao` | RG completo "há 25 h"; Receita com `503` | `MANUAL_REVIEW`, `BUREAU_UNAVAILABLE` | 24 h (`simulated_clock`) |
| F7-06 | `test_biro_fora_por_23h_continua_em_analise` | RG completo "há 23 h"; Receita com `503` | `ANALYSIS` | Borda das 24 h (`simulated_clock`) |
| F7-07 | `test_circuito_abre_depois_de_cinco_falhas` | Falhas seguidas até abrir; depois uma abertura nova com a Receita regular | Durante 30 s, nenhuma chamada nova à Receita, e a abertura fica em `ANALYSIS`; depois, uma chamada de teste e o circuito fecha | Circuit breaker (`global_state`, `slow`) |
| F7-08 | `test_retentativa_em_lote_devolve_para_a_fila` | Abertura em `BUREAU_UNAVAILABLE`; Receita volta; `POST /admin/onboardings/retry` com a chave | `202`, `requeued_count` 1; depois `ACTIVE`; histórico `MANUAL_REVIEW`, `PENDING_KYC` | Retentativa em lote |
| F7-09 | `test_retentativa_em_lote_mantem_os_outros_motivos` | Abertura em `MANUAL_REVIEW` por PEP, com a chave na lista | `requeued_count` 0; continua `MANUAL_REVIEW` | Só `BUREAU_UNAVAILABLE` |
| F7-10 | `test_retentativa_sem_chaves_pega_todas_com_biro_fora` | Sem `onboarding_keys` | A abertura do teste volta para a fila; `requeued_count` pelo menos 1 | Retentativa em lote |
| F7-11 | `test_retentativa_com_biro_ainda_fora_nao_muda_nada` | Saúde da Receita com `503` | `503 ONB005016`; a abertura continua `MANUAL_REVIEW` | `global_state` |
| F7-12 | `test_retentativa_em_lote_confere_o_corpo` | `onboarding_keys` que não é lista, ou com item que não é UUID | `400 ONB000001` | Schema |

### F8. Compliance: fila e decisão

Arquivo `test_compliance.py`.

| ID | Teste | Prepara e age | Espera | Regra |
|---|---|---|---|---|
| F8-01 | `test_fila_lista_da_mais_antiga_para_a_mais_nova` | Duas aberturas por PEP, A antes de B; percorre as páginas de `GET /onboardings?reason_code=PEP_SELF_DECLARED` | A aparece antes de B | Fila |
| F8-02 | `test_fila_usa_os_valores_padrao` | Sem parâmetros | `limit` 10, `page` 0, só `MANUAL_REVIEW` | Padrões |
| F8-03 | `test_fila_filtra_pela_etapa` | `status=REJECTED` | Traz a recusada do teste, não a que está em revisão | Filtro |
| F8-04 | `test_fila_marca_a_ultima_pagina` | Filtro sem nenhum resultado; percorrer até o fim | `data` vazio e `is_last_page` verdadeiro; última página com até `limit` itens | Paginação |
| F8-05 | `test_fila_recusa_parametro_errado` | Parametrizado: `limit` 0, 101 e `abc`; `page` -1; `status` e `reason_code` desconhecidos; parâmetro a mais (`document_number`) | `400 ONB000001` | Schema, LGPD |
| F8-06 | `test_itens_da_fila_nao_mostram_dado_pessoal` | Qualquer item | Sem CPF, nome ou renda | LGPD |
| F8-07 | `test_aprovacao_de_compliance_abre_a_conta` | `APPROVE` com justificativa | `202` `APPROVED`; depois `ACTIVE`; o evento traz `actor` `compliance`, a justificativa e quem decidiu | Decisão |
| F8-08 | `test_recusa_de_compliance_e_definitiva` | `REJECT` com justificativa | `200` `REJECTED`, `COMPLIANCE_REJECTED`; account-api nunca chamada | Decisão |
| F8-09 | `test_decisao_fora_de_revisao_e_recusada` | Abertura em `DRAFT`; abertura `ACTIVE`; abertura recusada por sanção | `409 ONB005014` | Etapa |
| F8-10 | `test_decisao_exige_decisao_e_justificativa` | Sem `decision`; sem `justification` | `400 ONB005001`, com o campo | Obrigatório |
| F8-11 | `test_limites_do_tamanho_da_justificativa` | 9 e 501 caracteres; 10 e 500 caracteres | `400 ONB000001` (`minimum`, `maximum`); os outros aceitos | Bordas |
| F8-12 | `test_decisao_so_aceita_approve_ou_reject` | `MAYBE` | `400 ONB000001` | Schema |
| F8-13 | `test_decisao_em_abertura_que_nao_existe_responde_404` | UUID que ninguém criou | `404 ONB005006` | R8 |
| F8-14 | `test_decisoes_simultaneas_valem_uma_vez` | `APPROVE` e `REJECT` juntos | Um aceito, o outro `409 ONB005014`; um só evento de decisão | `concurrency` |
| F8-15 | `test_decisao_exige_a_chave_idempotente` | Sem o cabeçalho | `400 ONB000011` | Decisão D7 |

### F9. Outbox e eventos para a webhook-api

Arquivo `test_events.py`. O teste lê no Mockserver os pedidos recebidos em `POST /internal/event` com a `onboarding_key` dele.

| ID | Teste | Prepara e age | Espera | Regra |
|---|---|---|---|---|
| F9-01 | `test_aprovacao_publica_aprovada_e_depois_criada` | Abertura aprovada | `account.kyc.approved` (`onboarding_key`, `customer_key`, `risk_level`) e depois `account.created` (mais `account_key`); cada um com `event_id` UUID e `occurred_at` | Eventos |
| F9-02 | `test_recusa_publica_recusada` | Recusa da Receita | `account.rejected` com `onboarding_key` e `reason_codes` | Eventos |
| F9-03 | `test_revisao_publica_revisao` | PEP | `account.kyc.manual_review` com `reason_codes` | Eventos |
| F9-04 | `test_aprovacao_de_compliance_publica_aprovada` | Compliance aprova | `account.kyc.approved` | Eventos |
| F9-05 | `test_eventos_nao_levam_dado_pessoal` | Todos os eventos acima | Nenhum traz CPF ou CNPJ, nome, renda ou data; `data` tem só os campos da tabela da RFC | LGPD |
| F9-06 | `test_cada_mudanca_publica_uma_vez` | Abertura aprovada | Cada tipo de evento chega uma vez; `DRAFT`, `PENDING_KYC` e `ANALYSIS` não publicam nada | Outbox |
| F9-07 | `test_webhook_fora_reenvia_o_mesmo_event_id` | webhook-api com `503` na primeira entrega | O evento chega de novo com o mesmo `event_id` | Retentativa (`slow`) |
| F9-08 | `test_eventos_vao_com_service_token` | Qualquer evento | Cabeçalho `SERVICE-TOKEN` presente | Rotas internas |

### F10. LGPD, transversal

Arquivo `test_lgpd.py`. Junta o que os outros já provam e acrescenta dois testes.

| ID | Teste | Prepara e age | Espera | Regra |
|---|---|---|---|---|
| F10-01 | `test_nenhuma_rota_recebe_dado_pessoal_na_url` | `GET /onboardings?document_number=...` | `400 ONB000001` (parâmetro desconhecido) | Nada pessoal na URL |
| F10-02 | `test_log_nunca_tem_documento_nem_renda` | Jornada completa com recusas no meio; lê `docker compose logs` da API e do worker | Nem o CPF (com e sem máscara) nem a renda aparecem | Nada pessoal no log (pula se não houver `docker`) |

Os outros pontos da LGPD já têm teste: respostas (F1-03, F3-02, F3-06), erros (F1-34), verificações (F6-21), fila (F8-06), eventos (F9-05) e dados apagados no prazo (F5-04).

## 4. Matriz de cobertura

**Códigos de erro**

| Código | Status | Testes |
|---|---|---|
| `ONB000001` | 400 | F1-11, F1-12, F1-13, F1-14, F7-12, F8-05, F8-11, F8-12, F10-01 |
| `ONB000002` | 403 | F0-03 |
| `ONB000003` | 401 | F3-11 |
| `ONB000006` | 401 | F3-12, F3-13, F3-14 |
| `ONB000007` | 401 | F3-15 |
| `ONB000008` | 403 | F3-16 |
| `ONB000011` | 400 | F1-30, F1-31, F4-19, F8-15 |
| `ONB000012` | 409 | F1-28 |
| `ONB000404` | 404 | F0-04 |
| `ONB005001` | 400 | F1-08, F1-09, F1-10, F4-11, F8-10 |
| `ONB005002` | 400 | F1-21 |
| `ONB005003` | 409 | F1-22, F1-23, F1-24 |
| `ONB005004` | 422 | F1-15, F1-16, F1-17 |
| `ONB005005` | 422 | F1-18, F1-19, F1-20 |
| `ONB005006` | 404 | F3-03, F3-04, F4-16, F8-13 |
| `ONB005007` | 404 | F3-08, F3-09, F5-04 |
| `ONB005008` | 409 | F4-15 |
| `ONB005009` | 409 | F4-12, F4-13, F4-18, F4-23 |
| `ONB005010` | 410 | F5-01, F5-02, F5-07 |
| `ONB005011` | 413 | F4-08 |
| `ONB005012` | 422 | F4-09, F4-10 |
| `ONB005013` | 429 | F2-01, F2-03, F2-07 |
| `ONB005014` | 409 | F8-09, F8-14 |
| `ONB005015` | 503 | F4-17 |
| `ONB005016` | 503 | F7-11 |

**Motivos (`reason_codes`)**

| Motivo | Testes |
|---|---|
| `RECEITA_SUSPENSA`, `RECEITA_CANCELADA`, `RECEITA_TITULAR_FALECIDO`, `RECEITA_NULA`, `RECEITA_PENDENTE_REGULARIZACAO` | F6-05 |
| `RECEITA_CNPJ_SUSPENSA`, `RECEITA_CNPJ_INAPTA`, `RECEITA_CNPJ_BAIXADA`, `RECEITA_CNPJ_NULA` | F6-06 |
| `RECEITA_NAO_ENCONTRADO` | F6-07 |
| `RECEITA_DADOS_DIVERGENTES` | F6-09 |
| `SANCTIONS_MATCH` | F6-11 |
| `PEP_MATCH` | F6-12 |
| `PEP_SELF_DECLARED` | F6-13, F6-20 |
| `INCOME_PROFILE` | F6-14, F6-17, F6-18, F6-19, F6-20 |
| `BUREAU_UNAVAILABLE` | F7-05, F7-08 |
| `COMPLIANCE_REJECTED` | F8-08 |

**Transições do ciclo de vida**

| Transição | Testes |
|---|---|
| início para `DRAFT` | F1-01 |
| `DRAFT` para `DRAFT` (falta um lado) | F4-03, F4-21 |
| `DRAFT` para `PENDING_KYC` | F4-01, F4-02, F4-04, F4-22 |
| `DRAFT` para `EXPIRED` | F5-01, F5-04 |
| `PENDING_KYC` para `ANALYSIS` | F6-01 (histórico) |
| `ANALYSIS` para `ANALYSIS` (birô fora) | F7-01, F7-02, F7-03 |
| `ANALYSIS` para `APPROVED` | F6-01 |
| `ANALYSIS` para `MANUAL_REVIEW` | F6-09, F6-12, F6-14, F7-05 |
| `ANALYSIS` para `REJECTED` | F6-05, F6-11 |
| `APPROVED` para `APPROVED` (account-api fora) | F6-22 |
| `APPROVED` para `ACTIVE` | F6-01, F6-23 |
| `MANUAL_REVIEW` para `APPROVED` | F8-07 |
| `MANUAL_REVIEW` para `REJECTED` | F8-08 |
| `MANUAL_REVIEW` para `PENDING_KYC` | F7-08 |

**Eventos**

| Evento | Testes |
|---|---|
| `account.kyc.approved` | F9-01, F9-04 |
| `account.created` | F9-01 |
| `account.rejected` | F9-02 |
| `account.kyc.manual_review` | F9-03 |

**As nove garantias da RFC 05**

| Garantia | Testes |
|---|---|
| Sem KYC aprovado, sem conta | F6-02, F6-08, F6-11, F7-01, F8-08 |
| Na dúvida, não aprova | F7-01 a F7-07 |
| Nada em dobro | F1-24, F1-27, F1-32, F4-18, F4-22, F4-23, F6-03, F6-22, F6-24, F8-14, F9-06 |
| Prazo de 20 minutos | F5-01 a F5-07 |
| Dado pessoal protegido | F1-03, F1-13, F1-34, F3-02, F6-21, F8-06, F9-05, F10-01, F10-02 |
| Abuso contido | F2-01 a F2-07 |
| Credencial válida e no prazo | F1-04, F3-11 a F3-16 |
| Cada um vê só o que é seu | F3-03, F3-04, F3-08, F3-09, F4-16 |
| Motivo e próximo passo sempre claros | F1-08, F1-11, F1-33, F3-01, F4-03, F4-21 |

## 5. O que o black box não alcança

Ficam fora deste plano, com o motivo. Se o time quiser, cada um vira um roteiro manual ou um teste de outra suíte.

- **Posse do worker depois de uma queda** (`lease_until`): precisa derrubar o worker no meio da análise. Roteiro manual com `docker compose kill onboarding-worker`.
- **Circuit breaker compartilhado entre réplicas** pelo Redis: precisa de duas réplicas do worker.
- **Comunicação ao Coaf registrada** no caso de sanção: nenhuma rota mostra esse registro.
- **Chave do Redis com o SHA-256 do documento, e não o CPF puro:** é detalhe interno.
- **Link assinado de 5 minutos do RG para compliance:** a RFC cita o link e o registro de cada acesso, mas a tabela de rotas não tem essa rota (pendência P1 abaixo).
- **Foto sem linha no bucket:** quando o envio é recusado depois de a foto subir (outro envio da mesma abertura ganhou a trava), a foto fica no bucket sem linha no banco. A RFC aceita esse pior caso ("nunca uma linha sem foto"). O caminho começa com `rg/{onboarding_key}/`, e o vencimento da F5 pode apagar pelo prefixo. O teste não vê, porque nunca lê o bucket.
- **`UNIQUE(onboarding_id, side)` como última garantia no envio do RG:** a conferência depois da trava já recusa o lado repetido, e a janela que sobra para o `UNIQUE` é pequena demais para um teste provocar. A mutação que tira a trava e o tratamento do `UNIQUE` juntos sobrevive por isso.
- **A conexão devolvida antes de chamar o bucket:** o envio do RG encerra a leitura (`rollback`, sem nada gravado) antes do `PutObject`, para não segurar conexão nem trava durante até 10 s. Não aparece por HTTP.
- **O que é do gateway:** `QIT000013` (chave em processamento), `QIT000014` (limite por origem e credencial), `QIT000015` (pedido longo demais) e o replay com `Idempotent-Replayed`. Vão para o plano da gateway-api.

## 6. Decisões a confirmar com o time

Cada uma muda um teste. Enquanto o time não confirmar, vale a proposta. As marcadas como **decidida** já estão nas RFCs.

| | Ponto em aberto | Proposta deste plano |
|---|---|---|
| D1 | A RFC não define o contrato dos birôs | O da seção 2.2; entra na RFC 05 |
| D2 | A RFC 05 manda só `customer_key` para `POST /internal/account`; a RFC 02 pede também `type` | Mandar `customer_key` e `type`, com `SERVICE-TOKEN` e `X-Idempotency-Key` |
| D3 | Quem emite a credencial de compliance | **Decidida em 06/10 (opção a), na RFC 05 v0.6:** um JWT com `scope` `compliance`, assinado com a mesma `AUTH_SECRET`, que vence em 1 hora; o `sub` identifica o analista e fica no histórico como quem decidiu. Nos testes, o próprio teste fabrica. A senha fixa, como o `OPERATOR_TOKEN`, foi descartada |
| D4 | Como o gateway informa o IP de origem | `X-Forwarded-For` (o primeiro IP); sem ele, o IP da conexão. O `X-Test-Client-Ip` fica só no gateway |
| D5 | O que conta como "recusa da origem" | Só o `409 ONB005003` (documento que já é cliente), como diz a tabela de cenários |
| D6 | Campos de um tipo enviados no outro (PF com `opening_date`) | `400 ONB000001`, porque só se coleta o necessário |
| D7 | A onboarding-api sem o gateway na frente, recebendo pedido sem `X-Idempotency-Key` | Ela repete a conferência do gateway em todo `POST` e `PUT`, com o código dela, `400 ONB000011` (o gateway responde `QIT000011`) |
| D8 | Mesma chave com pedido diferente, quando o Redis perdeu a chave | `409 ONB000012` (no gateway, `QIT000012`), conferido pelo `request_hash` |
| D9 | Repetir o `POST` de uma abertura vencida | `410 ONB005010`, porque o cadastro foi apagado |
| D10 | O gateway guarda a resposta do `POST` por 24 h, mas o token vale 1 h, e o replay devolveria um token vencido | **Decidida em 06/10 (opção a), nas RFCs 00 e 05 v0.6:** no `POST /onboarding` o gateway só reserva a chave enquanto o pedido roda (`409 QIT000013`) e não guarda a resposta. A repetição segue para a onboarding-api, que devolve a mesma abertura com credencial nova (F1-27) |
| D11 | Regra da mensagem de formato | `rule` só com `required`, `format`, `type`, `minimum` e `maximum`; campo a mais e valor fora da lista viram `format` |
| D12 | Obrigatório e formato errados no mesmo pedido | Vence o `400 ONB005001` |
| D13 | Como comparar nome e data com a Receita | Nome sem acento, sem diferença de maiúscula e sem espaço sobrando; data igual |
| D14 | PEP na PJ | Consulta pelo CNPJ, porque a RFC não guarda os dados do sócio |
| D15 | O que é uma falha que abre o circuito | Cada chamada que deu timeout, conexão recusada ou `5xx`. Um `4xx` que não é resposta prevista (como o `404` vazio de um mock sem expectativa) não abre o circuito, mas também não aprova: a abertura fica em `ANALYSIS` |
| D16 | Relógio simulado | Cabeçalho `X-Simulated-Now` (data e hora ISO 8601), só com `SIMULATED_CLOCK_ENABLED=true`, aceito no `POST /onboarding` e no envio do RG |
| D17 | Falhas simuladas | `X-Fault-Injection: bucket_unavailable` e `redis_unavailable`, só com `FAULT_INJECTION_ENABLED=true` |
| D18 | "Hoje" para idade e datas | O dia em `America/Sao_Paulo`, na API e nos testes, para o teste da borda não falhar à noite |
| D19 | Prefixo dos códigos de erro | **Decidida em 06/10, na RFC 05 v0.6:** todo erro que a onboarding-api responde começa com `ONB` (`ONB000xxx` nos gerais, `ONB005xxx` nos dela). Os que só o gateway responde continuam `QIT` |
| D20 | Onde moram as tabelas da onboarding | **Decidida em 06/10:** no banco único do grupo (`bootcamp`), seção 7 do `database/database.sql`. `customer` e `customer_document` seguem a definição do grupo; a onboarding preenche o `request_key` com a `onboarding_key` (como pede o `bancos.md`), e renda, ocupação e PEP ficam na tabela `onboarding` |
| D21 | Onde ficam os documentos do RG | **Decidida em 06/10:** numa tabela da abertura, `onboarding_document`, ligada pelo `onboarding_id`, uma linha por imagem, com `UNIQUE(onboarding_id, side)`. A `customer_document` do grupo fica como está, e a onboarding não grava nela |
| D22 | A RFC diz que o `GET` mostra os lados do RG recebidos, mas não diz o formato | **Decidida em 07/10, na RFC 05 v0.7:** `documents` é uma lista, na ordem de chegada, com `side`, `content_type` (o que os bytes dizem), `size_bytes` e `created_at` de cada imagem. Nunca o caminho no bucket. A resposta do `PUT` traz `onboarding_key`, `status` e `next_step` |
| D23 | A RFC diz `SEND_BACK` quando falta um lado, mas a pessoa pode mandar o verso primeiro | **Decidida em 07/10, na RFC 05 v0.7:** só a frente, `SEND_BACK`; só o verso, `SEND_FRONT` |

**Pendências da RFC encontradas no caminho**

- **P1.** A RFC cita o link assinado do RG para compliance, mas não há rota para ele.
- **P2.** O contrato da webhook-api ainda é "a confirmar" (RFC da webhook-api não escrita).
- **P3.** Resolvida pela D10: o gateway não guarda mais a resposta do `POST /onboarding`.

## 7. Ordem de trabalho

| Fatia | Testes | Depende de |
|---|---|---|
| F0 | 4 | Compose com a onboarding-api e as tabelas dela no `database.sql` |
| F1 | 34 | F0 |
| F2 | 7 | F1 e Redis |
| F3 | 16 | F1 |
| F4 | 23 | F3 e LocalStack |
| F5 | 7 | F4 e o worker (vencimento) |
| F6 | 24 | F4, worker e Mockserver |
| F7 | 12 | F6 |
| F8 | 15 | F6 |
| F9 | 8 | F6 |
| F10 | 2 | Todas |

São 152 testes, sem contar os casos dos parametrizados. Cada fatia termina com um commit que diz quais IDs deste plano ficaram verdes.
