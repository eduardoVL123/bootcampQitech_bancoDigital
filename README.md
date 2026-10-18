# Grupo 8: Antifraude Pix

**Integrantes:** Carlos Alberto Magalhães Neto · Eduardo Lopes Valerio · Enrico Martim Zúcollo

Uma API que recebe um Pix e decide, antes de o dinheiro sair, se ele **aprova**, **pede verificação** (2FA) ou **reprova**, e explica o porquê. Ela mora em [`antifraud-api/`](antifraud-api/), sobe junto com o banco digital da fase 1 e tem **banco de dados próprio** (`antifraud`).

| Rota | O que faz |
|---|---|
| `POST /pix/transaction` | Analisa o Pix (contrato da seção 3.1 do desafio) e devolve `key`, `status` e `metadata`. `201` na primeira vez; `200` se o mesmo `id` chegar de novo com o mesmo conteúdo |
| `GET /pix/transaction/{id}` | Devolve a análise gravada, pelo `id` do Pix |
| `PATCH /pix/transaction/{id}` | O cliente informa o resultado da verificação pedida (`approved_by_client` ou `reproved_by_client`), como no fluxo de desafio da API Pix da QI. A análise original não muda. Repetir o mesmo resultado devolve a resposta original (`200`); o resultado oposto é `409`; resposta anterior ao Pix ou no futuro é `422` |

Todas pedem o cabeçalho `INTERNAL-TOKEN`, como os outros serviços do repositório.

## Como o motor de decisão funciona

Cada Pix passa por **33 regras**. Nenhuma decide sozinha, com exceções explícitas (os bloqueios). Cada regra devolve uma avaliação (`triggered`, `not_triggered` ou `not_evaluable`, quando falta dado), uma pontuação e uma frase com os números que a fizeram disparar. O motor junta tudo assim:

1. **O replay vem antes de tudo.** O mesmo `id` é o mesmo Pix: devolve a análise gravada e não conta como tentativa nova. O mesmo `id` com outro conteúdo é `409`.
2. **Dado impossível não é risco, é erro.** Data que não existe (mês 13, 30 de fevereiro, fuso +25:00) volta `400`; data mais de 5 minutos no futuro, ou anterior à abertura de uma das contas, volta `422`. Nos dois casos, sem ser analisada.
3. **A conta é uma só.** Agência, número e participante identificam a conta, e o titular e a abertura que o motor viu primeiro valem para sempre: a mesma conta não pode ser CPF num pedido e CNPJ no outro, nem ter a idade calculada por uma abertura que a validação não conferiu. Pedido que descreve uma conta conhecida com outro titular ou outra abertura volta `409` (`QIT006007`), sem gravar nada, nem a outra conta, se o pedido a tinha criado. Máscara, letra minúscula no CNPJ e outro fuso para o mesmo instante não são divergência. Inconsistência de entrada não vira `rejected`: não é decisão de fraude. Nenhuma conta antiga é atualizada.
4. **O histórico é lido com travas.** As duas contas são criadas em ordem fixa (a da chave única), e só então a análise trava o pagador, o recebedor, as duas contas e o aparelho com travas consultivas do Postgres (`pg_advisory_xact_lock`), sempre na mesma ordem. A chave da conta é a mesma como origem e como destino, e o `PATCH` do desafio pede as mesmas travas, montadas pela mesma função, a partir da análise gravada. Oito Pix simultâneos da mesma conta veem a contagem certa (1, 2, ..., 8), e dois Pix cruzados (A → B e B → A) não travam um ao outro, inclusive entre duas contas da casa que o motor nunca viu (antes da ordem fixa, os INSERTs das contas fechavam um deadlock em 2 de 10 rodadas). O IP fica de fora das travas: atrás de um CGNAT de operadora, milhares de clientes dividem o mesmo IP. Há teste para cada caso, e a mutação que tira a trava faz os testes ficarem vermelhos.
5. **As regras rodam** contra o Pix e o histórico. Toda janela de tempo é ancorada na `transaction_date` do Pix, nunca no relógio do servidor, e a hora local é sempre a de São Paulo (o mesmo instante escrito com outro fuso dá o mesmo resultado).
6. **A decisão** combina as pontuações (próxima seção) e o **cenário** dá nome ao que o motor acha que está acontecendo (`conta_laranja`, `conta_tomada`, `pagamento_recorrente`...). O cenário só explica: não soma pontos.
7. **Tudo é gravado** numa linha só por Pix: o `metadata` da análise traz cada regra que disparou ou não pôde ser avaliada, com pontos, eixo e motivo, e o código das que não dispararam (`rules_not_triggered`). As tabelas de análise recusam `UPDATE` e `DELETE` por trigger: o GET de um Pix antigo devolve exatamente o que foi decidido, com a versão da política que valia.

**Os parâmetros não estão no código.** Cortes, pesos e janelas moram na tabela `fraud_policy`, em JSON, com versão. Mudar um parâmetro é gravar uma política nova; cada análise guarda a versão que usou.

**"Aprovado" é dinheiro que saiu, a partir de quando saiu.** `two_factor_required` não aconteceu (resposta da organização), então não entra em montante, perfil nem familiaridade, até o cliente confirmar a verificação pelo `PATCH`, e só a partir da `event_date` da confirmação. O Pix das 10h confirmado às 10h05 era, numa análise das 10h03, um desafio pendente: ainda não era dinheiro, e ainda era uma decisão restritiva para a `SONDAGEM_DE_LIMITE`, mesmo que a confirmação já esteja gravada quando a consulta roda. Nas regras, o corte é o instante do Pix analisado; nas réguas congeladas no início do dia (perfil, calendário, totais diários, tíquete do recebedor, régua adaptativa), é o início do dia em São Paulo, com o Pix de treino estritamente antes dele: o Pix da meia-noite e a confirmação feita hoje entram só na régua de amanhã. O mesmo corte vale para o cadastro do aparelho e para as duas arestas da `REDE_SUSPEITA`. As janelas continuam contadas pela `transaction_date`; o corte só decide se a confirmação já existia. Já as **tentativas** contam todos os status: quem leva 2FA ou recusa e insiste é exatamente o sinal.

**Corte de eventos não é snapshot.** A régua congelada usa só o que aconteceu antes do corte, mas é recalculada a cada consulta: um Pix histórico gravado depois (com data antiga) ainda muda a amostra das próximas análises. Resolver a ingestão tardia por completo fica fora deste protótipo. As análises já gravadas não mudam.

**Movimentação é premissa da simulação.** No protótipo, a aprovação direta e o desafio confirmado são tratados como dinheiro que saiu. É uma premissa para o histórico, não prova de liquidação: o motor não vê o SPI.

**A régua de cada cliente.** As regras de ritmo, montante e concentração comparam o cliente com ele mesmo quando há histórico: para cada dia com movimento nos 30 dias anteriores, o motor guarda o pico da janela (por exemplo, o máximo de tentativas em 5 minutos naquele dia) e calcula a mediana `m` e a dispersão robusta `s = MAD / 0,6745`. O corte vira `max(mínimo, ⌈2m⌉, ⌈m + 3s⌉)`. A régua é congelada no início do dia (o ataque de hoje não entra na régua de hoje), dias sem movimento ficam de fora (nunca viram zero), e sem 7 dias ativos e 20 eventos a regra usa uma régua de reserva **firme**, porque conta nova ou pouco usada é exatamente o perfil da conta laranja e da conta recém-tomada.

## Regras

Valores em reais só para leitura; no banco e no código são centavos. **Bloqueio** = reprova sozinha. **Piso** = exige um nível mínimo de verificação sem somar pontos.

### Movimentação (o pagador e o dinheiro)

| Regra | Lógica | Parâmetros | Por quê |
|---|---|---|---|
| `LIMITE_POR_PIX` | valor do Pix | ≥ R$ 20.000: +40 · > R$ 100.000: **bloqueio**. Só informativo quando o `PERFIL` diz que o valor é normal para o cliente | Valor alto pede confirmação, não recusa: carro e imóvel existem. Quem paga R$ 40 mil ao fornecedor todo mês não leva 2FA por isso. O teto é operacional do protótipo, não teto do Pix |
| `PERFIL` | z modificado = 0,6745 × (valor − mediana) / MAD dos aprovados, contra a **primeira referência elegível**: (1) o par pagador → recebedor (5 pagamentos em 3 dias, cobrindo 14 dias, em 365 dias); (2) a fase do mês no calendário do próprio cliente (os dias em que ele concentra os pagamentos de R$ 1.000 ou mais, em ≥ 3 meses); (3) as saídas gerais (10 pagamentos em 3 dias, em 90 dias). Exige diferença ≥ R$ 500 | z > 3,5 e > 2× mediana: +30 · z > 7 e > 3× mediana: +50 · com MAD = 0: > 3×: +30, > 6×: +50 | Compara com o contexto certo: R$ 42 mil é normal para o fornecedor que recebe R$ 40 mil e estranho para o contato que recebe R$ 150. A mediana não se deixa puxar pelo próprio aluguel. 3,5 é o corte de outlier do z modificado (Iglewicz e Hoaglin). O par usa 365 dias porque um pagamento mensal nunca juntaria 5 ocorrências em 90 |
| `PERFIL_SEM_HISTORICO` | nenhuma referência elegível e valor alto | > R$ 5.000: +20 e **piso facial** | Sem referência não é fraude, mas também não é perfil normal |
| `VELOCITY` | tentativas de saída da conta em 5 e 30 min, contando esta, de qualquer status; um corte para CPF e outro para CNPJ | **Com régua:** ≥ moderado +40 · ≥ alto +60 e piso facial+documento (mínimos 3 e 5 para CPF, 10 e 20 para CNPJ). **Reserva** (5 min), CPF: ≥ 3 +25 · ≥ 5 +40 e piso facial · ≥ 10 +60 e piso facial+documento; CNPJ: ≥ 10 +25 · ≥ 20 +40 e piso facial · ≥ 40 +60 e piso facial+documento | Quem faz 40 Pix por hora no trabalho não está numa rajada; a conta nova que faz 5 em 5 minutos está. Empresa paga fornecedores e folha em lote: dez Pix em cinco minutos são o dia normal dela |
| `MONTANTE_24H` | aprovados em 24h + este, com pelo menos um aprovado antes | > R$ 50.000: +40. Com régua, exige também desviar do pico diário do cliente | Exposição acumulada abaixo do limite por Pix. Um Pix sozinho acima do corte é assunto do limite e do perfil (a massa de cenários pegou essa dupla contagem) |
| `FATIAMENTO` | 3 ou mais aprovados na última hora e a soma com este | > R$ 10.000: +40. Com régua, exige também o desvio | Vários Pix médios na mesma hora, cada um abaixo do corte de valor |
| `MONTANTE_DIARIO_ATIPICO` | acumulado aprovado de hoje + este contra a mediana dos totais diários, com pelo menos um aprovado antes hoje | > 3× a mediana e excesso ≥ R$ 1.000: +30. Mínimo de 7 dias com movimento em 30 | O dia como unidade de perfil. Compara o parcial de hoje com dias completos, conservador de propósito |
| `ORIGEM_NOVA` | conta pagadora com menos de 48h | valor > R$ 1.000: +25 | Conta recém-aberta movimentando é o começo típico de conta laranja ou de cadastro com dado roubado |
| `CONTA_REATIVADA` | atividade antiga observada, ≥ 60 dias parada, e agora ≥ 3 tentativas em 1h ou valor > R$ 5.000 | +30 | Conta comprada ou tomada fica parada e é usada de uma vez. O primeiro contato com o motor não é reativação |
| `SONDAGEM_DE_LIMITE` | depois de um 2FA ou recusa nos últimos 15 min, tentar de novo com valor menor; nas últimas 2 h, só vale a sequência de duas reduções. Para outro destino, só conta se o valor ainda for ≥ 30% do anterior | 1 redução: +30 · 2 reduções seguidas: +50 e piso facial+documento | Ir baixando até achar o valor que passa. Uma redução pode ser ajuste legítimo. O almoço de R$ 30 dez minutos depois do 2FA do carro é outro pagamento, não sondagem |
| `NOTURNO` | 20h às 6h em São Paulo, pessoa física para outra pessoa física, ou para PJ com conta de menos de 30 dias | valor > R$ 1.000: +25 | O Banco Central limita a R$ 1.000 o Pix noturno quando o recebedor é pessoa física diferente do pagador (IN BCB 512/2024, com as alterações da IN BCB 669/2025). Aqui é heurística de risco, não a regra regulatória. PJ estabelecida fica de fora (loja e delivery recebem de madrugada); a PJ nova entra, porque é o MEI de fachada da conta laranja |
| `DATA_RETROATIVA` | a `transaction_date` é anterior, por mais de 5 min, ao Pix mais novo já analisado da conta | **0 pontos** e piso facial+documento | Toda janela é ancorada na data que o chamador informa: seis Pix mandados no mesmo minuto, com as datas recuando uma hora cada, escondiam a rajada de `VELOCITY`, `FATIAMENTO` e `SONDAGEM`. Até 5 min nada muda (a organização avisou que as datas chegam pouco fora de ordem), e o relógio do servidor não entra |

### Acesso (de onde e como)

| Regra | Lógica | Parâmetros | Por quê |
|---|---|---|---|
| `APARELHO_NOVO` | `device_id` nunca usado pelo titular, que tem ≥ 3 tentativas | +20 | Troca de aparelho é o momento da conta tomada |
| `APARELHO_NAO_CADASTRADO` | pelo app ou pela web, aparelho que não é o do primeiro Pix do titular nem foi confirmado numa verificação (`PATCH approved_by_client`) antes deste Pix | > R$ 200 no Pix ou > R$ 1.000 no dia nesse aparelho: **0 pontos** e piso facial | A regra do Banco Central para aparelho não cadastrado (Res. BCB 403/2024): acima desses valores, o aparelho precisa ser cadastrado, e a facial faz esse papel. O contrato não traz cadastro de aparelho, então "cadastrado" é uma aproximação |
| `VIAGEM_IMPOSSIVEL` | distância (Haversine) entre este Pix e o último ponto conhecido do titular, dividida pelo tempo. O ponto é o GPS; sem GPS, o lugar do IP | > 900 km/h e > 100 km (GPS) ou > 500 km (IP): +40. Com aparelho novo junto: piso facial+documento | 900 km/h é o cruzeiro de um avião comercial. Com IP, o piso de distância sobe porque IP é impreciso |
| `GEO_IP_DIVERGENTE` | GPS e lugar do IP a mais de 500 km | +30 | GPS forjado ou aparelho operado de longe. 500 km cobrem a operadora que sai para a internet por outro estado |
| `AMBIENTE_INCOERENTE` | GPS ou IP fora do retângulo do Brasil | +20 | Brasileiro viaja, então só soma |
| `GEO_AUSENTE` | o Pix chega sem `geolocation`, e o titular não é alguém que nunca manda (3 tentativas em 90 dias, nenhuma com GPS) | `app` +20 · `web` +20 · `api` 0 | O campo é opcional no contrato e nunca dá erro. Pelo app e pela web a ausência pesa, sem obrigar verificação sozinha (decisão do time com o tech lead). Quem negou a localização para sempre não leva os +20 em todo Pix: para ele, a ausência não é mudança. Pela `api`, uma empresa pagando pelo próprio sistema não tem GPS |
| `APARELHO_COMPARTILHADO` | ≥ 3 titulares pagando pelo mesmo aparelho em 30 dias | +25 | Família divide celular: sinal, não bloqueio |
| `IP_COMPARTILHADO` | ≥ 5 titulares no mesmo IP na última hora, numa rede (/24) nova para quem paga | +15 | Operadora põe milhares atrás do mesmo IP (CGNAT): contado só pelo IP, somava com o `NOTURNO` e pedia a facial do quinto cliente que pagasse um amigo à noite. A fazenda de contas aparece numa rede que nenhuma delas usava |
| `RUPTURA_DE_CONTEXTO` | acesso (aparelho novo, ou GPS a > 50 km de todos os pontos habituais) **e** dinheiro (perfil ou ritmo fora da régua do próprio cliente) **e** relacionamento (destino sem familiaridade, num cliente com histórico) | **0 pontos** e piso facial+documento | O retrato da conta tomada. Não soma: cada componente já pontuou na sua regra. IP diferente e GPS ausente não contam como "lugar diferente" |

### Destino (quem recebe)

| Regra | Lógica | Parâmetros | Por quê |
|---|---|---|---|
| `DESTINO_NOVO` | idade da conta destino | < 30 dias: +20 · < 1 dia: +30 | Golpe usa conta de passagem nova. A conta do exemplo do desafio tem 7 dias e 13 horas: com corte em 7 dias, a regra não a pegaria |
| `TETO_DESTINO_NOVO` | conta destino com menos de 7 dias e Pix acima de R$ 200 | 0 pontos. Só pesa com o eixo destino no corte e sem denúncia do recebedor: aí reprova | Concentração em conta nova pode ser loja lançando produto ou conta laranja. Na primeira semana, antes de a conta ter régua, a loja vende o tíquete pequeno e a laranja não recebe o valor alto |
| `CONTRAPARTE_INEDITA` | primeiro pagamento aprovado deste titular para aquele titular | valor > R$ 1.000: +15 | Todo aluguel um dia foi o primeiro: só soma com outros sinais |
| `TICKET_DO_RECEBEDOR` | o valor contra o que se costuma pagar ao recebedor. **Com régua** (≥ 10 créditos aprovados de ≥ 3 outros clientes da casa, em 3 dias, nos 90 dias até ontem): mediana e MAD, como no `PERFIL`. **Sem régua**, se é PJ: o teto de tíquete da atividade, pelo CNAE do mock de cadastro | desvio moderado ou acima do teto: +20 · desvio alto ou mais de 5× o teto: +40 · 0 se o pagador já pagou esse valor, ou mais, a esse recebedor | A doceria não recebe R$ 20 mil de uma vez. Só dificulta (2FA): encomenda grande existe, e a reprovação só vem se outro eixo concordar. O próprio pagador fica fora da régua, porque o que ele paga ali já é o par do `PERFIL` |
| `CONTA_LARANJA` | titulares diferentes pagando a mesma conta, de qualquer status, em duas janelas: a última hora e as últimas 24 h; vale a que pontuar mais | **Com régua do recebedor:** ≥ moderado +40 · ≥ alto +60 (mínimos 5 e 10 em 1 h, 10 e 20 em 24 h). **Reserva em 1 h:** conta < 30 dias, ≥ 5 +40, ≥ 10 +60; conta antiga, ≥ 5 +20, ≥ 10 +30. **Reserva em 24 h:** os mesmos pesos com 10 e 20 pagadores | Concentração. A loja que sempre recebe de 30 clientes por hora não é laranja; a conta laranja típica é nova e sem histórico. A janela de 24 h pega a laranja que espalha as vítimas ao longo do dia |
| `REPASSE_RAPIDO` | o dinheiro de terceiros que entrou na conta está saindo: na última hora (≥ 3 titulares ainda expostos) ou nas últimas 24 h (≥ 5), o escoamento **acumulado** chega a 80% da base líquida, contando este Pix, e este Pix escoa parte do que entrou. Devolução só até o crédito que quem pagou ainda tem na conta (ver abaixo) | +60 se o destino é novo para ela ou há desvio de perfil · 0 se é o fornecedor de sempre com perfil e ritmo normais · +20 se inconclusivo. As duas janelas são avaliadas e vale a de mais pontos; no empate, a mais curta | Dispersão: o lado de saída da conta laranja. Três saídas de R$ 1.000 depois de três entradas de R$ 1.000 são o mesmo repasse que uma saída de R$ 3.000, e o centavo que o destino mandou antes não transforma o dinheiro das vítimas em devolução. A janela de 24 h pega a laranja que espera horas para repassar |
| `COORDENACAO_ENTRE_CONTAS` | um aparelho, ≥ 3 titulares pagadores, a mesma conta destino com menos de 7 dias, em 10 min | +40 e piso facial. Zera o `APARELHO_COMPARTILHADO` dos mesmos titulares | Várias contas operadas juntas para escoar para uma conta nova. O mesmo fato não conta duas vezes |
| `REDE_SUSPEITA` | o destino está a até dois saltos de uma conta com evidência qualificada (a âncora pagou o destino, ou pagou quem pagou), por Pix aprovados de pelo menos R$ 10 em 30 dias, e o pagador ainda não paga esse destino | +30, com o caminho no `metadata` | Vínculos de 1º e 2º grau, por SQL, sem banco de grafos. O vizinho não vira âncora nova, e a suspeita não se propaga sem fim. Sem o corte de valor, uma âncora que é cliente da casa contaminava qualquer conta com um Pix de R$ 0,01 |
| `REPUTACAO_EXTERNA` | contadores do **mock** de reputação no formato do `destination_statistics` da API Pix da QI (`mule_accounts`, `scammer_accounts`, `distinct_fraud_reporters`, `open_reports`... em 90 dias, 12 meses, 60 meses) | **bloqueio** com golpe ou laranja em 90 dias · +40 com denúncia aberta ou ocorrência em 12 meses · fraude de cadastro: +40 se a conta destino tem menos de 90 dias, **bloqueio** se é do próprio pagador e tem menos de 30 dias, 0 para a conta antiga · papel de vítima: 0 | `mule_accounts` e `scammer_accounts` são marcações de fraude, que só existem depois de a instituição do recebedor analisar e confirmar: uma basta. Denúncia sem análise é `open_reports`, e essa só soma. Quem teve a identidade roubada é a vítima, não o fraudador, mas a conta NOVA no CPF dela pode ser a que o fraudador abriu: é o golpe da "conta segura". O mock é fictício, determinístico e marcado `is_mock` |
| `REPUTACAO_INTERNA` | documento destino ou aparelho na lista interna vigente | documento com fraude confirmada: **bloqueio** · "não fui eu" do titular e aparelho: +40 | Casos confirmados (semeados) e o "não fui eu" do titular depois de um desafio. Contra conta que a casa já sabe que é de golpe, 2FA não protege: quem paga é a vítima, e ela passa na facial. O "não fui eu" é a palavra de um cliente só, e por isso soma sem bloquear. **Nunca** a decisão do próprio motor: uma rejeição por limite não diz nada sobre o recebedor, e alimentar a lista com ela geraria falsos positivos em cadeia |
| `MESMA_TITULARIDADE` | mesmo documento nos dois lados | redutor até −10 | Transferir entre os próprios bancos é o Pix de menor risco. Desconta só da família de valor: contas do mesmo dono também podem ser tomadas |
| `DESTINO_CONFIAVEL` | ≥ 3 pagamentos aprovados a este titular, em 3 dias diferentes, o primeiro há ≥ 7 dias, e o valor de agora ≤ o maior já pago | redutor até −10 | A regra do aluguel. Um Pix de R$ 10 não "aquece" o destino para um de R$ 2.500 |

### Como o `REPASSE_RAPIDO` conta o repasse

A regra não compara o Pix sozinho com o que entrou: ela refaz, a cada Pix, a projeção do dinheiro de terceiros que passou pela conta na janela, a partir das análises e confirmações que o motor já tem (`controllers/engine/flow.py`). Nada novo é gravado: não é um ledger.

- **O que entra:** só o que virou dinheiro no instante avaliado. Aprovação direta fica disponível na `transaction_date`; desafio confirmado, em `max(transaction_date, event_date)`, e só se a confirmação já tinha acontecido. Um Pix antigo confirmado dentro da janela entra nela, no instante da confirmação, nunca antes. Recusado, rejeitado e desafio pendente não movimentam nada (continuam contando nas regras de tentativas). Empate de instante se desfaz pelo id, e o Pix em análise entra por último, uma vez só, como saída candidata: nada é consumido antes de ele virar dinheiro, e o replay não conta de novo.
- **Lotes em fila (FIFO):** cada entrada de outro titular vira um lote, numa fila global e na lista daquele titular. Entrada do próprio titular não é dinheiro de terceiros, e Pix da conta para ela mesma não move nada.
- **Devolução até o crédito:** uma saída para quem pagou é devolução só até o crédito que ele ainda tem na conta, e consome esse crédito. Estar entre os pagadores não basta: o destino que mandou R$ 0,01 tem R$ 0,01 de devolução. Crédito usado numa devolução não justifica outra.
- **Escoamento:** o resto da saída consome os lotes de terceiros mais antigos. Lote consumido não volta, e saída anterior a uma entrada não a consome. Mandar para outra conta do mesmo titular escoa como qualquer outra saída: não há isenção automática para "conta própria" financiada por vítimas.
- **As contas, em centavos inteiros:** `I` é o que entrou de terceiros; `R`, as devoluções reconhecidas; `E`, o escoamento coberto por lotes de terceiros (os dois com o Pix atual); `B = I − R`, a base líquida. Titular exposto é quem recebeu de volta menos do que pagou (o lote escoado continua sendo exposição dele). O repasse aparece com titulares expostos suficientes, `B > 0`, `E / B ≥ 80%` (comparado sem ponto flutuante: `5·E ≥ 4·B`) e o Pix atual escoando alguma parte do pool. Uma devolução integral legítima não herda o alerta das saídas anteriores.
- **Exemplo:** quatro pessoas pagam R$ 1.000 e a conta manda R$ 3.500 para uma delas. São R$ 1.000 de devolução e R$ 2.500 de escoamento, sobre uma base de R$ 3.000 e três pagadores ainda expostos: 83%, repasse.

O `metadata` da regra traz a janela, `incoming`, `refunded`, `outflow`, `base`, a parte do Pix atual (`current_refund`, `current_outflow`), `qualified_payers` e `attribution: "fifo_heuristic"`. **FIFO é uma atribuição heurística**, porque dinheiro é fungível: ela não prova que uma saída devolve um Pix específico. E a projeção só enxerga o que passou pelo motor dentro da janela: dinheiro de antes dela, ou que chegou por outro banco, não aparece. A consulta é uma só por Pix (os eventos das 24 h, em lote, nos índices por conta e data e num índice parcial das confirmações), e a projeção é uma varredura linear.

**Sinais sem pontos** (em `metadata.signals`): PF ou PJ de cada ponta, dígito verificador dos documentos (um CPF inventado numa massa de teste não vira fraude), idade das contas, fuso do horário, de onde veio a localização do IP.

## Como as regras viram decisão

**Eixos e famílias.** Cada regra pertence a uma família de evidências que medem o mesmo fato, e cada família a um de três eixos: **movimentação** (o pagador e o dinheiro), **acesso** (de onde e como) e **destino** (quem recebe). **Dentro de uma família, só a maior pontuação conta**: limite e perfil olham, os dois, o valor, e um Pix alto fora do perfil soma 50, não 90. As regras correlacionadas aparecem no `metadata` com `effective_points: 0` e `correlated: true`.

**Os redutores** (mesma titularidade e destino confiável) tiram até 10 pontos cada, só da família de valor, juntos no máximo 20, sem deixar a família negativa. Não reduzem pisos nem bloqueios.

**A decisão**, nesta ordem de prioridade:

| Condição | `status` | Verificação (`metadata.authentication.level`) |
|---|---|---|
| Algum bloqueio: teto operacional, fraude confirmada do recebedor (mock ou lista interna), conta segura | `rejected` | `none` |
| Score ≥ 80 **e** pelo menos dois eixos com ≥ 20 pontos | `rejected` | `none` |
| Eixo destino com ≥ 80 pontos, sozinho (`reject_destination_alone`), com denúncia do recebedor ou acima do teto da conta nova | `rejected` | `none` |
| Score ≥ 60, ou um piso `facial_document` | `two_factor_required` | `facial_document`: facial e documento |
| Score ≥ 40, ou um piso `facial` | `two_factor_required` | `facial` |
| O resto | `approved` | `none` |

O score é a soma das contribuições efetivas, de 0 a 100. **Ele não é probabilidade**: 80 pontos não são 80% de chance de fraude.

**Por que a rejeição exige dois eixos.** Um sinal sozinho, por mais forte, pode ter explicação legítima: uma loja recebe de muita gente, uma família divide o celular, um cliente viaja. Quando o risco alto está concentrado num eixo só, o motor pede a verificação reforçada em vez de reprovar. Bloquear cliente bom também é prejuízo. Quando o dinheiro, o acesso e o destino estranham juntos, aí reprova. A exceção é a evidência **confirmada** do recebedor: ela bloqueia sozinha, porque a verificação só responde "é o dono da conta mesmo?", e no golpe quem paga é o próprio dono, enganado (Res. BCB 501/2025: recusar pagamento para conta com fundada suspeita de fraude). O eixo **destino** com 80 ou mais também reprova sozinho, mas só com mais um fato, porque concentração em conta nova é ambígua: pode ser a loja lançando um produto ou a conta laranja recebendo das vítimas. O primeiro fato é alguém já ter denunciado o recebedor: o alerta do mock externo (denúncia aberta) ou o "não fui eu" de outro cliente. Loja de verdade não junta denúncia na primeira semana, e ali a verificação não protege: quem faz a selfie é o pagador enganado, e ele passa. O segundo é o teto da conta nova (`TETO_DESTINO_NOVO`): na primeira semana, antes de a conta ter a régua dela, o Pix acima de R$ 200 reprova. A loja vende o tíquete pequeno, e a laranja não recebe o valor alto; é o teto que reprova o repasse da conta laranja para uma conta de 3 horas. Fora disso, vale a tabela: dez clientes numa hora para uma conta de 10 dias pedem facial e documento. O aparelho de quem paga na lista interna não conta como denúncia do recebedor: é risco do pagador, e contra ele a facial funciona. Tirar `reject_destination_alone` da política desliga o ramo.

**Qual eixo pesou na rejeição.** Todo Pix rejeitado traz `metadata.rejection_axis`, com `movimentacao`, `acesso` ou `destino`. No bloqueio, é o eixo da regra que bloqueou (o teto é movimentação; a fraude confirmada do recebedor é destino). Na rejeição pela soma, é o eixo com mais pontos, e no empate fica o eixo da regra que explica a decisão (`reason`). Nos outros status, `rejection_axis` vem `null`.

**Quando pede 2FA, e qual.** O status público é sempre um dos três do contrato. O nível vai no `metadata`: `facial` para a dúvida moderada (40 a 59 pontos, ou piso facial), `facial_document` para a forte (60 ou mais num eixo, ou piso reforçado). O motor **pede** a verificação; quem a executa é o app do cliente, e o resultado volta pelo `PATCH`.

Exemplo, o payload da seção 3.1 do desafio (Pix de R$ 1.500 às 22:15, conta destino com 7 dias):

```json
{
  "key": "…",
  "status": "two_factor_required",
  "metadata": {
    "risk_score": 45,
    "risk_axes": {"movimentacao": 25, "acesso": 0, "destino": 20},
    "rejection_axis": null,
    "reason": "NOTURNO",
    "reason_description": "R$ 1.500,00 as 22:15 (Sao Paulo), de pessoa fisica para outra pessoa fisica.",
    "authentication": {"level": "facial", "required_checks": ["facial"], "execution": "required_not_executed"},
    "scenario": "primeiro_pagamento",
    "rules": [
      {"rule": "NOTURNO", "evaluation": "triggered", "raw_points": 25, "effective_points": 25, "...": "..."},
      {"rule": "DESTINO_NOVO", "evaluation": "triggered", "raw_points": 20, "effective_points": 20, "...": "..."},
      {"rule": "CONTRAPARTE_INEDITA", "evaluation": "triggered", "raw_points": 15, "effective_points": 0, "correlated": true, "...": "..."}
    ],
    "rules_not_triggered": ["PERFIL", "LIMITE_POR_PIX", "VELOCITY", "..."],
    "reputation": {"provider": "mock_bureau", "is_mock": true, "signal": "not_found"},
    "latency_ms": 55
  }
}
```

## O `PATCH` do desafio e os erros

O cliente responde o desafio uma vez. A ordem do `PATCH`:

1. **A data precisa existir.** 30 de fevereiro é `400`, inclusive quando o pedido repete uma resposta já gravada.
2. **A análise precisa ter pedido o desafio** (`404` se não existe, `409 QIT006005` se não pediu).
3. **As travas são as da própria análise:** as mesmas chaves do `POST`, montadas a partir dos dados gravados. A resposta espera o Pix da mesma conta que está sendo analisado, e duas respostas do mesmo desafio esperam uma a outra.
4. **Com as travas, o resultado é relido.** O mesmo resultado devolve `200` com o registro original: a `event_date` não muda, a denúncia não se repete e a análise não é refeita. O oposto é `409 QIT006006`. Respostas simultâneas gravam uma vez só: iguais dão todas `200`, opostas dão uma vencedora e `409` para as outras, nunca `500`.
5. **Só a primeira resposta passa pela cronologia:** `transaction_date ≤ event_date ≤ agora + 5 min` (a mesma folga do `POST`). Anterior ao Pix é `422 QIT006008`; no futuro, `422 QIT006002`. Responder no mesmo instante do Pix vale, e não há prazo máximo: a confirmação de anos atrás vale para a simulação daquela época.
6. **O resultado e a lista interna são gravados juntos.** O "não fui eu" põe o aparelho na lista por 30 dias e o documento destino em cautelar (+40) por 24 horas. Vira fraude confirmada, por 30 dias, com uma segunda fonte independente: outro titular, nos 30 dias, ou a reputação externa. Tudo vale a partir da `event_date` validada, nunca antes dela: uma análise de um instante anterior à denúncia não a enxerga, como não enxerga a confirmação de 2FA futura.

| Código | HTTP | Quando acontece |
|---|---|---|
| `QIT006001` | 404 | não existe análise para esse `id` |
| `QIT006002` | 422 | data mais de 5 minutos à frente do relógio do servidor (a do Pix, ou a resposta do desafio) |
| `QIT006003` | 422 | o Pix é anterior à abertura de uma das contas |
| `QIT006004` | 409 | o mesmo `id` com outro conteúdo |
| `QIT006005` | 409 | resposta de desafio para uma análise que não pediu desafio |
| `QIT006006` | 409 | o desafio já tem o resultado oposto |
| `QIT006007` | 409 | a conta já é conhecida com outro titular ou outra data de abertura |
| `QIT006008` | 422 | a resposta do desafio é anterior ao Pix |

Os erros de formato e de token são os comuns a todas as APIs do repositório (`QIT000…`, na seção 7 da fase 1).

## Como rodar e testar

```bash
docker compose up -d --build --wait
```

Sobem os serviços da fase 1 e a `antifraud-api`, na porta **3020** (`ANTIFRAUD_API_PORT` no `.env` muda isso). Um Pix:

```bash
curl -s -X POST http://localhost:3020/pix/transaction \
  -H "INTERNAL-TOKEN: default_token" -H "Content-Type: application/json" \
  -d '{"id":"pix-000123","amount":150000,"transaction_date":"2026-10-17T22:15:00-03:00",
       "source_account":{"branch":"0001","account_number":"88213","opening_date":"2025-03-02T10:00:00-03:00","owner":{"document_number":"123.456.789-09"}},
       "destination_account":{"participant":"60701190","branch":"3675","account_number":"10442","opening_date":"2026-10-10T09:00:00-03:00","owner":{"document_number":"987.654.321-00"}},
       "source":{"device_id":"dvc-9f2c71a8","channel":"app","ip":"198.51.100.23","geolocation":{"latitude":-23.56,"longitude":-46.65}}}'
curl -s http://localhost:3020/pix/transaction/pix-000123 -H "INTERNAL-TOKEN: default_token"
```

É o payload exato da seção 3.1 do desafio. Antes das 22:15 de 17/10/2026, essa data ainda está no futuro e a API responde `422 QIT006002`, como deve: o motor não aceita Pix com data mais de 5 minutos à frente do relógio.

Os testes (black box, só por HTTP, sem importar nada de `src/`):

```bash
pip install -r requirements-dev.txt
pytest tests/antifraud_api -v
```

A matemática da projeção do repasse (consumo dos lotes, ordem, fronteira do corte) tem testes de unidade, que importam `src` e rodam sem banco nem API. Ficam fora de `tests/`, que é caixa-preta, e o CI não os roda:

```bash
pytest antifraud-api/tests
```

A massa de cenários por mutação, que imprime a tabela da próxima seção:

```bash
python tools/cenarios_antifraude.py
```

A medição de escala: o banco com até 3 milhões de Pix, a loja e o pagador com milhares de Pix, a rede desconhecida e a concorrência. O resultado e a leitura dele estão em [`docs/testes/antifraude-escala.md`](docs/testes/antifraude-escala.md):

```bash
docker compose -f docker-compose.yml -f tools/escala/compose.escala.yml up -d --build --wait db antifraud-api
```

```bash
python tools/escala_antifraude.py
```

Os números do documento de escala são da versão **anterior** às correções de 18/10/2026 (repasse acumulado, identidade da conta, cortes das confirmações e `PATCH`), e não foram medidos de novo. A consulta nova do repasse foi medida à parte, no ambiente local (Windows, Postgres 18 sem Docker), com uma conta concentrada semeada por SQL num banco de 371 mil Pix. A conta tinha 56 mil entradas em 90 dias e 8.000 eventos de dinheiro nas últimas 24 h, entre eles 1.000 desafios confirmados, metade de Pix anteriores à janela:

- A consulta (`EXPLAIN ANALYZE`) levou 50 ms em série e 93 a 99 ms com os dois workers paralelos que o Postgres escolheu: no Windows, subir worker custa cerca de 50 ms. Os ramos usam os índices por conta e data. O ramo "Pix antigo confirmado na janela" usa o índice parcial das confirmações quando elas são uma fração pequena da tabela, e a projeção das 24 h levou 21 ms.
- Na API, no mesmo banco, comparada com a versão anterior: o Pix dessa conta foi de 350 a 400 ms para 510 a 610 ms de motor (`latency_ms`). O Pix de um pagador comum ficou igual, em 42 a 55 ms.

> **Mudou o `database/antifraud.sql`?** O banco nasce de uma imagem que *copia* o arquivo. Recriar só o volume não basta: `docker compose down -v && docker compose up -d --build --wait`. Sem o `--build`, o banco sobe com a política antiga. As correções de 18/10/2026 acrescentaram um índice (`pix_challenge_result_approved_event`).

## Resultado na massa sintética

A ferramenta cria pessoas fictícias com histórico gerado pela própria API (até 5 meses) e aplica uma mutação por cenário. **É massa sintética:** os números verificam que o motor faz o que este README descreve, não medem eficácia contra fraude real.

**Tráfego legítimo**

| Cenario | Esperado | Obtido | Score | Cenario deduzido | Regras que pesaram | Ok |
|---|---|---|---:|---|---|:-:|
| compra do dia a dia | approved | approved | 0 | sem_alerta_relevante |  | sim |
| aluguel recorrente (5 meses) | approved | approved | 0 | pagamento_recorrente |  | sim |
| fornecedor de sempre (R$ 42 mil) | approved | approved | 0 | sem_alerta_relevante |  | sim |
| transferencia para a propria conta | approved ou facial | facial | 40 | risco_contextual | PERFIL +50, MESMA_TITULARIDADE -10 | sim |
| empresa pela api, sem GPS | approved | approved | 0 | sem_alerta_relevante |  | sim |
| cliente novo, R$ 100 | approved | approved | 0 | sem_alerta_relevante |  | sim |
| loja que recebe de 10 clientes por hora | approved | approved | 0 | sem_alerta_relevante |  | sim |
| primeiro aluguel (R$ 2.500) | approved ou facial ou facial_document | facial_document | 65 | primeiro_pagamento | PERFIL +50, CONTRAPARTE_INEDITA +15 | sim |
| payload do documento oficial | facial | facial | 45 | primeiro_pagamento | NOTURNO +25, DESTINO_NOVO +20 | sim |
| 6 clientes da mesma operadora (CGNAT), 21h | approved | approved | 25 | pagamento_recorrente | NOTURNO +25 | sim |
| almoco de R$ 30 depois do 2FA do carro | approved | approved | 0 | sem_alerta_relevante |  | sim |
| quem nunca manda GPS, destino de 20 dias | approved | approved | 20 | risco_contextual | DESTINO_NOVO +20 | sim |

**Tráfego fraudulento**

| Cenario | Esperado | Obtido | Score | Cenario deduzido | Regras que pesaram | Ok |
|---|---|---|---:|---|---|:-:|
| acima do teto operacional | rejected | rejected | 35 | restricao_por_limite | LIMITE_POR_PIX (bloqueio), PERFIL_SEM_HISTORICO +20, CONTRAPARTE_INEDITA +15 | sim |
| recebedor com marcacao critica (mock) | rejected | rejected | 0 | risco_critico_do_recebedor | REPUTACAO_EXTERNA (bloqueio) | sim |
| noite, R$ 25 mil, sem GPS | rejected | rejected | 100 | coacao_noturna | LIMITE_POR_PIX +40, NOTURNO +25, GEO_AUSENTE +20, CONTRAPARTE_INEDITA +15 | sim |
| conta tomada (aparelho novo, Recife em 15 min) | facial_document ou rejected | rejected | 100 | conta_tomada | PERFIL +50, VIAGEM_IMPOSSIVEL +40, MONTANTE_DIARIO_ATIPICO +30, DESTINO_NOVO +20 | sim |
| rajada de 10 Pix em 5 min | facial_document | facial_document | 60 | esvaziamento_fatiado | VELOCITY +60 | sim |
| sondagem: R$ 30 mil, 25 mil, 19 mil | facial_document ou rejected | facial_document | 85 | sondagem_de_limite | SONDAGEM_DE_LIMITE +50, PERFIL_SEM_HISTORICO +20, CONTRAPARTE_INEDITA +15 | sim |
| conta laranja: 10 pagadores, conta nova | facial_document ou rejected | rejected | 80 | conta_laranja | CONTA_LARANJA +60, DESTINO_NOVO +20 | sim |
| repasse rapido para conta de 3 horas | facial_document ou rejected | rejected | 90 | conta_laranja | REPASSE_RAPIDO +60, DESTINO_NOVO +30 | sim |
| coordenacao: 3 titulares, 1 aparelho | facial ou facial_document ou rejected | facial_document | 60 | coordenacao_entre_contas | COORDENACAO_ENTRE_CONTAS +40, DESTINO_NOVO +20 | sim |
| fatiamento: 4 x R$ 2.900 em 30 min | facial ou facial_document | facial | 40 | esvaziamento_fatiado | FATIAMENTO +40 | sim |
| aparelho na lista interna | facial ou facial_document ou rejected | facial | 40 | risco_contextual | REPUTACAO_INTERNA +40 | sim |
| falsa central para conta confirmada (lista interna) | rejected | rejected | 20 | risco_critico_do_recebedor | REPUTACAO_INTERNA (bloqueio), DESTINO_NOVO +20 | sim |
| conta segura no proprio CPF (fraude de cadastro) | rejected | rejected | 40 | risco_critico_do_recebedor | REPUTACAO_EXTERNA (bloqueio), DESTINO_NOVO +30, PERFIL_SEM_HISTORICO +20, MESMA_TITULARIDADE -10 | sim |
| 6 Pix com a data recuando 1 h cada | facial_document ou rejected | facial_document | 0 | data_fora_de_ordem | DATA_RETROATIVA (piso facial_document) | sim |
| aparelho sem cadastro, R$ 500 | facial ou facial_document ou rejected | facial | 20 | risco_contextual | APARELHO_NOVO +20, APARELHO_NAO_CADASTRADO (piso facial) | sim |

**Resumo**

- Legitimos aprovados sem friccao: 9 de 12
- Fraudes retidas (2FA ou rejeicao): 15 de 15
- Cenarios no resultado esperado: 27 de 27
- Latencia do motor em 77 analises: p50 45 ms, p95 49 ms (depois das correções de 18/10/2026, no ambiente local: Windows, Postgres 18 sem Docker. A medição anterior, no Docker e antes das correções, deu p50 44 ms e p95 50 ms)

Dos três legítimos que não passaram direto, nenhum foi reprovado: a transferência de R$ 3.000 para a própria conta, num cliente que só gasta pouco, pede a facial; o primeiro aluguel, 30 vezes o gasto típico do cliente, pede facial e documento; e o payload do desafio pede a facial, como o exemplo de saída do próprio documento.

## O que o motor não resolve

- **Só enxerga o que passa por ele.** Uma conta só "repassa" para o motor se aparecer primeiro como destino e depois como origem; num banco de verdade, os recebimentos viriam também do extrato. Quem recebe salário por outro banco aparece sem entradas, e dinheiro de antes da janela do `REPASSE_RAPIDO` fica fora da projeção. A atribuição FIFO é heurística: diz qual dinheiro de terceiros uma saída consumiu, não qual Pix ela devolve.
- **Aprovar é movimentar só na simulação.** A aprovação direta e o desafio confirmado contam como dinheiro que saiu, sem liquidação, SPI, DICT ou MED de verdade.
- **O histórico não é um snapshot.** As réguas congeladas cortam os eventos no início do dia, mas um Pix histórico gravado depois, com data antiga, ainda muda a amostra das próximas consultas.
- **A conta guarda o primeiro titular e a primeira abertura.** Uma correção cadastral legítima (troca de titularidade, abertura informada errada) precisaria de um fluxo próprio; hoje ela volta `409`.
- **Reputação, cadastro de CNPJ e localização de IP são mocks.** O mock de reputação segue o formato do `destination_statistics` da QI, e as faixas de IP são faixas de documentação com lugares fictícios. Em produção, a mesma tabela `ip_range_location` receberia uma base real (por exemplo a DB-IP City Lite, CC BY 4.0), sem mudar o motor. O CNAE do `TICKET_DO_RECEBEDOR` vem de um mock com dois CNPJs fictícios (uma doceria e uma concessionária); em produção, dos dados abertos do CNPJ da Receita, pelo documento que o DICT devolve, e os tetos de tíquete por atividade sairiam de dados reais de liquidação.
- **O limite que o cliente escolhe é da plataforma (BaaS).** O motor não o aplica, não recusa Pix acima dele e não guarda os pedidos de mudança. O roteiro de pedir aumento e esvaziar a conta fica com quem aplica o limite e com as regras de ritmo e de acesso.
- **A verificação é pedida, não executada.** O motor diz `facial` ou `facial_document`; o app executa e devolve o resultado pelo `PATCH`.
- **O calendário é enxuto:** dia do mês com tolerância, sem dia útil nem feriado.
- **A data é de quem chama.** Até 5 minutos fora de ordem o motor confia; além disso, a `DATA_RETROATIVA` pede a verificação reforçada, mas o motor não usa o relógio do servidor para datas no passado.
- **O cadastro de aparelho é aproximado:** o contrato não o traz, então conta como cadastrado o aparelho do primeiro Pix do titular ou um aparelho confirmado numa verificação.
- **Os parâmetros são escolhas do time**, calibradas na massa sintética. Precisariam de dados reais rotulados para virar política de produção.

## Alternativas descartadas

- **O limite que o cliente escolhe, dentro do antifraude** (com `PUT /pix/account_limit` e carência de 24h para aumentar): descartado porque o limite é do BAS, o núcleo bancário, que o aplica antes de o Pix chegar ao antifraude. Duas cópias da mesma regra divergem, e o antifraude fica com o que é dele: risco. Saiu em 18/10/2026, com as regras `LIMITE_DO_CLIENTE` e `AUMENTO_PENDENTE`. Ganharia se o antifraude fosse o único lugar por onde o Pix passa antes de sair.
- **Distância de Mahalanobis e modelos treinados** (Isolation Forest, árvores): descartados porque precisam de muito mais histórico por cliente do que um hackathon tem, e porque "distância 4,2" não explica nada ao cliente nem à banca. Ganhariam com dados reais rotulados e um time de dados para calibrar. O `PERFIL` por mediana e MAD entrega a parte útil (o limite individual) com explicação.
- **Score sem eixos (só a soma):** descartado porque um sinal forte isolado reprovaria cliente legítimo. Ganharia se os sinais fossem independentes de verdade, o que não são.
- **Grafo offline num worker:** descartado porque conta laranja se monta e se esvazia em minutos, e um grafo recalculado a cada hora veria a rede depois de o dinheiro sair. As relações de até dois saltos saem por SQL, na hora. Ganharia com relações de três saltos ou mais.
- **Geolocalização obrigatória no schema:** descartada porque o contrato a marca como opcional e a banca pode mandar Pix sem ela; recusar com `400` um pedido válido quebraria o contrato. A ausência pesa como sinal.
- **Alimentar a lista interna com as rejeições do motor:** descartado porque transforma um falso positivo em vários.
- **Um ledger de créditos gravado para o repasse:** descartado porque duplicaria o estado que as análises e as confirmações já têm, e precisaria ser corrigido a cada confirmação tardia. A projeção refeita a cada Pix custa uma consulta em lote e uma varredura linear. Ganharia se a janela de uma conta chegasse a centenas de milhares de eventos.
- **Comparar cada saída sozinha com o que entrou** (a versão anterior do `REPASSE_RAPIDO`): descartado porque três saídas de R$ 1.000 escapavam, e qualquer saída para alguém que tivesse pagado a conta, nem que fosse R$ 0,01, contava como devolução.
- **`SELECT ... FOR UPDATE` nas contas:** descartado porque a chave estrangeira da análise pega `KEY SHARE` na conta do outro lado, e dois Pix cruzados fechariam um deadlock (a lição de 07/10 da fase 1). As travas consultivas não tocam em linha nenhuma.
- **Análise manual (`in_manual_analysis`, que a API da QI tem):** descartada porque o desafio diz que no Pix não cabe análise manual, e o contrato só tem três status.
- **A regra de quebra do padrão mensal (`PADRAO_MENSAL`):** retirada. Quando o valor fugia do padrão, o `PERFIL` já pontuava (ele compara com a fase do mês do calendário do cliente) e ela valia 0; sobrava um piso de facial num caso estreito, e quem faz um pagamento grande por mês nem formava padrão. O calendário continua, como referência do `PERFIL`.
- **A rede do IP nunca vista (`REDE_NOVA`):** retirada. Na família do aparelho novo e da geografia, só contava quando nenhuma delas disparava, e sozinha (+15) não mudava decisão nenhuma; rede de celular muda o tempo todo. A troca de acesso fica com o aparelho, e a rede continua servindo ao `IP_COMPARTILHADO`.

---

# Fase 1: o banco digital

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

São nove coisas de pé, e vale saber o nome de cada uma:

| Serviço | Porta | O que é |
|---|---|---|
| `api` | 3000 | conta, saldo, livro de lançamentos, extrato, transação e tarifa. **A única que altera saldo** |
| `customer-api` | 3010 | o cliente: cadastro, consulta e documento |
| `onboarding-api` | 3005 | abertura de conta em etapas, retomável, com RG e KYC |
| `onboarding-worker` | sem porta | processo separado, mesmo código: analisa KYC, vence aberturas paradas, entrega a caixa de saída |
| `webhook-worker` | sem porta | entrega aos parceiros os eventos da `webhook_outbox`, assinados, com retentativa de recuo exponencial |
| `db` | 5432 | o banco (PostgreSQL 16). Um banco só, chamado `bootcamp`, com uma seção por API |
| `redis` | 6379 | só dado pequeno e reconstruível: limites por origem e estado do circuit breaker. **Nunca saldo** |
| `localstack` | 4566 | emula o S3 para a foto do RG, sem custo de AWS |
| `mockserver` | 1080 | só nos testes, no lugar dos birôs de consulta |

Se o `redis` cair, tudo continua funcionando, só mais devagar. Se o
`localstack` cair, o envio do RG falha e a abertura fica na etapa, sem
perder o que já foi feito. Se o `webhook-worker` cair, nenhum evento se
perde: o que não foi entregue continua na tabela, com a hora da
próxima tentativa, e a entrega retoma quando ele voltar.

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

### As RFCs

| RFC | Cobre | Onde |
|---|---|---|
| **00** | o ecossistema: como as peças se encaixam, as fronteiras, o que cai se cada uma cair | `docs/rfc/00-ecossistema.md` |
| **01** | cliente | `RFC 01 - API de Cliente.md` |
| **02** | conta, livro, transação, tarifa e extrato | `docs/rfc/02-conta.md` |
| **05** | abertura de conta | `docs/rfc/05-onboarding-api.md` |
| **06** | webhooks de saída | `RFC 06 - API de Webhooks Outgoing.md` |

Comece pela **00**: ela tem o mapa e diz, na última seção, o que o desenho não resolve.

O markdown é a fonte. Para gerar o `.docx` e o
**PDF** das cinco, com os diagramas renderizados:

```bash
bash docs/rfc/gerar-pdf.sh
```

Precisa de `pandoc`, `npx`, ImageMagick e LibreOffice. Para gerar uma
só, passe o arquivo: `bash docs/rfc/gerar-pdf.sh 02-conta.md`. Os
binários gerados não vão para o git, de propósito: o markdown é que é
a fonte, e duas versões da mesma coisa viram uma desatualizada.


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
============== 356 passed, 27 skipped in 677.50s (0:11:17) ==============
```

**Os 27 que pulam, e como rodar eles também.** Dois grupos de teste
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

Aí são **383 passando e nada pulado**, que é o que o CI roda a cada
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
