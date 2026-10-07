# Bootcamp QI Tech — projeto base da API

Projeto base do Bootcamp: uma API REST em **Python + FastAPI**, com banco
**PostgreSQL**, rodando em **Docker**.

Você não precisa saber programar para começar. A API e o banco sobem
no **Docker**, então você não instala nem um nem outro na sua máquina.
Os **testes** rodam no seu Python — são dois comandos, e a seção 2
mostra os dois.

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

São duas coisas de pé, e vale saber o nome de cada uma:

| Serviço | O que é |
|---|---|
| `api` | a API que responde às suas requisições |
| `db` | o banco de dados (PostgreSQL) |

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

### Agora as outras rotas

Elas não abrem no navegador, porque exigem um cabeçalho: o
`INTERNAL-TOKEN`, que é a senha da API (seção 6). Para mandar um
cabeçalho a gente usa o `curl`, um programa de linha de comando que já
vem instalado no Mac, no Linux e no Windows.

**Abra um segundo terminal** — o primeiro está ocupado rodando a API — e
cole um comando de cada vez.

> **No Windows**, use o **Git Bash**: ele veio junto com o Git da seção
> 0. No PowerShell estes comandos não funcionam, porque lá `curl` é o
> apelido de outro programa, com outra sintaxe.

#### 1. Criar uma entidade

```bash
curl -X POST http://localhost:3000/sample_entity \
  -H "INTERNAL-TOKEN: default_token" \
  -H "Content-Type: application/json" \
  -d '{
    "hello": "world",
    "name": "Maria da Silva",
    "email": "maria.silva@exemplo.com.br",
    "document_number": "529.982.247-25",
    "birthdate": "1990-05-17"
  }'
```

```json
{"sample_entity_key":"3fbf83e9-e5fc-4e0f-8427-db6a1a50f964"}
```

Esse `sample_entity_key` é o endereço da entidade que você acabou de
criar. **Copie o seu** — ele nasce diferente a cada vez, e nos comandos
abaixo você troca o que está escrito aqui pelo seu.

> **Rodou o comando duas vezes e levou 409 na segunda?** É de propósito:
> o CPF e o e-mail não podem se repetir. Para criar uma segunda
> entidade, troque o e-mail (qualquer um serve) e o CPF — mas o CPF tem
> que ser **válido de verdade**, com os dois dígitos finais batendo com
> a conta. O `529.982.247-25` acima é um CPF de teste conhecido, que
> passa na conta e não pertence a ninguém.
>
> **E os cinco campos são todos obrigatórios?** São. Mande `{}` e a API
> diz qual está faltando — é o comando 6 lá embaixo.

#### 2. Buscar a entidade

```bash
curl http://localhost:3000/sample_entity/3fbf83e9-e5fc-4e0f-8427-db6a1a50f964 \
  -H "INTERNAL-TOKEN: default_token"
```

```json
{"hello":"world","sample_entity_key":"3fbf83e9-e5fc-4e0f-8427-db6a1a50f964","name":"Maria da Silva","email":"maria.silva@exemplo.com.br","document_number":"529.982.247-25","birthdate":"1990-05-17","status":"pending","counter":0,"status_events":[{"status":"pending","event_datetime":"2026-09-11T20:36:43.104210"}]}
```

Você mandou cinco campos e voltaram nove. Os quatro extras a API montou
sozinha:

- **`sample_entity_key`** — o endereço da entidade;
- **`status`** — o estado inicial, `pending`;
- **`counter`** — um contador zerado;
- **`status_events`** — a **história**. Cada vez que o status muda, uma
  linha nova entra aqui, com a hora. Saber onde a entidade está é uma
  coisa; saber por onde ela passou é outra, e é essa lista que responde
  a segunda.

#### 3. Listar as entidades

```bash
curl http://localhost:3000/sample_entities \
  -H "INTERNAL-TOKEN: default_token"
```

```json
{"data":[{"hello":"world","sample_entity_key":"3fbf83e9-e5fc-4e0f-8427-db6a1a50f964","name":"Maria da Silva","email":"maria.silva@exemplo.com.br","document_number":"529.982.247-25","birthdate":"1990-05-17","status":"pending","counter":0}],"limit":10,"page":0,"is_last_page":true}
```

Vêm de dez em dez, da mais nova para a mais antiga. Para pedir outra
quantidade ou outra página, acrescente `?limit=2&page=0` ao endereço —
o `limit` vai até **100**. O `is_last_page` já responde a pergunta
seguinte — "tem mais?" — sem custar uma segunda requisição.

Repare no que **não** veio: o `status_events`. Na lista cada item vem
resumido, porque montar a história de cada entidade custa uma consulta a
mais por item — numa página de 100, são 100 consultas para uma
informação que quem está varrendo não pediu. A história aparece quando
você abre UMA entidade, no comando 2.

Também dá para **filtrar**. Todos os filtros se combinam, e todos são
opcionais:

```bash
curl "http://localhost:3000/sample_entities?name=maria&status=pending&status=failed" \
  -H "INTERNAL-TOKEN: default_token"
```

| Filtro | Como casa |
|---|---|
| `name` | por **pedaço**, ignorando maiúscula/minúscula |
| `email` | exato |
| `document_number` | exato |
| `birthdate_from` / `birthdate_to` | intervalo, **incluindo** as duas pontas |
| `status` | pode repetir: `?status=pending&status=failed` traz os dois |

Repare que `status` se comporta ao contrário dos outros: `name` junto
com `email` **estreita** a busca (os dois precisam bater), mas dois
`status` **alargam** (basta um bater). Faz sentido pelo que a pessoa
quer dizer — "me mostra o que deu errado e o que deu certo" é um pedido
legítimo, e uma entidade só pode estar num dos baldes.

#### 4. Somar 1 no contador

```bash
curl -i -X PUT http://localhost:3000/webhook/sample_entity/3fbf83e9-e5fc-4e0f-8427-db6a1a50f964/increment_counter \
  -H "INTERNAL-TOKEN: default_token"
```

```
HTTP/1.1 204 No Content
```

Esta rota não responde nada — por isso o `-i`, que manda o `curl`
mostrar também o **status** da resposta. `204` quer dizer "deu certo e
não tenho nada a dizer". Repita o comando 2: o `counter` agora é `1`.

#### 5. Mudar o status

```bash
curl -X PUT http://localhost:3000/sample_entity/3fbf83e9-e5fc-4e0f-8427-db6a1a50f964 \
  -H "INTERNAL-TOKEN: default_token" \
  -H "Content-Type: application/json" \
  -d '{"status": "success"}'
```

```json
{"sample_entity_key":"3fbf83e9-e5fc-4e0f-8427-db6a1a50f964"}
```

Repita o comando 2: o `status` virou `success`. E rode este comando 5
mais uma vez — agora a API recusa:

```json
{"title":"Entity cannot change status","description":"Entity with status success cannot update to success.","translation":"Essa entidade não pode ser atualizada.","code":"QIT001002"}
```

Isso é uma **regra de negócio**, não um erro de digitação: entidade que
já terminou não volta atrás. A frase que decide isso mora em
`src/controllers/sample_entity_controller.py`, e você pode ir ler.

#### 6. Mandar um JSON torto

```bash
curl -X POST http://localhost:3000/sample_entity \
  -H "INTERNAL-TOKEN: default_token" \
  -H "Content-Type: application/json" \
  -d '{}'
```

```json
{"title":"Bad Request","description":"'hello' is a required property","translation":"Payload Inválido","code":"QIT000001"}
```

**400**, e nada foi criado. O `hello` é obrigatório, e quem recusou não
foi a regra de negócio: foi o `src/schemas/`, antes da primeira linha da
rota rodar. Pedido torto não chega a custar uma consulta ao banco.

Repare que ele reclamou de **um** campo, e você deixou cinco de fora. É
assim mesmo: a validação para no primeiro problema. Tire o `{}` e vá
preenchendo um campo de cada vez para ver a reclamação andar.

E existe uma fronteira aqui que vale a pena enxergar cedo. Mande um CPF
com o formato certo e os dígitos errados:

```bash
curl -X POST http://localhost:3000/sample_entity \
  -H "INTERNAL-TOKEN: default_token" \
  -H "Content-Type: application/json" \
  -d '{
    "hello": "world",
    "name": "Maria da Silva",
    "email": "outra@exemplo.com.br",
    "document_number": "111.111.111-11",
    "birthdate": "1990-05-17"
  }'
```

```json
{"title":"Invalid Document Number","description":"The document number 111.111.111-11 is not a valid CPF.","translation":"O CPF informado não é válido.","code":"QIT001003"}
```

Agora é **422**, não 400. A diferença não é capricho: 400 quer dizer
"não consegui ler o seu pedido"; 422 quer dizer "li, entendi, e esse
valor não pode existir". O schema sabe contar pontos e traços — ele não
sabe fazer a conta dos dois últimos dígitos. Quem sabe é o
`src/utils/document_number.py`, e por isso essa recusa vem de dentro,
com código próprio.

#### Esqueceu o `-H "INTERNAL-TOKEN: ..."`?

A API responde **403** e nem chega a olhar o resto:

```json
{"title":"Forbidden","description":"Request must be internal","translation":"Requisição precisa ser interna","code":"QIT000002"}
```

#### Toda resposta vem com um número de protocolo

Repare no `-i` deste comando: ele mostra os **cabeçalhos** da resposta,
não só o corpo.

```bash
curl -i "http://localhost:3000/sample_entities?limit=1" \
  -H "INTERNAL-TOKEN: default_token"
```

```
HTTP/1.1 200 OK
content-type: application/json
x-request-id: 8f3c1e42-1b0d-4f77-9a55-2e4c9d1f0abc
...
```

Esse `x-request-id` é o **número de protocolo** da sua requisição: um
nome único, criado no instante em que ela chegou. Copie o seu e procure
por ele no log:

```bash
docker compose logs api | grep 8f3c1e42
```

```
[INFO] bootcamp-api.middlewares.request_logger [8f3c1e42-...] - ENTROU GET /sample_entities?limit=1
[INFO] bootcamp-api.middlewares.request_logger [8f3c1e42-...] - SAIU 200 GET /sample_entities - 2.9 ms
```

Duas linhas, o mesmo nome nas duas — e nenhuma outra requisição usa esse
nome. Serve para o dia em que alguém disser "deu erro por volta das
14h30": sem o número, você abre o log e encontra mil linhas parecidas, de
mil requisições diferentes, embaralhadas, porque a API atende várias ao
mesmo tempo e o log é um só. Com o número, achar a agulha é um `grep`.

Se quem chamou já mandar um `x-request-id`, a API **respeita o que veio**
e usa o mesmo — é assim que se segue um único pedido atravessando vários
sistemas:

```bash
curl -i "http://localhost:3000/sample_entities?limit=1" \
  -H "INTERNAL-TOKEN: default_token" \
  -H "X-Request-ID: meu-teste-1"
```

Experimente mandar um valor esquisito nesse cabeçalho — com espaços, ou
bem comprido. A API não devolve o que você mandou: ela troca por um novo.
O porquê está em `src/utils/request_context.py`, e é uma das poucas
lições de segurança que cabem em cinco linhas.

> Só o `/` e o `/health_check` não aparecem no log: o Docker consulta o
> health check a cada três segundos, e sem essa exceção o log seria
> quase só isso. Eles ganham o `x-request-id` como todo mundo — o que
> não ganham é a linha de log.

### Todas as rotas

Sete endereços — este é o mapa inteiro da API:

| Método e rota | O que faz | Responde |
|---|---|---|
| `GET /` | diz qual serviço é este | `200` + nome e id |
| `GET /health_check` | diz se a API está de pé | `204`, sem corpo |
| `POST /sample_entity` | cria uma entidade | `201` + o `sample_entity_key` |
| `GET /sample_entity/{key}` | busca uma entidade | `200` + a entidade |
| `GET /sample_entities` | lista, de dez em dez, com filtros | `200` + a página |
| `PUT /sample_entity/{key}` | muda o status (`success` ou `failed`) | `202` + o `sample_entity_key` |
| `PUT /webhook/sample_entity/{key}/increment_counter` | soma 1 no contador | `204`, sem corpo |

As cinco de baixo exigem o `INTERNAL-TOKEN` (seção 6). As duas de cima
são abertas — a primeira você já usou: foi ela que respondeu no
navegador.

Os parâmetros da listagem, todos opcionais e combináveis:
`?limit=` (padrão 10, teto 100) · `?page=` (padrão 0) · `?status=`
(repetível) · `?name=` · `?email=` · `?document_number=` ·
`?birthdate_from=` · `?birthdate_to=`. Qualquer outro nome a API
**recusa** com 400 — é o `src/schemas/get_sample_entities.json` que
decide, e ele não aceita o que não conhece. Vale a pena errar de
propósito uma vez:

```bash
curl "http://localhost:3000/sample_entities?stauts=pending" \
  -H "INTERNAL-TOKEN: default_token"
```

Sem essa recusa, um `stauts` com a letra trocada viraria uma lista
inteira devolvida como se o filtro tivesse funcionado — o pior tipo de
bug, o que não reclama.

Para desligar tudo: `Ctrl+C` no terminal da API e depois

```bash
docker compose down
```

---

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
============================== 35 passed in 1.54s ==============================
```

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
— esta última porque quem a consulta é o próprio Docker, que não tem
como mandar cabeçalho.

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
| `QIT000010` | os parâmetros do endereço se contradizem         |
| `QIT000404` | essa rota não existe                             |
| `QIT000405` | a rota existe, mas não aceita esse método        |
| `QIT000500` | erro inesperado (o time é avisado)               |
| `QIT001001` | a entidade procurada não existe                  |
| `QIT001002` | a entidade já está num status final              |
| `QIT001003` | o CPF tem o formato certo, mas não é um CPF      |
| `QIT001004` | já existe um cadastro com esse CPF               |
| `QIT001005` | já existe um cadastro com esse e-mail            |
| `QIT001006` | a pessoa é menor de idade                        |
| `QIT001007` | a data de nascimento não existe no calendário    |

Um código estável vale mais que uma mensagem bonita: quem integra com a
API programa em cima do código, não do texto.

Os números não são sorteados. Eles vêm em duas faixas:

- **`QIT000…`** — os erros que **toda** API tem: JSON errado, sem token,
  rota inexistente. Estão em `src/errors/base_error.py` e você não
  precisa mexer neles.
- **`QIT001…`** — os erros das **regras deste projeto**. Estão em
  `src/errors/custom_errors.py`, e é aí que os seus entram: o próximo
  livre é o `QIT001008`.

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
