# Como rodar os testes

## O que "black box" quer dizer aqui

O teste não abre o código da API nem o banco. Ele só manda pedidos HTTP para a API que está rodando no Docker e confere a resposta: o status, o corpo e os cabeçalhos. É o que faria um aplicativo de verdade.

Por isso são sempre dois passos, nesta ordem:

1. **Subir as APIs no Docker** (`docker compose up`).
2. **Rodar o pytest na sua máquina**, fora do Docker, apontando para elas.

Se a API não estiver de pé, nenhum teste roda.

## Uma vez só: preparar a máquina

| O quê | Como conferir | Se faltar |
|---|---|---|
| Docker Desktop | Abra o programa. No canto de baixo aparece "Engine running" | Instale pelo site do Docker |
| Python 3.11 | `py -3.11 --version` mostra `Python 3.11.x` | Instale o 3.11. O 3.13 ou mais novo quebra o SQLAlchemy da base |
| Ambiente virtual com as dependências | Existe a pasta `.venv` dentro de `banco-digital` | `py -3.11 -m venv .venv` e depois `.venv/Scripts/python -m pip install -r requirements-dev.txt` |
| Arquivo `.env` | Existe `banco-digital/.env` com `SERVER_LOCALHOST=127.0.0.1` | Crie com essa linha. O Windows não conecta em `0.0.0.0`, que é o padrão |

Quando o `requirements-dev.txt` mudar, rode o `pip install` de novo.

## Toda vez

**1. Abra o Docker Desktop** e espere aparecer "Engine running".

**2. Abra um terminal na pasta do projeto.** As aspas são necessárias por causa do espaço em `QI tech`. No `cmd`, use `cd /d`, que também troca de disco se precisar:

```bash
cd "C:\Users\carlo\Documents\ChatGPT\QI tech\banco-digital"
```

No `cmd`:

```bat
cd /d "C:\Users\carlo\Documents\ChatGPT\QI tech\banco-digital"
```

**3. Suba tudo:**

```bash
docker compose up -d --build --wait
```

- `-d`: roda em segundo plano e devolve o terminal.
- `--build`: monta as imagens com o código atual.
- `--wait`: só termina quando todos os serviços estão saudáveis.

Na primeira vez demora alguns minutos, porque baixa as imagens (só a do LocalStack tem uns 460 MB) e instala as dependências. Depois fica rápido.

Para conferir, rode `docker compose ps`. Os serviços precisam aparecer como `healthy`, menos o `onboarding-worker` (duas réplicas) e o `mockserver`, que não têm checagem de saúde e aparecem só como `Up`:

| Serviço | O que é | Porta na sua máquina |
|---|---|---|
| `onboarding-api` | A API de criação de conta | 3005 |
| `db` | PostgreSQL, com o banco único do grupo (`bootcamp`) | 5432 |
| `redis` | Contadores dos limites de pedidos | nenhuma |
| `localstack` | O S3 de mentira, com o bucket privado `rg-documentos` das fotos do RG. Só fica `healthy` depois que o bucket existe | nenhuma |
| `onboarding-worker` | O mesmo código da onboarding-api, em outro processo, em duas réplicas. A cada segundo, analisa o KYC das aberturas com o RG completo e pede a conta das aprovadas. A cada minuto, vence as aberturas paradas há mais de 20 minutos e apaga as fotos e os dados pessoais delas | nenhuma |
| `mockserver` | Faz o papel da Receita, das listas de sanções e de PEP e da account-api. Cada teste programa a resposta para o documento dele | 1080 |
| `api` | A API da raiz do repositório (pasta `src/`) | 3000 |

**4. Rode os testes da onboarding-api:**

```bash
.venv/Scripts/python -m pytest tests/onboarding_api -v
```

O `.venv/Scripts/python` usa o Python do ambiente virtual, sem precisar ativá-lo.

**No `cmd` (Prompt de Comando), a barra é invertida.** O `cmd` lê `/` como o começo de uma opção, e com `/` responde "'.venv' não é reconhecido como um comando interno". No `cmd`, o mesmo comando fica assim:

```bat
.venv\Scripts\python -m pytest tests\onboarding_api -v
```

| Terminal | Como escrever o começo do comando |
|---|---|
| `cmd` (Prompt de Comando) | `.venv\Scripts\python -m pytest ...` |
| PowerShell | `.venv\Scripts\python` ou `.venv/Scripts/python`, os dois funcionam |
| Git Bash | `.venv/Scripts/python -m pytest ...` |

Os comandos das próximas seções usam `/`. No `cmd`, troque por `\`.

## Como ler o resultado

```
tests/onboarding_api/test_service.py::TestService::test_home_says_which_service PASSED [ 25%]
tests/onboarding_api/test_service.py::TestService::test_requires_internal_token PASSED [ 75%]
...
============================== 97 passed in 7.03s ==============================
```

- **Cada linha é um teste.** O nome diz qual comportamento ele garante. A primeira linha do teste, no código, diz o ID dele no plano (por exemplo, `F1-22`), e o plano diz qual regra da RFC ele protege.
- **`PASSED`:** a API fez o que a RFC manda.
- **`FAILED`:** a API respondeu diferente. O pytest mostra a linha com `E`, por exemplo `E  assert 409 == 201`. Lê-se assim: a API respondeu `409`, e o teste esperava `201`.
- **`SKIPPED`:** o teste foi pulado de propósito, e o motivo aparece com `-rs`. O caso mais comum é o teste de falha simulada, explicado abaixo.
- **A última linha** é o resumo: quantos passaram, falharam e foram pulados.

## Rodar só uma parte

| Para rodar | Comando |
|---|---|
| Tudo, como o CI e a banca | `.venv/Scripts/python -m pytest -v` |
| Só a onboarding-api | `.venv/Scripts/python -m pytest tests/onboarding_api -v` |
| Só uma fatia (um arquivo) | `.venv/Scripts/python -m pytest tests/onboarding_api/test_post_onboarding.py -v` |
| Só um grupo (uma classe) | `.venv/Scripts/python -m pytest "tests/onboarding_api/test_post_onboarding.py::TestPostOnboardingIdempotency" -v` |
| Só um teste | `.venv/Scripts/python -m pytest "tests/onboarding_api/test_service.py::TestService::test_requires_internal_token" -v` |
| Por palavra no nome | `.venv/Scripts/python -m pytest tests/onboarding_api -k idempotency -v` |
| Pular os testes lentos, que esperam o worker (até 90 s cada) | acrescente `-m "not slow"` |
| Parar no primeiro erro | acrescente `-x` |
| Só os que falharam na última vez | acrescente `--lf` |
| Ver o motivo dos pulados | acrescente `-rs` |
| Saída curta, um ponto por teste | troque `-v` por `-q` |

## Testes com falha simulada

Alguns testes fingem que algo caiu: hoje, o F2-06, com o Redis fora do ar, e o F4-17, com o bucket do RG fora do ar. Eles só rodam com `FAULT_INJECTION_ENABLED=true` **nos dois lados**: na API, para ela obedecer ao cabeçalho `X-Fault-Injection`, e no pytest, para o teste não ser pulado. É assim que o CI roda.

Os testes do prazo de 20 minutos (F5) seguem a mesma ideia, com `SIMULATED_CLOCK_ENABLED=true`: com ela, o teste manda `X-Simulated-Now` e o pedido acontece "no passado", sem esperar 20 minutos de verdade. Ligue as duas juntas.

No `cmd`, sem aspas e sem espaço em volta do `=`:

```bat
set FAULT_INJECTION_ENABLED=true
set SIMULATED_CLOCK_ENABLED=true
docker compose up -d --wait
.venv\Scripts\python -m pytest tests\onboarding_api -v
```

No PowerShell:

```powershell
$env:FAULT_INJECTION_ENABLED = "true"
$env:SIMULATED_CLOCK_ENABLED = "true"
docker compose up -d --wait
.venv/Scripts/python -m pytest tests/onboarding_api -v
```

No Git Bash:

```bash
export FAULT_INJECTION_ENABLED=true
export SIMULATED_CLOCK_ENABLED=true
docker compose up -d --wait
.venv/Scripts/python -m pytest tests/onboarding_api -v
```

O `docker compose up` percebe que a variável mudou e recria a onboarding-api sozinho. Por isso, **todo** `docker compose up` precisa das variáveis no mesmo terminal: um `up` sem elas recria a API com as falsificações desligadas, e os testes delas falham. Para voltar ao normal, feche o terminal (ou rode `set FAULT_INJECTION_ENABLED=` no `cmd`, `Remove-Item Env:FAULT_INJECTION_ENABLED` no PowerShell ou `unset FAULT_INJECTION_ENABLED` no Git Bash, e o mesmo para `SIMULATED_CLOCK_ENABLED`) e suba de novo.

Atenção: com o worker de pé, toda abertura de teste que ficou parada em `DRAFT` por mais de 20 minutos é vencida e tem o cadastro apagado. E toda abertura com o RG completo é analisada: se o Mockserver foi recriado e perdeu as respostas programadas, ela fica em `ANALYSIS` e volta para a fila a cada minuto, até a F7 trazer as novas tentativas espaçadas. Isso vale também para as aberturas que as outras suítes deixam no banco local, e é o comportamento esperado da RFC 05.

## Mudei o código: preciso subir de novo?

| O que mudou | O que fazer |
|---|---|
| Só os testes (`tests/`) | Nada. Rode o pytest de novo |
| Código Python da API (`onboarding-api/src/`) | Em geral a API e o worker recarregam sozinhos. Se o teste não enxergar a mudança: `docker compose restart onboarding-api onboarding-worker` |
| `onboarding-api/requirements.txt` | `docker compose up -d --build --wait` |
| `database/database.sql` (tabelas) | `docker compose down -v` e depois `docker compose up -d --build --wait`. O SQL só roda num banco vazio, e o `-v` apaga os dados de teste |

## Ver o que a API fez

O log mostra cada pedido que entrou e saiu, com o status e o tempo:

```bash
docker compose logs onboarding-api --tail 50
```

Todo erro devolve um `request_id`, e ele aparece em cada linha de log daquele pedido. Para achar um pedido específico, filtre pelo `request_id`:

```bash
docker compose logs onboarding-api | grep 8f3c1e42
```

No PowerShell, troque `grep` por `Select-String`; no `cmd`, por `findstr`.

## Desligar

| Comando | O que faz |
|---|---|
| `docker compose down` | Para tudo e mantém os dados |
| `docker compose down -v` | Para tudo e apaga os dados. Na próxima subida, o banco nasce vazio |

## Problemas comuns

| O que aparece | O que é | Como resolver |
|---|---|---|
| `'.venv' não é reconhecido como um comando interno` | Você está no `cmd`, e ele não aceita `/` no caminho do programa | Use barra invertida: `.venv\Scripts\python -m pytest tests\onboarding_api -v` |
| `Nao consegui falar com a onboarding-api em http://127.0.0.1:3005` | A API não está de pé | Rode `docker compose ps`. Se não estiver `healthy`, veja `docker compose logs onboarding-api` |
| `port is already allocated` ao subir | Outro programa usa a porta 3000, 3005 ou 5432, em geral a `bootcamp-base-api` ou a biblioteca | Pare o outro projeto (`docker compose down` na pasta dele) ou troque a porta no `.env` (`API_PORT`, `ONBOARDING_API_PORT`, `DB_PORT`) |
| `failed to connect to the docker API` | O Docker Desktop está fechado | Abra o programa e espere o "Engine running" |
| `No module named jwt` ou `No module named pytest` | Faltam dependências no `.venv` | `.venv/Scripts/python -m pip install -r requirements-dev.txt` |
| Os testes não acham a API, mas ela está de pé | Falta o `.env` com `SERVER_LOCALHOST=127.0.0.1` | Crie o arquivo com essa linha |
| `SKIPPED ... FAULT_INJECTION_ENABLED=true` | Teste de falha simulada pulado de propósito | Normal. Para rodar, veja a seção de falha simulada |
| O `localstack` não sobe e o log pede `LOCALSTACK_AUTH_TOKEN` | Alguém trocou a imagem por uma versão de 2026.03 em diante, que exige conta no LocalStack | Volte para `localstack/localstack:4.14.0` no `docker-compose.yml`, a última que sobe sem conta |
| `FAILED test_bucket_fora_responde_503...` com `assert 202 == 503` | O pytest está com `FAULT_INJECTION_ENABLED=true`, mas a API subiu sem | Suba de novo com a variável ligada no mesmo terminal |
| `FAILED test_envio_depois_do_prazo_responde_410` com `assert 202 == 410` | O pytest está com `SIMULATED_CLOCK_ENABLED=true`, mas a API subiu sem | Suba de novo com a variável ligada no mesmo terminal |
| `AssertionError: Passaram 90 s e a condicao nao valeu` num teste da F5 | O worker não está de pé, ou parou com erro | `docker compose ps` e `docker compose logs onboarding-worker --tail 30` |
| `AssertionError: Passaram 20.0 s ... 'status': 'PENDING_KYC'` ou `'ANALYSIS'` num teste da F6 | O worker não analisou: está fora do ar, ou um birô não respondeu como o teste programou | `docker compose logs onboarding-worker --tail 30`; procure `Biro respondeu` ou `Biro sem resposta` |
| `Nao consegui falar com o Mockserver em http://127.0.0.1:1080` | O Mockserver não subiu, ou a porta 1080 está ocupada | `docker compose ps`; para trocar a porta, `MOCKSERVER_PORT` no `.env` e `MOCKSERVER_URL` no pytest |
