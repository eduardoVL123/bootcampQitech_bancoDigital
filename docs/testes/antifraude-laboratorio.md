# Laboratório da antifraud-api

Há duas ferramentas, e cada uma responde a uma pergunta diferente.

| ferramenta | pergunta | como |
|---|---|---|
| `tools/bancada_rfc_antifraude.py` | A API cumpre o contrato nos casos que já conhecemos? | 145 pedidos fixos do RFC, com gabarito de status, nível, cenário e regra em arquivo separado |
| `tools/laboratorio_antifraude.py` | Quanto golpe a API segura, quanto cliente honesto ela barra, e onde ela falha? | episódios sorteados a cada rodada, um caçador de burlas e um corpus que guarda tudo o que já escapou |

O `tools/cenarios_antifraude.py` é a massa da própria equipe da API, montada com o `tests/utils/pix.py` dos testes dela. As três ferramentas convivem: as duas de cima usam a sua própria base (`tools/laboratorio/pix_base.py`), só com a biblioteca padrão, e não mexem nos arquivos dos testes.

Para rodar, a API tem de estar de pé (`docker compose up -d db antifraud-api`) e o Python precisa do `requests` (o `.venv` do projeto já tem).

A suíte fixa sozinha não mede eficiência: com um caso por tipologia, a API pode passar em todos e ainda assim deixar escapar a variação seguinte. O laboratório existe para achar essa variação.

## Como o laboratório mede

O laboratório não confere o nome da regra. Ele confere o resultado.

**Golpe contido** é a decisão chegar ao nível que de fato segura aquele golpe. Esse é o ponto que mais engana:

| quem aperta o botão | exemplos | o que segura |
|---|---|---|
| o golpista, de outro aparelho | conta tomada, sondagem de limite, dreno lento | `facial`: ele não tem o rosto da vítima |
| a própria vítima, enganada | falsa central, falso parente, mão fantasma, QR Code adulterado, sequestro | só `rejected`: a vítima passa na selfie |
| o dono da conta laranja | repasse em cascata, fazenda de aparelhos | só `rejected` |

Por isso o relatório mostra **detectado** (houve algum atrito) separado de **contido**. Uma API que pede selfie em toda falsa central detecta 100% e contém 0%.

**Falso positivo** é rejeitar um cliente legítimo. **Fricção indevida** é pedir autenticação além do que o perfil justifica (cada perfil legítimo diz até onde a API pode ir). Se uma regra do BCB obriga o bloqueio, rejeitar não conta como erro.

**Proteção do cliente contra ele mesmo** é a terceira medida. Ninguém engana nem invade: o próprio titular decide algo que pode machucar (apostar cada vez mais de madrugada, furar o limite que ele mesmo escolheu, mandar as economias inteiras num impulso). Bloquear tira do cliente o que é dele, mas uma pausa ("tem certeza?", que na API é a selfie) e o respeito ao limite escolhido por ele protegem. Por isso o laboratório conta como **protegido** o Pix em que a API pausou ou segurou o limite do cliente, e como **excesso** o bloqueio além disso. Os Pix da mesma sequência que ainda estão dentro do hábito são legítimos comuns: proteger cedo demais é só atrito.

A **precisão projetada** responde: se só 0,1% (ou 1%) do tráfego real fosse golpe, quantos alertas seriam golpe de verdade? Ela cai rápido quando a API pede autenticação demais para quem é honesto.

## O ciclo

```
rodada  ->  "o que falta"  ->  corrigir a API  ->  regressao  ->  cacar  ->  rodada ...
```

1. **Rodada.** Sorteia 3 episódios de cada perfil, com botões sorteados, e manda tudo para a API. O relatório diz, por tipologia, quanto escapou e **qual botão faz a diferença** (por exemplo, `localizacao=mesma_cidade (100%) contra localizacao=outra_cidade (0%)`: a API depende do IP e não percebe o GPS falso).
2. **O que falta.** Para cada golpe que escapou: os sinais que ele deixa no payload, as regras que a API acionou, o que o contrato atual não carrega, a defesa conhecida, a fonte e o comando para repetir o pior episódio.
3. **Corrigir.** Mude a lógica da API com base no relatório, não no episódio. Corrigir só o episódio é decorar a prova.
4. **Regressão.** Repete tudo o que está no corpus com CPFs novos e marca cada item como `resolvida`, `aberta` ou `reaberta` (voltou a falhar depois de uma correção).
5. **Caçar.** Faz o papel do golpista que aprende: parte da versão ingênua do golpe e muda um botão por vez, ficando com a mudança que mais afrouxa a decisão (usa o `score` da resposta como desempate, se a API devolver). Cada achado é repetido com duas sementes novas para saber se é uma burla de verdade ou sorte.

O comando `loop` faz os passos 1, 4 e 5 sem parar, até três voltas seguidas sem nenhum erro.

## Comandos

```bash
python tools/laboratorio_antifraude.py catalogo
```

```bash
python tools/laboratorio_antifraude.py rodada
```

```bash
python tools/laboratorio_antifraude.py cacar --orcamento 25
```

```bash
python tools/laboratorio_antifraude.py cacar --tipo legitimo
```

```bash
python tools/laboratorio_antifraude.py regressao
```

```bash
python tools/laboratorio_antifraude.py metamorfico --quantidade 20
```

```bash
python tools/laboratorio_antifraude.py loop
```

Para repetir um episódio exato, Pix por Pix, use o comando que o relatório imprime em "Repetir o pior episódio".

Opções comuns: `--perfis a,b` restringe os perfis, `--semente N` repete a mesma história, `--url` aponta para outra API (o padrão é `http://localhost:${ANTIFRAUD_API_PORT:-3020}`, com o `INTERNAL_TOKEN` do ambiente). `gerar` grava a massa rotulada sem mandar nada, para inspecionar.

Os relatórios e o histórico ficam em `tools/resultados/` (fora do Git). O corpus fica em `tools/corpus_antifraude.json` e deve ser versionado: ele é a memória do que a API já errou.

## O que cada rodada cobre

**Golpes (15):** conta tomada, mão fantasma, falsa central, falso parente, QR Code adulterado, sequestro relâmpago, conta laranja, repasse em cascata, sondagem de limite, dreno lento e gradual, fazenda de aparelhos, rede suspeita, recebedor ou aparelho marcado, conta dormente, golpe escalonado (falso investimento ou golpe do amor).

**Legítimos difíceis (16):** rotina, pagamento recorrente, PJ e fornecedor, troca de celular, viajante, compra grande planejada, autônomo que recebe de muitos, racha da conta no bar, família à noite, dia do pagamento, aparelho da família, cliente sem permissão de GPS, e quatro situações de emergência e de vida real:

- **emergência da família no exterior:** filho e esposa na Austrália, e às 2h de Brasília o pai manda R$ 20 mil e depois compra remédio numa farmácia daqui;
- **brasileiro no exterior:** usa o app de dia por lá, que é madrugada aqui, com um IP que a API não conhece;
- **emergência no hospital de madrugada:** caução, farmácia e a corrida de volta;
- **compra de carro usado de um particular:** valor alto para uma pessoa nunca paga, idêntico a um golpe para quem só vê o Pix.

O Pix não atravessa fronteira. Mandar dinheiro para fora é um Pix em reais para uma empresa de remessa aqui, ou para a conta brasileira de quem está lá, e é assim que o laboratório simula. A localização de Sydney fica de propósito fora do seed (IPv6 de documentação): a API só descobre onde ela fica pelo GPS dos Pix anteriores.

**Proteção do cliente (2):** apostas compulsivas e esvaziar a reserva por impulso. O limite autoimposto furado e o aumento de limite e saque saíram junto com o limite do cliente, que é do BAS (18/10/2026).

Cada tipologia tem botões com as adaptações que o golpista faz quando a versão ingênua é barrada: aquecer o aparelho novo com Pix pequenos, usar conta laranja antiga em vez de nova, falsificar GPS e usar VPN na cidade da vítima, fatiar abaixo do limite, esperar a carência do aumento de limite, rotacionar o `device_id`. A lista completa sai em `catalogo`.

**Metamórficos** cobram coerência sem precisar de gabarito: a mesma história com CPFs novos tem de dar a mesma decisão, e a mesma história com o dobro do valor não pode dar uma decisão mais branda.

## Limites, para não se enganar

- **"Perfeito" não existe.** Toda antifraude troca golpe que passa por cliente honesto barrado. O objetivo realista é empurrar a contenção para cima sem deixar falso positivo e fricção subirem, olhando os dois números juntos.
- **A API pode decorar o gerador.** Se a lógica for ajustada olhando só estas tipologias, ela aprende o laboratório, não o golpe. Duas defesas: tratar o relatório como sintoma e corrigir a lógica geral, e separar algumas tipologias como prova cega (quem mexe na API não olha o resultado delas; rode com `--perfis` só de vez em quando).
- **Alguns golpes são indistinguíveis com o contrato atual.** No QR Code adulterado e na falsa central com conta laranja antiga, o Pix da vítima é igual a um Pix legítimo. O relatório lista em "sinais que o contrato atual não carrega" o que bancos usam nesses casos: chamada em curso, app de acesso remoto, forma de iniciação do Pix, troca recente de chip. Se nada disso entrar no contrato, a única defesa é olhar o recebedor.
- **Dados sintéticos não substituem dados reais.** Quando houver marcações de fraude reais (MED, DICT, contestação), elas devem virar tipologias novas no catálogo.
- **Referências regulatórias usadas:** limite noturno de R$ 1.000 entre pessoas físicas das 20h às 6h (IN BCB 512/2024, na redação da IN BCB 669/2025; a IN BCB 746/2026 também altera a 512, mas não o limite noturno) e limite de R$ 200 por Pix e R$ 1.000 por dia em aparelho nunca usado (Res. BCB 403/2024, em vigor desde 1/11/2024). Conferido em 17/10/2026 em notícias e agregadores de normas, não no texto consolidado do Banco Central.
- **O que o laboratório assume da API** (branch `feat/antifraud-api`): o contrato da seção 3.1 (`transaction_date`, `source_account`, `destination_account`, `source`), o IP resolvido pelas três faixas /24 do seed (SP, Recife, Lisboa) e o histórico formado só por Pix aprovados ou com selfie confirmada. Por isso, quando a API pede selfie e quem está com o aparelho é o titular (cliente honesto, vítima enganada ou dono da laranja), o laboratório confirma com `PATCH approved_by_client`. Quando é o golpista, ninguém confirma.
- **Toda conta é da casa** (`participant` 99999999). É assim que a API liga o que uma conta recebeu com o que ela paga depois. Com outro participante, ela veria duas contas e o repasse sumiria.
- **O dia simulado padrão é ontem**, porque a API recusa `transaction_date` no futuro (tolerância de 300 s). A suíte fixa tem a data do desafio, 2026-10-17, com Pix até as 23h: antes desse horário ela só roda com `TIME_SKEW_SECONDS` alto na API.

## Fontes da pesquisa

- Febraban, golpes mais comuns: <https://febrabantech.febraban.org.br/temas/seguranca/quase-4-em-cada-10-brasileiros-ja-sofreram-golpe-aponta-pesquisa-da-febraban>
- Pedidos de devolução negados em 2026: <https://sbtnews.sbt.com.br/noticia/brasil/golpe-no-pix-9-em-cada-10-reembolsos-sao-negados>
- Regras de aparelho novo (Res. BCB 403/2024): <https://bpmoney.com.br/negocios/pix-tera-novas-regras-de-seguranca-a-partir-de-1o-de-novembro-confira>
- Limite noturno (IN BCB 669/2025, que altera a IN BCB 512/2024): <https://www.legisweb.com.br/legislacao/?id=484165>
- MED 2.0 e rastreio em camadas: <https://dock.tech/fluid/blog/banking/med-2-0/>
- Mão fantasma: <https://www.santander.com.br/blog/golpe-da-mao-fantasma>
- Contas laranja e aluguel de contas antigas: <https://www.serasaexperian.com.br/conteudos/prevencao-a-fraude/entenda-como-o-pix-impulsiona-a-abertura-de-contas-laranjas>
- QR Code adulterado em lojas virtuais: <https://ohoje.com/2026/09/08/novo-golpe-troca-qr-code-do-pix-e-ja-atinge-90-sites-no-brasil/>
- Falso parente no WhatsApp: <https://tecnoblog.net/noticias/golpe-via-whatsapp-usa-dados-vazados-e-pede-dinheiro-a-parentes-da-vitima/>
- SIM swap: <https://www.welivesecurity.com/br/2022/03/10/fraudes-de-sim-swap-o-que-e-e-como-funciona/>
- Contas laranja e fraude de pagamento autorizado: <https://amlwatcher.com/blog/money-mule-detection-app-fraud-aml/>
- PaySim, simulador usado para testar controles de fraude: <https://ntnuopen.ntnu.no/ntnu-xmlui/handle/11250/2640900>
- Pix internacional ainda em estudo no BCB; hoje é feito via empresas de remessa: <https://sbtnews.sbt.com.br/noticia/economia/banco-central-avalia-ligar-pix-a-sistemas-de-outros-paises>
- Jogo responsável e autoexclusão nacional (Portarias SPA 1.231/2024 e 2.579/2025): <https://igamingbusiness.com/br/jogo-sustentavel/jogo-responsavel/sistema-brasileiro-de-autoexclusao-sera-lancado-ate-o-final-de-2025/>
