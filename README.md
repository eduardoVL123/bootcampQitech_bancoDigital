# Banco digital, Bootcamp QI Tech 2026

Um **banco digital operado só por API REST, sem tela**. Em **Python +
FastAPI**, com **PostgreSQL**, tudo rodando em **Docker**.

O que ele faz: cadastra o cliente, abre a conta, deposita, transfere
cobrando tarifa, devolve o extrato paginado e fecha a conciliação em
zero. Abertura de conta em etapas, com foto do RG em bucket e análise de
KYC, mora numa API própria.

**A promessa do projeto é que cada centavo pode ser explicado:** o saldo
nunca fica negativo, nada é cobrado duas vezes, nada fica pela metade, e
o extrato sempre fecha com o saldo. A seção 1 mostra isso acontecendo em
oito comandos.

Você não precisa saber programar para começar. As APIs e o banco sobem
no **Docker**, então você não instala nem um nem outro na sua máquina.
Os **testes** rodam no seu Python, e a seção 2 mostra como.

---

## 0. O que você precisa ter instalado

São três coisas.

| O quê | Para quê | Como conferir |
|---|---|---|
| **Docker** (com o Docker Desktop no Mac/Windows) | roda a API e o banco | `docker compose version` |
| **Git** | trazer o projeto para o seu computador | `git --version` |
| **Python 3.11 ou mais novo** | rodar os testes (seção 2) | `python3 --version` |

Abra o terminal e rode os três comandos da coluna da direita. Se todos
responderem um número de versão, você está pronto.

> **Por que o Python, se tudo roda no Docker?** Porque os testes rodam
> FORA dele, na sua máquina, contra a API que está de pé no container.
> O ganho é o ciclo: você salva um teste e roda na hora, sem esperar
> imagem nenhuma ser montada. O preço está explicado na seção 2.

> **`docker compose version` deu erro?** Sua instalação do Docker é
> antiga demais (ou o Docker não está ligado). No Mac e no Windows,
> abra o **Docker Desktop** e espere a baleia parar de se mexer. Se o
> comando continuar falhando, reinstale pelo site oficial —
> o `docker compose` (com **espaço**) vem junto desde 2022.

Nada além destes três. Se em algum momento este projeto pedir que você
instale outro PROGRAMA, é um bug do projeto — avise a gente. (As
bibliotecas Python que os testes usam são outra conversa: elas entram
com um `pip install` na seção 2, dentro de uma pasta do próprio
projeto, e somem quando você apaga essa pasta.)

---

## 1. Rodando pela primeira vez

```bash
docker compose up
```

Um comando. Só isso, e não precisa criar nem copiar arquivo nenhum
antes: as configurações já vêm com valor padrão dentro do
`docker-compose.yml`.

O Docker baixa o Python, sobe o banco, cria as tabelas e liga a API. Na
primeira vez demora alguns minutos; depois é quase instantâneo.

São oito coisas de pé, e vale saber o nome de cada uma:

| Serviço | Porta | O que é |
|---|---|---|
| `api` | 3000 | conta, saldo, livro de lançamentos, extrato, transação e tarifa. **A única que altera saldo** |
| `customer-api` | 3010 | o cliente: cadastro, consulta e documento |
| `onboarding-api` | 3005 | abertura de conta em etapas, retomável, com RG e KYC |
| `onboarding-worker` | sem porta | processo separado, mesmo código: analisa KYC, vence aberturas paradas, entrega a caixa de saída |
| `db` | 5432 | o banco (PostgreSQL 16). Um banco só, chamado `bootcamp`, com uma seção por API |
| `redis` | 6379 | só dado pequeno e reconstruível: limites por origem e estado do circuit breaker. **Nunca saldo** |
| `localstack` | 4566 | emula o S3 para a foto do RG, sem custo de AWS |
| `mockserver` | 1080 | só nos testes, no lugar dos birôs de consulta |

Se o `redis` cair, tudo continua funcionando, só mais devagar. Se o
`localstack` cair, o envio do RG falha e a abertura fica na etapa, sem
perder o que já foi feito.

Quando aparecer `Application startup complete`, a API está no ar. Abra
no navegador:

### 👉 http://localhost:3000

Você vai ver isto:

```json
{"service":"bootcamp-api","id":"8"}
```

Pouca coisa, e de propósito: essa rota só diz "estou viva, e eu sou este
serviço". Mas você acabou de fazer uma **requisição HTTP** — a mesma
coisa que o navegador faz ao abrir qualquer site.

### Agora o banco, de ponta a ponta

As outras rotas não abrem no navegador, porque exigem cabeçalhos. Para
mandar cabeçalho a gente usa o `curl`, que já vem instalado no Mac, no
Linux e no Windows.

**Abra um segundo terminal**, porque o primeiro está ocupado rodando as
APIs, e cole um comando de cada vez. As saídas abaixo são reais, tiradas
de uma execução de verdade: as chaves nascem diferentes a cada vez, e
você troca as do exemplo pelas suas.

> **No Windows**, use o **Git Bash**: ele veio junto com o Git da seção
> 0. No PowerShell estes comandos não funcionam, porque lá `curl` é o
> apelido de outro programa, com outra sintaxe.

A jornada é a que o projeto promete: **Ana recebe R$ 1.000, transfere
R$ 100 para o Bruno, paga R$ 2 de tarifa e fica com R$ 898.** Os quatro
lançamentos somam zero, e no fim a conciliação prova isso.

#### 1. Cadastrar o cliente (customer-api, porta 3010)

```bash
curl -X POST http://localhost:3010/internal/customer \
  -H "INTERNAL-TOKEN: default_token" \
  -H "Content-Type: application/json" \
  -d '{
    "request_key": "e881d42f-38ef-4c8a-83f5-fc4db2402950",
    "type": "PF",
    "name": "Ana Souza",
    "document_number": "130.412.731-10",
    "birth_date": "1990-01-01"
  }'
```

```json
{"customer_key":"ac270637-501b-4e76-a955-67322548f3d3","type":"PF","name":"Ana Souza","created_at":"2026-10-09T12:56:57.178984+00:00"}
```

O `request_key` é o que torna esta rota **idempotente**: repetir o mesmo
pedido com a mesma chave devolve o cliente que já existe, em vez de criar
um segundo. O CPF precisa ser válido de verdade, com os dois dígitos
finais batendo com a conta.

**Faça isto duas vezes**, com `request_key`, nome e CPF diferentes: a
segunda pessoa é o Bruno, que vai receber a transferência.

#### 2. Abrir a conta

```bash
curl -X POST http://localhost:3000/internal/account \
  -H "INTERNAL-TOKEN: default_token" \
  -H "Content-Type: application/json" \
  -d '{"customer_key": "ac270637-501b-4e76-a955-67322548f3d3"}'
```

```json
{"account_key":"bdc7f4af-b7f3-4b4a-90b1-6266f125e41d","balance":0,"status":"ACTIVE"}
```

Repita para o Bruno. Pedir duas vezes para a **mesma** pessoa responde
`200` com a mesma `account_key`, e não `201`: é no máximo uma conta não
encerrada por cliente, garantido por um índice único parcial no banco, e
não por uma checagem no código.

#### 3. Depositar R$ 1.000

Daqui para frente as rotas pedem **quem** está chamando, e não só qual
aplicação: é a credencial, no cabeçalho `Authorization` (seção 6).
Depósito é operação de operador, porque quem deposita cria dinheiro no
sistema.

```bash
curl -X POST http://localhost:3000/transaction \
  -H "INTERNAL-TOKEN: default_token" \
  -H "Authorization: Bearer <credencial de operador>" \
  -H "Idempotency-Key: um-uuid-seu" \
  -H "Content-Type: application/json" \
  -d '{
    "type": "DEPOSIT",
    "destination_account_key": "bdc7f4af-b7f3-4b4a-90b1-6266f125e41d",
    "amount": 100000
  }'
```

```json
{"transaction_key":"112cb867-0476-45dd-ada2-7b652e545918","type":"DEPOSIT","status":"COMPLETED","amount":100000,"fee_amount":0,"fee_policy_key":null,"origin_account_key":"3884e3d1-077d-4a78-bd51-81e13142fa99","destination_account_key":"bdc7f4af-b7f3-4b4a-90b1-6266f125e41d","created_at":"2026-10-09T12:56:57.254056+00:00"}
```

`100000` é **R$ 1.000,00 em centavos**: dinheiro é inteiro do JSON até o
banco, nunca `float`. O `origin_account_key` que apareceu sozinho é a
conta técnica `SETTLEMENT`, a contrapartida do depósito: o dinheiro não
nasce do nada, ele sai de uma conta que pode ficar negativa de propósito.

O `Idempotency-Key` é o que protege o cliente dele mesmo: mandar o mesmo
depósito dez vezes com a mesma chave credita **uma**.

#### 4. Transferir R$ 100 para o Bruno

Agora a credencial é a da Ana, porque o dinheiro sai da conta dela.

```bash
curl -X POST http://localhost:3000/transaction \
  -H "INTERNAL-TOKEN: default_token" \
  -H "Authorization: Bearer <credencial da Ana>" \
  -H "Idempotency-Key: outro-uuid-seu" \
  -H "Content-Type: application/json" \
  -d '{
    "type": "TRANSFER",
    "origin_account_key": "bdc7f4af-b7f3-4b4a-90b1-6266f125e41d",
    "destination_account_key": "a1c9501a-bb40-4066-885b-e7b0669927c8",
    "amount": 10000
  }'
```

```json
{"transaction_key":"67838a37-dca1-4b8e-9fa5-4ed02446a49c","type":"TRANSFER","status":"COMPLETED","amount":10000,"fee_amount":200,"fee_policy_key":"0ac3c2ea-36f2-4e95-af14-b7c35e9fede7","origin_account_key":"bdc7f4af-b7f3-4b4a-90b1-6266f125e41d","destination_account_key":"a1c9501a-bb40-4066-885b-e7b0669927c8","created_at":"2026-10-09T12:56:57.294260+00:00"}
```

A tarifa de 200 centavos não foi recalculada: ela foi **copiada** da
política vigente no momento da operação, e a `fee_policy_key` registra
qual era. Mudar a tarifa amanhã não muda o que esta transação cobrou.

#### 5. Ler o saldo

```bash
curl http://localhost:3000/account/bdc7f4af-b7f3-4b4a-90b1-6266f125e41d \
  -H "INTERNAL-TOKEN: default_token" \
  -H "Authorization: Bearer <credencial da Ana>"
```

```json
{"account_key":"bdc7f4af-b7f3-4b4a-90b1-6266f125e41d","balance":89800,"status":"ACTIVE","status_events":[{"status":"ACTIVE","reason":null,"event_datetime":"2026-10-09T12:56:57.216033+00:00"}]}
```

`89800` centavos, os R$ 898 da conta da história: 100000 menos 10000 da
transferência, menos 200 da tarifa.

#### 6. O extrato, que prova o saldo

```bash
curl "http://localhost:3000/account/bdc7f4af-b7f3-4b4a-90b1-6266f125e41d/statement?limit=3" \
  -H "INTERNAL-TOKEN: default_token" \
  -H "Authorization: Bearer <credencial da Ana>"
```

```json
{"data":[{"entry_key":"be4dca62-552e-47d3-893b-783bab6f484f","amount":-200,"balance_after":89800,"sequence":3,"created_at":"..."},{"entry_key":"cb4fabe2-5b78-4f4f-873e-ae6f63ed58a8","amount":-10000,"balance_after":90000,"sequence":2,"created_at":"..."},{"entry_key":"5e294112-f451-4007-be73-47e226f5e188","amount":100000,"balance_after":100000,"sequence":1,"created_at":"..."}],"next_cursor":null,"is_last_page":true}
```

Cada linha traz o `balance_after`, o saldo **depois dela**. É isso que
permite ao extrato provar o saldo sozinho, sem confiar na coluna da
conta. A paginação é por **cursor opaco e assinado**, nunca por página
numerada: o livro recebe escrita o tempo todo, e com página numerada um
lançamento novo entre uma página e a seguinte faria um item aparecer
duas vezes.

#### 7. A conta do Bruno, com a credencial da Ana

```bash
curl http://localhost:3000/account/<conta-do-bruno> \
  -H "INTERNAL-TOKEN: default_token" \
  -H "Authorization: Bearer <credencial da Ana>"
```

```json
{"title":"Account not found","description":"Account with key ... was not found.","translation":"Conta não encontrada.","code":"QIT002010","request_id":"5f7688a6-b255-4cf7-a92d-086207c37e9c","errors":[]}
```

**`404`, e não `403`.** Um `403` confirmaria que aquela conta existe, e
é justamente isso que não se conta para quem não é o titular. É o item
número 1 do OWASP API Security Top 10.

#### 8. A conciliação, que prova o sistema inteiro

```bash
curl http://localhost:3000/internal/reconciliation \
  -H "INTERNAL-TOKEN: default_token"
```

```json
{"total":0,"entry_count":6}
```

A soma de **todos** os lançamentos de **todas** as contas tem de ser
zero. Se der qualquer outro número, algum centavo foi criado ou
destruído sem contrapartida. É o teste que prova tudo de uma vez.

Para desligar: `Ctrl+C` no terminal das APIs e depois

```bash
docker compose down
```

### Todas as rotas

O sistema são quatro serviços HTTP. Cada rota responde a quatro
perguntas: quem pode pedir, quanto tempo espera, o que acontece se
pedirem duas vezes, e como se descobre que falhou.

**API de conta e transação** (`src/`, porta 3000). É a única que altera
saldo:

| Método e rota | O que faz | Responde |
|---|---|---|
| `GET /` | diz qual serviço é este | `200` |
| `GET /health_check` | diz se a API está de pé | `204`, sem corpo |
| `POST /internal/account` | abre a conta do cliente | `201` nova, `200` a que já existia |
| `GET /account/{key}` | saldo e estado atual | `200`; `404 QIT002010` se não existe ou não é sua |
| `GET /account/{key}/statement` | extrato por cursor assinado | `200`; `400 QIT002015` cursor adulterado |
| `PATCH /account/{key}` | bloqueia, desbloqueia ou encerra. Só operador | `200`; `409 QIT002014` encerrar com saldo; `422 QIT002018` sair de `CLOSED` |
| `POST /transaction` | depósito e transferência com tarifa | `201`; `409 QIT002012` saldo insuficiente; `422 QIT002019` formato errado por tipo |
| `GET /transaction/{key}` | o comprovante | `200`; `404 QIT002010` |
| `POST /internal/posting` | **a única rota que move dinheiro** | `201`; `422 QIT002017` se os lançamentos não somam zero |
| `POST /internal/fee_policy` | fixa a tarifa vigente | `201` |
| `GET /internal/reconciliation` | soma tudo, tem de dar zero | `200` com `total` e `entry_count` |

**API de cliente** (`customer-api/`, porta 3010): cadastro de PF,
consulta e documento. Contrato na `RFC 01 - API de Cliente.md`.

**API de abertura de conta** (`onboarding-api/`, porta 3005): abertura em
etapas, retomável, com RG em bucket, KYC, fila de compliance e prazo de
20 minutos. Contrato em `docs/rfc/05-onboarding-api.md`.

**Webhooks de saída** (`webhook_api/`): a caixa de saída de eventos.
Contrato na `RFC 06 - API de Webhooks Outgoing.md`.

As rotas `/internal/...` são chamadas por outra API, nunca por um
cliente. Todas, menos `/` e `/health_check`, exigem o `INTERNAL-TOKEN`
(seção 6).


## 2. Rodando os testes

Os testes rodam **na sua máquina**, contra a API que está de pé no
Docker. Então são dois passos: um de uma vez só, outro toda vez.

**Uma vez só — instalar as dependências de teste:**

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements-dev.txt
```

O `.venv` é uma pasta com um Python só deste projeto. Ele existe pra que
instalar algo aqui não mexa no Python da sua máquina — e pra que apagar a
pasta desfaça tudo. No Windows, a segunda linha é
`.venv\Scripts\activate`.

**Toda vez — com a API de pé, em outro terminal:**

```bash
pytest
```

A API precisa estar respondendo antes. Se você acabou de dar
`docker compose up`, espere o `(healthy)` aparecer — é o healthcheck do
`docker-compose.yml` dizendo que a porta já atende. Sem isso, o primeiro
teste bate numa porta que ainda não responde.

O resultado sai assim:

```
tests/integration/test_healthcheck.py::TestHealthCheck::test_home PASSED
...
=================== 372 passed, 26 skipped in 602.63s (0:10:02) ===================
```

**Os 26 que pulam, e como rodar eles também.** Dois grupos de teste
precisam de uma porta de serviço que fica **desligada por padrão**, de
propósito: a injeção de falha, que faz a API quebrar num ponto exato
para provar que nada fica pela metade, e o relógio simulado, que faz o
prazo de 20 minutos vencer sem esperar 20 minutos. Nenhuma das duas pode
existir ligada num banco de verdade, então o padrão é `false` e os
testes que dependem delas se anunciam como pulados.

Para rodar a suíte inteira, ligue as duas na API e no `pytest`:

```bash
echo 'FAULT_INJECTION_ENABLED=true'  >> .env
echo 'SIMULATED_CLOCK_ENABLED=true'  >> .env
docker compose up -d --wait
set -a && . ./.env && set +a
pytest
```

Aí são **399 passando e nada pulado**, que é o que o CI roda a cada
push. Vale rodar assim antes de qualquer entrega.

Para rodar só um arquivo (ou só um teste), acrescente o caminho:

```bash
pytest -v tests/integration/test_healthcheck.py
```

Os testes leem o seu `.env` sozinhos (é o `tests/conftest.py` que faz
isso). Trocou a porta da API ali, os testes passam a bater na porta nova
— você não configura a mesma coisa em dois lugares.

Os testes conversam com a API **por HTTP**, exatamente como um cliente de
verdade faria. Eles não espiam o código por dentro: nenhum deles importa
nada de `src/`. Só sabem: "mandei isso, tem que voltar aquilo".

> Uma exceção, e ela é honesta: `tests/utils/db_utils.py` fala com o
> banco direto, por SQLAlchemy. Mas não para **montar** cenário — só
> para **zerar** o banco entre testes que não podem se atrapalhar. O
> cenário continua nascendo pela API, com `POST`.

Isso tem uma consequência bonita: **este projeto inteiro já foi reescrito
de um framework para outro, e nenhum teste precisou mudar.** Quando o
teste descreve o combinado em vez de descrever o código, ele sobrevive à
reforma.

## 3. Quando dá errado

Os tropeços mais comuns, com a mensagem que você vai ver:

### `port is already allocated`

```
Bind for 0.0.0.0:5432 failed: port is already allocated
```

Outro programa da sua máquina já usa aquela porta (é comum ter um
Postgres instalado ocupando a 5432). Não precisa descobrir qual: escolha
outras portas livres. É pra isto que serve o `.env` —

```bash
cp .env.example .env
```

— e, dentro dele, tire o `#` da frente destas duas linhas e troque os
números:

```
API_PORT=3001
DB_PORT=5433
```

Mexeu no `DB_PORT`? Então mude **também** a porta da `DATABASE_URL`, no
mesmo arquivo:

```
DATABASE_URL=postgresql+psycopg2://bootcamp:bootcamp@localhost:5433/bootcamp
```

São dois lugares porque são dois pontos de vista. O `DB_PORT` diz em
que porta **da sua máquina** o banco aparece; a `DATABASE_URL` é o
endereço que os testes usam para chegar nele de fora do Docker. A API
lá dentro não usa nenhuma das duas — para ela o banco é `db:5432`, e
por isso essa linha está fixa no `docker-compose.yml`.

Suba de novo. Agora a API atende em http://localhost:3001 — e nos
comandos `curl` da seção 1 você troca `3000` por `3001`.

### `failed to connect to the docker API`

```
failed to connect to the docker API at unix:///var/run/docker.sock;
check if the path is correct and if the daemon is running
```

O Docker não está ligado. Abra o **Docker Desktop** (Mac/Windows) e
espere ficar verde. No Linux: `sudo systemctl start docker`.

### `Não consegui falar com a API` / `Não consegui falar com o banco`

Só aparece no atalho local (fora do Docker). Quer dizer que a API ou o
banco não estão de pé, ou que a porta no seu `.env` não é a que eles
estão usando. Suba com `docker compose up` e confira as portas.

### `relation "..." does not exist`

```
psycopg2.errors.UndefinedTable: relation "minha_tabela" does not exist
```

Você mexeu no `database/database.sql`, e o banco não ficou sabendo.
Aquele arquivo roda **uma vez só: quando o banco nasce.** Depois disso o
Postgres nunca mais olha para ele — subir de novo com `docker compose
up` não adianta, e `docker compose restart db` também não.

Repare no que a mensagem faz com você: ela não diz "seu SQL não rodou",
diz que a tabela não existe. Você vai reler o seu SQL procurando um erro
de digitação que não está lá.

Para o banco nascer de novo, já com o schema novo:

```bash
docker compose down -v
docker compose up
```

O `-v` é o que apaga o volume — o disco do banco. **Ele leva junto tudo
que você tinha criado na mão**, as entidades dos `curl` da seção 1. Não
tem meio-termo: ou o banco nasce de novo com o schema novo, ou continua
com o antigo. (Em sistema de verdade é outra história — lá ninguém apaga
o banco, e a mudança de schema entra por um comando aplicado no deploy.)

### Nada disso resolveu?

Este comando desliga e limpa **este** projeto (containers, rede e o
banco com tudo dentro) para você recomeçar do zero:

```bash
docker compose down -v
docker compose up
```

Para ver o que a API está dizendo enquanto roda: `docker compose logs -f api`.

---

## 4. As pastas

```
src/
  app.py           ← liga tudo: rotas, middlewares e tratamento de erro
  database.py      ← onde a sessão de banco mora (quem cuida do ciclo
                     dela é middlewares/session_manager.py)
  constants.py     ← as configurações, lidas do ambiente

  resources/       ← recebe a requisição HTTP e devolve a resposta
                     (quem liga cada endereço a um resource é o app.py)
  schemas/         ← o formato do que entra: o JSON do corpo e os
                     parâmetros do endereço
  controllers/     ← as regras de negócio: o que pode e o que não pode
  repositories/    ← as conversas com o banco
  models/          ← as tabelas, descritas em Python
  dtos/            ← traduz o objeto do banco no JSON que sai
  errors/          ← os erros da API, cada um com seu código
  middlewares/     ← o que acontece com TODA requisição
  connectors/      ← as conversas com outros serviços
  utils/           ← as ferramentas que não são de nenhuma camada

database/
  database.sql     ← as tabelas, em SQL puro

tests/             ← os testes
```

### Por que tanta pasta?

Porque cada uma tem **um trabalho só**, e só conversa com a vizinha:

```
requisição → resource → controller → repository → banco
                 ↑           ↑
             valida o     decide o
              formato     que pode
```

O resource não sabe SQL. O repository não sabe o que é uma regra de
negócio. Um teste rápido para saber se uma linha está na pasta certa:
**nenhum `raise` mora em `resources/`** — quem recusa é o schema, antes,
ou o controller, depois. Confira você mesmo:

```bash
grep -rn "raise" src/resources/
```

Não volta nada, e isso é de propósito. Quando você precisa trocar o banco, mexe numa pasta. Quando a
regra muda, mexe na outra. É isso que permite um time inteiro trabalhar
no mesmo projeto sem pisar no pé um do outro.

---

## 5. Configuração e senhas

Toda configuração entra por **variável de ambiente** — nunca escrita no
meio do código.

- **valor padrão** → escrito no `docker-compose.yml`, na forma
  `${VARIAVEL:-padrao}`. É por causa dele que o `docker compose up`
  funciona sem preparo nenhum.
- `.env` → **opcional**, fica só na sua máquina e **nunca** vai para o
  Git. Serve para sobrescrever um padrão (porta ocupada, outro token).
- `.env.example` → vai para o Git, e é a cópia de onde você parte. Só
  tem valor de mentirinha.

Essa separação não é frescura. Senha commitada em repositório é uma das
formas mais comuns de vazamento de dados no mundo real, e não tem
desfazer: uma vez no histórico, está lá para sempre.

Uma ressalva honesta: valor padrão de senha em arquivo versionado só
vale porque aqui é um projeto de estudo, sem dado de ninguém. Em
sistema de verdade, segredo não tem padrão — ele falta, e a aplicação
se recusa a subir sem ele.

## 6. Autenticação

As rotas de negócio pedem um cabeçalho:

```
INTERNAL-TOKEN: default_token
```

Sem ele, a API responde **403**. `default_token` é o valor padrão; para
trocar, ponha `INTERNAL_TOKEN=outra_coisa` no seu `.env`.

Ficam abertas, de propósito, só duas: a rota raiz e o `/health_check`
porque quem consulta a segunda é o próprio Docker, que não tem como
mandar cabeçalho.

**Só isso não basta num banco, e o motivo cabe numa frase:** o
`INTERNAL-TOKEN` diz **que aplicação** está falando, não **quem**. Com
ele sozinho, qualquer um que o tenha leria o saldo de qualquer conta. Por
isso as rotas de cliente pedem uma segunda coisa:

```
Authorization: Bearer <credencial>
```

A credencial é um JWT assinado em HMAC-SHA256 com a `AUTH_SECRET`, com o
`sub` igual à `customer_key` de quem pede. Quem a emite é a
onboarding-api, no fim da abertura de conta. **Cada API confere sozinha**,
sem chamar ninguém e sem ir ao banco: a assinatura já prova que a
credencial saiu de dentro do ecossistema.

| Camada | Cabeçalho | A pergunta que responde |
|---|---|---|
| aplicação | `INTERNAL-TOKEN` | é um cliente nosso que está chamando? |
| identidade | `Authorization: Bearer` | **quem** está chamando? |
| serviço | só o `INTERNAL-TOKEN`, nas `/internal/...` | quem chama é outra API, não um cliente |

Dois escopos: `onboarding`, que é o cliente e vê só a própria conta, e
`operator`, que lê qualquer conta e é o único que pode pedir um depósito.
Conta que não é sua responde **`404`, não `403`**, para não confirmar que
ela existe.

> Os valores padrão (`default_token`, e a `AUTH_SECRET` do
> `.env.example`) são **só para estudo**. Num ambiente de verdade eles
> vêm do ambiente, nunca do repositório.

---

## 7. Os códigos de erro

Todo erro da API responde no mesmo formato, com um código próprio:

```json
{
  "title": "Bad Request",
  "description": "'hello' is a required property",
  "translation": "Payload Inválido",
  "code": "QIT000001"
}
```

| Código      | Quando acontece                                  |
|-------------|--------------------------------------------------|
| `QIT000001` | o JSON enviado está fora do formato              |
| `QIT000002` | faltou o `INTERNAL-TOKEN`, ou ele está errado    |
| `QIT000003` | faltou a credencial no `Authorization`           |
| `QIT000004` | a credencial está malformada ou a assinatura não confere |
| `QIT000005` | a credencial venceu                              |
| `QIT000006` | a operação exige escopo de operador              |
| `QIT000010` | os parâmetros do endereço se contradizem         |
| `QIT000404` | essa rota não existe                             |
| `QIT000405` | a rota existe, mas não aceita esse método        |
| `QIT000500` | erro inesperado (o time é avisado)               |

Um código estável vale mais que uma mensagem bonita: quem integra com a
API programa em cima do código, não do texto.

Os números não são sorteados. Eles vêm em faixas, uma por domínio:

- **`QIT000…`** os erros que **toda** API tem: JSON fora do schema, sem
  token, credencial ausente ou vencida, rota inexistente. Estão em
  `src/errors/base_error.py`.
- **`QIT001…`** faixa **reservada**. Era a da `sample_entity`, a
  entidade de exemplo do projeto base, que saiu antes da entrega junto
  com o código dela. Os números ficam vazios para não mudarem de
  significado no meio do caminho.
- **`QIT002…`** conta, livro, transação e tarifa. Estão em
  `src/errors/account_errors.py` e `src/errors/custom_errors.py`, e o
  catálogo completo, com o que cada um significa, está na
  `docs/rfc/02-conta.md`.
- **`ONB…`** a onboarding-api tem a própria convenção, documentada na
  `docs/rfc/05-onboarding-api.md`.

Não repita um número. Se repetir, a API **não sobe** — tem uma checagem
no start (`error_verification`, em `src/errors/base_error.py`) que
procura código repetido e derruba a aplicação de propósito. Parecer
chato agora é melhor que dois erros diferentes chegarem ao cliente com o
mesmo código.

---

## 8. A licença

Este projeto é **MIT** — pode usar, copiar, modificar e levar para o seu
portfólio, inclusive em trabalho pago. O único pedido é manter o arquivo
`LICENSE` junto quando você distribuir o código.
