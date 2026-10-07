# RFC 06 - Webhooks de Saída (Outgoing) e Padrão Outbox

## 1. Contextualização e Objetivo
No nosso Banco Digital, precisamos notificar parceiros e clientes corporativos quando eventos importantes acontecem, como:
- Uma transação bancária falhou ou foi concluída com sucesso.
- O cadastro de uma nova conta foi aprovado ou mandado para revisão manual.

Em vez de forçar os clientes a ficarem consultando nossa API o tempo todo para saber se o status mudou (o que chamamos de *Polling* e que sobrecarrega nossos servidores), nós enviamos uma notificação ativamente para o sistema deles via uma requisição HTTP POST. Essa notificação é o **Webhook**.

A `webhook-api` será o microsserviço responsável exclusivamente por **disparar essas notificações para a internet**.

---

## 2. O Grande Desafio (E a Solução)

Sistemas financeiros não podem perder mensagens. Considere dois problemas graves:

1. **Problema Interno:** A API Principal aprova uma transação e tenta enviar um webhook, mas no exato milissegundo antes de enviar, o nosso servidor sofre um pico de energia e reinicia. A transação foi feita no banco de dados, mas o cliente nunca foi avisado.
2. **Problema Externo:** Nós tentamos avisar o cliente, mas o servidor dele está fora do ar naquele momento (Erro 503). O que fazemos? Desistimos? 

Para resolver isso de forma profissional, usaremos dois padrões de engenharia: o **Transactional Outbox Pattern** e **Filas com Exponential Backoff (Redis)**.

### 2.1. O que é o Transactional Outbox Pattern?
A regra de ouro é: **A ação e a intenção do aviso devem ser salvas juntas.**
Quando a `api` aprova uma transação, ela abre uma transação no banco de dados (PostgreSQL) e faz DUAS coisas antes de dar o `COMMIT`:
1. Altera o status da transação para `success`.
2. Insere uma linha em uma tabela chamada `webhook_outbox` (ex: `{"event": "transaction.success", "payload": {...}}`).

Como as duas ações ocorrem na mesma transação de banco de dados, é **impossível** que a transação mude de status sem que a mensagem vá para a "caixa de saída" (Outbox). Se faltar energia, o banco de dados desfaz tudo (Rollback) e o estado fica consistente.

### 2.2. Como o Redis e o Exponential Backoff entram nisso?
A tabela `webhook_outbox` é apenas uma tabela passiva. Precisamos de um motor forte para pegar as mensagens dessa tabela e enviar pela internet aos milhares. É aí que entra o **Redis** operando como um "gerenciador de fila" (provavelmente usando bibliotecas como Celery, RQ ou integradas via background tasks).

**O fluxo funciona assim:**
1. A `webhook-api` lê a tabela `webhook_outbox`.
2. Ela empurra essa mensagem para uma fila dentro da memória ultra-rápida do **Redis**.
3. *Workers* (trabalhadores da `webhook-api`) puxam as mensagens do Redis e fazem a requisição HTTP POST para o cliente.

**E se o servidor do cliente der erro (Exponential Backoff)?**
Se o cliente estiver fora do ar, o Redis não perde a mensagem. Nós configuramos uma política de **Exponential Backoff Retries** (Tentativas com recuo exponencial). 
O Redis tira a mensagem da fila principal e agenda para tentar novamente de forma espaçada, para não sobrecarregar o cliente que já está com problemas:
- Falhou a 1ª vez? Tenta de novo em **1 minuto**.
- Falhou a 2ª vez? Tenta de novo em **2 minutos**.
- Falhou a 3ª vez? Tenta de novo em **4 minutos**.
- Falhou a 4ª vez? Tenta de novo em **8 minutos**.

E assim por diante, até um limite máximo (ex: 5 tentativas). Se falhar em todas, marcamos a mensagem como "Falhou" (Dead Letter) para análise futura, mas garantimos que fizemos o máximo para entregar.

---

## 3. Segurança e Contratos

### 3.1. Assinatura Criptográfica (HMAC)
Como o cliente vai saber que aquele Webhook (um simples POST recebido na internet) realmente veio do nosso Banco e não de um hacker fingindo ser nós?

Todo webhook que a nossa `webhook-api` disparar conterá um **Header de Assinatura** (Exemplo: `X-Banco-Signature`). 
A nossa API pegará o corpo (payload) que está sendo enviado, aplicará uma função matemática (HMAC-SHA256) usando uma **Chave Secreta** que só o nosso banco e aquele cliente específico conhecem. O cliente fará a mesma conta matemática do lado dele; se os resultados baterem, ele tem certeza matemática de que fomos nós que enviamos.

### 3.2. Exemplos de Eventos
- `transaction.created`
- `transaction.success`
- `transaction.failed`
- `account.approved`
- `account.manual_review`

---

## 4. O Fluxo Completo Resumido

1. `api` aprova transação.
2. `api` salva a transação e insere um registro em `webhook_outbox` no mesmo COMMIT.
3. `webhook-api` lê `webhook_outbox` e manda para uma fila no **Redis**.
4. O *Worker* lê a fila, assina a mensagem criptograficamente e envia (HTTP POST).
5. Deu Sucesso (200 OK)? O registro é marcado como `DELIVERED`.
6. Deu Erro? O Redis agenda um novo envio multiplicando o tempo de espera (Exponential Backoff).
