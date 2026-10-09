# Plano de testes: webhook de saída (RFC 06)

## O que esta fatia resolve

A RFC 06 descreve o sistema no presente, como se ele operasse: *"a `webhook-api` lê a tabela e manda"*, *"o worker lê a fila, assina e envia"*. Hoje **nada disso acontece num `docker compose up`**. Provado assim: com o sistema de pé, criei cliente, abri conta, depositei, transferi e bloqueei uma conta, tudo com sucesso, e a `webhook_outbox` terminou com **zero eventos**.

O desenho está certo e o código do worker faz o que diz. O que falta é ligá-lo nas pontas:

| Peça | Hoje | Depois desta fatia |
|---|---|---|
| Quem grava o evento | ninguém chama `publish_webhook` fora dos testes dele | o `transaction_controller`, no **mesmo `COMMIT`** da transação |
| Quem entrega | nada: sem `Dockerfile`, sem serviço no compose, sem laço | o serviço `webhook-worker`, igual ao `onboarding-worker` |
| Quando tenta de novo | a RFC promete 1, 2, 4 e 8 minutos; o código não tem coluna de prazo e reenvia na varredura seguinte | coluna `next_attempt_at`, e o recuo é de verdade |
| O que conta como entregue | **só `200`** | qualquer `2xx` |
| Como o parceiro descarta repetição | não dá: o evento não tem identificador próprio | `event_id` único, no corpo e no cabeçalho |
| Onde mora o segredo do parceiro | numa coluna, em texto puro, copiado em cada evento | variável de ambiente, nunca no banco |

## Três decisões, e o preço de cada uma

**Um parceiro só, configurado por ambiente.** `WEBHOOK_TARGET_URL` e `WEBHOOK_SECRET`. O certo, num banco de verdade, é uma tabela de assinaturas: cada parceiro com a própria URL, o próprio segredo e a própria lista de eventos. **Descartada por escopo**, e registrada aqui: ganharia no dia em que existir mais de um parceiro, que é o primeiro dia de produção. O que esta fatia **resolve de verdade** é o segredo sair do banco: ele era uma coluna em texto puro, copiada em cada linha da fila.

**O recuo é configurável, e o compose usa 2 segundos.** `WEBHOOK_RETRY_BASE_SECONDS` vale 2 no ambiente local e seria 60 em produção. Sem isso, um teste de retentativa levaria um minuto para provar a segunda tentativa, e ninguém rodaria. O valor está no `docker-compose.yml`, visível, e não escondido no código.

**Entrega ao menos uma vez, e não exatamente uma vez.** Se o parceiro responder e o nosso `COMMIT` falhar logo depois, o evento é reenviado. É por isso que o `event_id` existe: **quem recebe descarta a repetição**. Prometer "exatamente uma vez" na entrega por HTTP seria mentira, e a RFC passa a dizer isso.

## Casos de teste

Todos pela porta da frente: o parceiro é o **Mockserver**, que já está no compose, e o teste confere o que ele recebeu. Nenhum lê o banco, nenhum importa código da aplicação (R1).

| # | Teste | Espera |
|---|---|---|
| W-01 | `test_transferencia_entrega_o_evento_ao_parceiro` | o parceiro recebe um `POST` com `event_type` `transaction.success` e a `transaction_key` da transferência |
| W-02 | `test_o_evento_vai_assinado` | o cabeçalho `X-Banco-Signature` bate com o HMAC-SHA256 do corpo, calculado pelo teste com o mesmo segredo |
| W-03 | `test_evento_traz_identificador_proprio` | `event_id` no corpo e no cabeçalho `X-Banco-Event-Id`, e é um UUID |
| W-04 | `test_parceiro_que_responde_202_nao_recebe_de_novo` | **o bug de hoje**: `202` é sucesso, e o evento não é reenviado |
| W-05 | `test_parceiro_fora_do_ar_recebe_depois` | a primeira tentativa cai, a segunda entrega, e o parceiro recebe **duas** vezes no total |
| W-06 | `test_transacao_recusada_nao_gera_evento` | transferência sem saldo responde `409` e o parceiro **não** recebe nada. É o Outbox provado pela porta da frente: sem `COMMIT`, sem evento |
| W-07 | `test_deposito_tambem_avisa` | depósito gera `transaction.success` |

## Resultado

Os sete casos do plano foram escritos antes do código e **todos falharam**, com o parceiro recebendo zero requisições. Depois do código, com mais um caso que nasceu no meio do caminho: **8 de 8**.

| Mutação | O que aconteceu |
|---|---|
| só `200` conta como sucesso (o bug de hoje) | o W-04 falhou: o parceiro que respondeu `202` recebeu o mesmo evento de novo |
| tirei a assinatura do cabeçalho | **duas** falharam, o W-02 e o W-05 |
| tirei o recuo, reenviando na varredura seguinte | **duas** falharam: sem recuo o parceiro leva cinco marteladas em cinco segundos |
| publiquei o evento **depois** do `COMMIT`, fora do Outbox | o W-06 falhou: o parceiro foi avisado de uma transferência recusada |
| tirei o limite de tentativas | o W-08 falhou: continuou tentando para sempre |

Nenhuma sobreviveu.

### Dois erros meus no caminho, e os dois eram do teste

**1. O depósito da preparação também gera evento.** O W-05 programava uma queda de conexão e esperava que ela pegasse a transferência. Pegava o **depósito de abertura da conta**, que é uma transação como outra qualquer e chega antes. O teste via uma entrega em vez de duas e acusava o código. A correção foi esperar a fila da preparação esvaziar e limpar a rota antes de programar a falha.

**2. O Mockserver não morre entre uma rodada e outra.** O W-08 registra uma queda de conexão para 99 vezes, com prioridade alta, e isso **sobrevive ao fim do `pytest`**: na rodada seguinte, o W-04 levava a queda deixada pelo teste anterior e falhava sem ter nada a ver com o assunto. Só apareceu porque rodei a suíte duas vezes seguidas depois de restaurar os mutantes. A correção é uma fixture que limpa a rota do parceiro antes de cada teste: **cada teste cria o próprio mundo**, inclusive no que está fora dele.

A limpeza é só na rota `/parceiro/webhook`. Um `reset` geral apagaria as respostas que os testes da onboarding programam, e quebraria os testes do Carlos.

## O que esta fatia não resolve

- **Um parceiro só**, configurado por ambiente. A tabela de assinaturas, com URL, segredo e lista de eventos por parceiro, continua fora do escopo.
- **A entrada da webhook-api não existe.** O worker da onboarding entrega os eventos dele por HTTP para `WEBHOOK_API_URL`, que no compose aponta para o Mockserver. Juntar as duas metades, uma rota `POST /internal/event` que grava na mesma `webhook_outbox`, é o próximo passo natural e não foi feito.
- **Só `transaction.success` é publicado.** `account.blocked`, `account.closed` e os outros eventos da RFC 06 ainda não têm quem os publique.
