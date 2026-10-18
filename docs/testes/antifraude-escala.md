# Escala da antifraud-api

A pergunta do tech lead, em 18/10: **o banco vira problema quando lota de dados, e atrasa a análise?** Este documento responde com medição, não com opinião. A ferramenta é `tools/escala_antifraude.py`, e cada número abaixo saiu dela.

## Como medir

```bash
docker compose -f docker-compose.yml -f tools/escala/compose.escala.yml up -d --build --wait db antifraud-api
```

```bash
python tools/escala_antifraude.py --tamanhos 0,100000,1000000,3000000 --pesados 1000,5000,10000
```

A sobreposição `tools/escala/compose.escala.yml` liga o `pg_stat_statements` no Postgres. Com ele, o relatório separa o tempo gasto **no banco** do tempo total, e lista as consultas que mais pesaram. O relatório sai na tela e em `tools/resultados/` (fora do Git).

**O banco é enchido por SQL e a medição é por HTTP.** Encher pela API custaria uns 60 ms por Pix: 3 milhões levariam dois dias. As linhas semeadas têm `pix_id` começando por `escala-` e carregam o `metadata` de um Pix de verdade, para ocupar o mesmo espaço em disco. Por escrever direto no banco, a ferramenta se recusa a rodar contra um Postgres que não seja local. As tabelas são append-only: para limpar, `docker compose down -v`.

**Quatro perguntas, quatro seções do relatório:**

1. **Volume total.** Com 1 mil, 100 mil, 1 milhão e 3 milhões de Pix no banco, o Pix de um cliente comum demora mais?
2. **Entidade pesada.** E se o volume estiver concentrado num pagador, numa loja que recebe de muita gente, num IP de operadora ou numa rede /24 que não está na tabela de faixas?
3. **Concorrência.** Quantos Pix por segundo a API aguenta com 1, 4, 8 e 16 chamadores?
4. **Disco.** Quanto cada Pix grava.

`--secoes` escolhe as medições (`volume,pagador,loja,ip,rede,concorrencia`), e `--tamanhos 0` mede contra o banco como ele está, sem encher.

O teste `tests/antifraud_api/test_escala.py` guarda o achado principal no CI. Ele só roda com `RUN_ESCALA=true`, porque monta 800 recebimentos pela API, o que leva perto de um minuto. O workflow curto do antifraude liga essa chave.

## O que a medição mostrou (motor de 17/10, antes das correções)

**1. O volume total não atrasa a análise.** De mil para 3 milhões de Pix, a latência ficou no mesmo lugar, e o banco gasta menos de 10 ms por Pix:

| Pix no banco | tabela | motor p50 | ponta p50 | ponta p95 | no banco, por Pix |
|---:|---:|---:|---:|---:|---:|
| 1.265 | 3 MB | 68 ms | 125 ms | 152 ms | 6,7 ms |
| 101.260 | 203 MB | 74 ms | 129 ms | 152 ms | 7,5 ms |
| 1.001.260 | 2.014 MB | 72 ms | 129 ms | 146 ms | 8,3 ms |
| 3.001.260 | 6.168 MB | 66 ms | 115 ms | 129 ms | 7,3 ms |

Os índices compostos `(coluna, transaction_date DESC)` fazem cada consulta ler só as linhas da entidade e da janela. O tamanho da tabela não entra na conta.

**2. O que atrasa é o volume de uma entidade só, e quase tudo era Python, não banco:**

| entidade | tamanho | motor p50 | no banco, por Pix |
|---|---:|---:|---:|
| loja que recebe em 30 dias | 1.000 Pix | 177 ms | 12 ms |
| loja que recebe em 30 dias | 5.000 Pix | 2.098 ms | 24 ms |
| loja que recebe em 30 dias | 10.000 Pix | **8.071 ms** | 47 ms |
| pagador com histórico | 1.000 Pix | 89 ms | 14 ms |
| pagador com histórico | 5.000 Pix | 272 ms | 45 ms |
| pagador com histórico | 10.000 Pix | 713 ms | 82 ms |
| IP com Pix na última hora | 1.000 Pix | 70 ms | 13 ms |

A loja com 10 mil recebimentos levava 8 segundos por Pix, e o banco respondia por 47 ms disso. A causa estava em `engine/reference.py`: para achar o pico da janela móvel de cada dia, a função `_peaks` varria de novo todos os eventos anteriores para cada evento. O custo crescia com o quadrado. Medida isolada, sem banco nem rede: 1.000 eventos, 109 ms; 5.000, 2,8 s; 10.000, 11,4 s.

**3. A concorrência para num processo só.**

| chamadores | destinos diferentes | todos na mesma loja |
|---:|---:|---:|
| 1 | 6,7 Pix/s | 6,7 Pix/s |
| 4 | 13,8 Pix/s | 10,6 Pix/s |
| 8 | 14,5 Pix/s | 11,0 Pix/s |
| 16 | 15,6 Pix/s | 11,7 Pix/s |

A partir de 4 chamadores a vazão não sobe mais, e a latência cresce na mesma proporção: é a fila de um processo Python só (`uvicorn` sem `--workers`). Pix para a mesma loja fazem fila também na trava consultiva do recebedor, que é o que mantém a contagem certa sob concorrência.

**4. Disco: a explicação pesava mais que a análise.** Cada Pix gravava 1,7 KB de análise e mais 7,5 KB em 37 linhas da `pix_rule_result`, uma por regra avaliada. Com elas, cada gravação fazia 37 conferências de chave estrangeira.

## O que mudou por causa disso

| mudança | por quê | efeito |
|---|---|---|
| `_peaks` com a janela deslizando | o custo quadrático da seção 2 | mesmo resultado (conferido contra o código antigo em 500 históricos aleatórios, 3 tipos de régua e 3 janelas); 10 mil eventos passam de 11,4 s para 37 ms na função |
| sai a `pix_rule_result` | a seção 4 | uma linha por Pix em vez de 38. O que disparou continua no `metadata.rules`; o que não disparou fica pelo código, em `metadata.rules_not_triggered` |
| sai o limite do cliente | é do BAS (decisão do tech lead) | uma consulta a menos por Pix e duas regras a menos |
| a mediana do IP aprendido sai do Postgres, sobre os 200 pontos de GPS mais novos da /24 | o lugar de um IP fora da tabela vinha de todas as linhas com GPS da rede em 30 dias, levadas para o Python | a conta não cresce mais com a rede, e o índice parcial `pix_analysis_ip_network` já traz latitude e longitude |

## Depois das correções

Mesma ferramenta, mesmo computador, banco zerado e enchido de novo até 1 milhão de Pix.

| medida | antes | depois |
|---|---:|---:|
| cliente comum, ponta p50, 1 milhão de Pix no banco | 129 ms | **117 ms** |
| cliente comum, tempo no banco por Pix | 8,3 ms | **6,6 ms** |
| loja com 1.000 recebimentos em 30 dias, motor p50 | 177 ms | **80 ms** |
| loja com 5.000 recebimentos | 2.098 ms | **121 ms** |
| loja com 10.000 recebimentos | 8.071 ms | **171 ms** |
| pagador com 10.000 Pix no histórico, motor p50 | 713 ms | **324 ms** |
| rede /24 fora da tabela com 10.000 Pix com GPS, motor p50 | 132 ms | **65 ms** |
| vazão com 1 chamador | 6,7 Pix/s | **8,7 Pix/s** |
| vazão com 16 chamadores | 15,6 Pix/s | **18,8 Pix/s** |
| disco por Pix (análise + linhas de regra) | 9,2 KB | **2,2 KB** |

A loja com 10 mil recebimentos ficou 47 vezes mais rápida. A rede desconhecida com 10 mil pontos de GPS voltou ao custo de um Pix comum: o banco passou de 21 ms para 5 ms por Pix, e o tempo não cresce mais com a rede (65 ms com mil, cinco mil ou dez mil pontos). O pagador com 10 mil Pix caiu à metade, e o que sobrou é banco: 84 ms por Pix, das consultas que leem os 186 dias de histórico dele. A linha da análise cresceu de 1,7 KB para 2,2 KB porque passou a levar os códigos das regras que não dispararam; ainda assim, cada Pix grava um quarto do que gravava.

## Mais de um processo

A vazão de um processo para em uns 17 Pix por segundo: o Python faz uma conta de cada vez por processo, e cada Pix gasta uns 60 ms de regras. Para saber quanto ganha subindo mais processos, a medição roda a API com 4 (`uvicorn --workers 4`):

```bash
docker compose -f docker-compose.yml -f tools/escala/compose.escala.yml -f tools/escala/compose.processos.yml up -d --build --wait db antifraud-api
```

```bash
python tools/escala_antifraude.py --tamanhos 0 --secoes concorrencia --chamadores 1,4,8,16,32
```

**O compose da entrega continua com um processo só**, como o Base Service. A sobreposição `tools/escala/compose.processos.yml` vale só para esta medição: o uvicorn não junta `--reload` com `--workers`, e o `--reload` (a API recarregar quando um arquivo muda) é o jeito de desenvolver herdado do Base Service.

Mesmo banco e mesmo notebook (Intel i7-1165G7, 4 núcleos físicos e 8 threads), 15 Pix por chamador:

| chamadores | destinos diferentes, 1 processo | destinos diferentes, 4 processos | mesma loja, 1 processo | mesma loja, 4 processos |
|---:|---:|---:|---:|---:|
| 1 | 8,6 Pix/s (p50 109 ms) | 8,2 Pix/s (p50 107 ms) | 9,3 Pix/s | 8,0 Pix/s |
| 4 | 18,0 Pix/s (p50 211 ms) | 25,5 Pix/s (p50 145 ms) | 12,4 Pix/s | 17,1 Pix/s |
| 8 | 16,9 Pix/s (p50 467 ms) | **31,2 Pix/s** (p50 222 ms) | 13,1 Pix/s | 15,6 Pix/s |
| 16 | 17,4 Pix/s (p50 919 ms) | 25,9 Pix/s (p50 443 ms) | 13,0 Pix/s | 15,0 Pix/s |
| 32 | 17,6 Pix/s (p50 1.829 ms) | 29,5 Pix/s (p50 867 ms) | 12,9 Pix/s | 14,7 Pix/s |

**O que os números dizem:**

- **Com 4 processos, a vazão quase dobra** (de uns 17 para até 31 Pix por segundo), e a latência sob carga cai à metade (8 chamadores: de 467 para 222 ms).
- **A contagem continua certa.** A suíte inteira da `antifraud-api` (199 testes, com os de concorrência e o de escala) passou contra os 4 processos. A API não guarda estado na memória entre requisições, e as travas consultivas moram no Postgres, então valem entre processos.
- **Não chega a 4 vezes porque, neste notebook, a CPU acaba.** Com 8 chamadores, a máquina ficou só 18% ociosa: a API usou 3 núcleos, o Postgres 2,3, e o gerador de carga roda na mesma máquina. Num servidor, a API e o banco ficariam em máquinas separadas.
- **O banco gasta mais CPU do que o `pg_stat_statements` mostra.** O "no banco" das outras tabelas soma só a execução das consultas (uns 7 ms por Pix). Com 31 Pix por segundo, o Postgres ocupou 2,3 núcleos: a conta inclui planejar cada uma das cerca de 40 consultas de cada Pix, que vão sem preparo, e gravar o commit. É a próxima alavanca: menos idas ao banco por Pix.
- **A mesma loja não escala com processos.** Pix simultâneos para o mesmo recebedor fazem fila na trava dele, e ficam em uns 13 a 17 por segundo com 1 ou com 4 processos; ali a máquina ficou com metade da CPU parada. É o preço da contagem de pagadores da loja nunca errar.

## Conexões e driver: o experimento de 18/10

Um Pix de cliente comum manda **56 comandos SQL** ao banco. Com o planejamento ligado no `pg_stat_statements` (`pg_stat_statements.track_planning=on`), apareceu que o Postgres gastava mais tempo **planejando** essas consultas do que executando. A hipótese era que consultas preparadas, que o Postgres planeja uma vez por conexão, resolveriam. O `psycopg2` não prepara; o `psycopg` 3 prepara sozinho a consulta que se repete.

Antes disso, uma descoberta: com `APP_ENV=local`, que é o padrão do compose e vem do Base Service, a API usa `NullPool` (`antifraud-api/src/database.py`) e **abre conexão nova a cada requisição**. Em qualquer outro `APP_ENV`, ela usa um pool de 5 conexões. Consulta preparada só vale dentro de uma conexão, então o experimento comparou quatro montagens, todas por arquivo de sobreposição, sem mudar a entrega. Cada uma num banco zerado, 50 Pix de clientes com 40 Pix de histórico:

| montagem | conexões novas por Pix | execução no banco | planejamento | motor p50 | ponta p50 | 8 chamadores |
|---|---:|---:|---:|---:|---:|---:|
| A: como sobe hoje (`psycopg2`, `APP_ENV=local`) | 2 | 5,6 ms | 14,7 ms | 70 ms | 115 ms | 17,0 Pix/s |
| B: `psycopg2` com pool (`APP_ENV` de produção) | 0 | 3,1 ms | 9,0 ms | 52 ms | **81 ms** | 18,2 Pix/s |
| C: `psycopg` 3 com pool | 0 | 2,8 ms | 8,9 ms | 57 ms | 87 ms | 15,4 Pix/s |
| C com `plan_cache_mode=force_generic_plan` | 0 | 8,0 ms | 8,5 ms | 62 ms | 91 ms | 15,7 Pix/s |

**O que ficou:**

- **O ganho é do pool, não do driver.** Reaproveitar conexões tira 34 ms da ponta (de 115 para 81 ms, 30%). Para separar o pool do nível do log, que o `APP_ENV` também muda (`DEBUG` no local, `INFO` fora), uma quinta rodada ligou só o pool com `APP_ENV=local`: ponta de 80 ms, motor de 51 ms. O log não pesava.
- **O `psycopg` 3 não entrou.** O planejamento continuou em uns 9 ms por Pix, com ou sem o plano genérico forçado, e a vazão caiu. A troca foi desfeita.
- **O pool entrou, em todo ambiente.** Desde 18/10, `antifraud-api/src/database.py` cria o pool (5 conexões, até 15 por processo, com `pool_pre_ping`) também no modo local, mantendo o `psycopg2`. Os outros serviços do repositório continuam como no Base Service. **As seções anteriores deste documento foram medidas antes disso; a próxima traz os números de agora.**

## Com o pool: o que a entrega roda hoje

Mesmo notebook, banco zerado e enchido até 1 milhão de Pix, um processo, 30 Pix por linha:

| medida | sem pool | com pool |
|---|---:|---:|
| cliente comum, 1 milhão de Pix no banco: motor p50 | 69 ms | **49 ms** |
| cliente comum, 1 milhão de Pix no banco: ponta p50 | 117 ms | **79 ms** |
| cliente comum, tempo no banco por Pix | 6,6 ms | **3,3 ms** |
| pagador com 10.000 Pix: motor p50 | 324 ms | **166 ms** |
| loja com 1.000 recebimentos: motor p50 | 80 ms | **62 ms** |
| loja com 10.000 recebimentos: motor p50 (códigos diferentes, ver abaixo) | 171 ms | 217 ms |
| rede /24 fora da tabela com 10.000 Pix com GPS: motor p50 | 65 ms | **45 ms** |
| 1 chamador, 1 processo | 8,7 Pix/s | **11,8 Pix/s** |
| 8 chamadores, 1 processo | 17,0 Pix/s | 17,9 Pix/s |
| **16 chamadores, 4 processos** | 25,9 Pix/s | **40,8 Pix/s** |
| 16 chamadores na mesma loja, 4 processos | 15,0 Pix/s | 17,4 Pix/s |

Na entrega, do zero: bancada 141 de 141, 199 testes da `antifraud-api` (em 2min38, eram 3min31) e massa 27 de 27, com o motor em p50 44 ms e p95 50 ms (eram 64 e 78).

**O que muda na leitura:**

- **Com 4 processos, o pool faz a diferença que faltava.** Sem ele, cada Pix abria 2 conexões, e o Postgres gastava CPU criando processos; com ele, 4 processos chegam a 40,8 Pix por segundo, 2,3 vezes um processo só, contra 1,8 vez antes.
- **A loja com 10 mil recebimentos não piorou por causa do pool.** A linha da tabela compara códigos diferentes: os 171 ms são de antes de o `CONTA_LARANJA` ganhar a janela de 24 h (commit `f33ba60`), que calcula a régua de pagadores da loja uma segunda vez a cada Pix. Verificado com o mesmo código, motor p50, cada rodada com uma loja nova de 10 mil recebimentos:

  | montagem | rodadas | motor p50 |
  |---|---|---:|
  | com pool, janelas de 1 h e 24 h (o que está publicado) | 3 | 188, 191, 193 ms |
  | sem pool, janelas de 1 h e 24 h | 1 | 235 ms |
  | com pool, só a janela de 1 h (política de teste, sem a de 24 h) | 2 | 145, 176 ms |

  O pool tira uns 45 ms também neste caso. A janela de 24 h acrescenta uns 30 a 45 ms. E o mesmo caso oscila uns 30 ms entre rodadas: os 217 ms da tabela foram medidos com 1 milhão de Pix no banco, e os de cima com o banco quase vazio. O item 3 da lista abaixo, guardar a régua por conta e por dia, tira as duas contas do caminho de cada Pix.
- **Pix para a mesma loja continuam limitados pela trava dela**, agora em uns 17 a 20 por segundo com 4 processos.

## O que continua em aberto

As próximas alavancas, na ordem de ganho medido. Nenhuma foi feita antes da entrega: as de maior ganho mexem no coração do motor.

| # | O que | Evidência | Como melhorar | Custo e risco |
|---|---|---|---|---|
| 1 | **Planejamento das consultas** | 9 ms por Pix com pool (14,7 ms sem), contra 3 ms de execução; o driver não resolveu | menos comandos (item 2); ou preparar à mão as consultas mais frequentes, conferindo o plano de cada uma | médio |
| 2 | **Idas ao banco** | 56 comandos por Pix; a soma e contagem do pagador roda 3 vezes, uma por janela | juntar as janelas do mesmo pagador ou da mesma loja numa consulta só, com `FILTER` por janela | médio: mexe no `history_repository`, e cada número tem de continuar igual |
| 3 | **A régua é recalculada a cada Pix, mas só muda uma vez por dia** | ela é congelada no início do dia por desenho; o pagador com 10 mil Pix ainda leva 324 ms | guardar a régua por conta e por dia (numa tabela ou no Redis): o primeiro Pix do dia calcula, os outros leem | médio; a correção é garantida pelo próprio desenho |
| 4 | **A trava da loja segura o Pix inteiro** | a mesma loja fica em 13 a 17 Pix por segundo, com 1 ou 4 processos | calcular tudo e só então travar a loja para reler a contagem, gravar e fazer o commit (uns 10 ms em vez de uns 60 ms) | **alto:** é a garantia de que a contagem nunca erra |
| 5 | **Pagador muito ativo** | uns 84 ms no banco com 10 mil Pix; um `count(*)` lê o histórico inteiro só para saber se há 3 tentativas | parar de contar no 3 (`LIMIT`) e índices que já tragam valor e status (`INCLUDE`) | baixo, mas só ajuda o pagador muito ativo |
| 6 | **Disco no longo prazo** | 2,2 KB por Pix; o `analysis_key` é `CHAR(36)` com índice único de 222 MB em 3 milhões de linhas, sem nenhuma leitura | `analysis_key` como `UUID`, `metadata` mais enxuto, partição por mês com arquivamento | médio; exige recriar o banco |
| 7 | **Infraestrutura** | medido acima | mais processos ou réplicas (o pool já está ligado em todo ambiente), banco em outra máquina, PgBouncer quando houver muitas réplicas | fora do código |
