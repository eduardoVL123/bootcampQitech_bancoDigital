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

## O que continua em aberto

- **Mais processos em produção.** Medido acima: 4 processos quase dobram a vazão neste notebook. Em produção, seriam processos ou réplicas atrás de um balanceador, com o banco em outra máquina. Cada processo abre o próprio pool (até 15 conexões com `pool_size=5`), e o Postgres aceita 100 por padrão.
- **Menos idas ao banco por Pix.** São cerca de 40 consultas por Pix, cada uma planejada de novo. Juntar as consultas do mesmo pagador, ou prepará-las, diminui a CPU do Postgres, que é o que aparece quando há mais processos.
- **Pagador muito ativo.** Com 10 mil Pix no histórico, o banco gasta uns 80 ms por Pix. As consultas que mais pesam leem o histórico inteiro de 186 dias do pagador, e uma delas (`count(*)` por documento) não tem limite de tempo, só para saber se há pelo menos 3 tentativas.
- **O `analysis_key`** é `CHAR(36)` com índice único de 222 MB em 3 milhões de linhas, e nenhuma consulta busca por ele.
- **O `metadata`** é a maior parte da linha que sobrou.
