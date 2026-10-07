# Plano de Testes Black Box - Webhook API (Outgoing)

Este documento descreve os cenários de testes end-to-end (Black Box) para a `webhook-api`. Esses testes verificarão o processamento interno de notificações de saída, a entrega à internet e os mecanismos de resiliência (retries), operando de fora para dentro.

## 1. Escopo e Objetivos
- Garantir que a API consiga ler da tabela `webhook_outbox` corretamente (integração entre Outbox e Envio).
- Assegurar a lógica de **Exponential Backoff Retries** quando um endpoint externo estiver instável.
- Garantir que os eventos entregues não sejam reenviados (Idempotência/Garantia de Entrega).
- Garantir a assinatura criptográfica (`HMAC`) de todas as requisições de saída por motivos de segurança.

---

## 2. Casos de Teste (Cenários Base)

### 2.1. O Caminho Feliz (Happy Path)
> Garante que um evento gravado na nossa fila sai pelo cano corretamente.

* **Cenário A:** Envio com sucesso de primeira.
  * *Ação:* Inserimos diretamente no banco (ou via mock do core) um registro de `transaction.success` no `webhook_outbox`. Um servidor de destino externo (Mock) é configurado para retornar `HTTP 200 OK`.
  * *Espectativa:* A `webhook-api` processa o registro, envia uma requisição `POST` ao Mock, o Mock recebe os dados exatos (junto com os headers corretos), e o status do webhook no nosso banco de dados passa de `PENDING` para `DELIVERED`.

### 2.2. Segurança Criptográfica (Assinatura HMAC)
* **Cenário A:** O Header `X-Banco-Signature` é gerado corretamente.
  * *Ação:* Inserimos um evento no outbox. O Mock externo inspeciona a requisição recebida.
  * *Espectativa:* O cabeçalho `X-Banco-Signature` deve estar presente. Ao processar a função HMAC-SHA256 do corpo do JSON recebido no Mock com a secret-key do teste, o valor gerado localmente pelo Mock deve bater milimetricamente com o Header fornecido.

### 2.3. Resiliência: O Teste do Exponential Backoff
> Este é o teste central para provarmos o diferencial do uso do Redis como gerenciador de filas e retentativas.

* **Cenário A:** O servidor do cliente cai temporariamente (Retentativa).
  * *Ação:* O servidor Mock é configurado para retornar `HTTP 500 Internal Server Error` na **primeira** requisição de um webhook, mas retornar `HTTP 200 OK` na **segunda**.
  * *Espectativa:* A API envia a primeira, toma o 500, e altera o status do evento para algo como `QUEUED_FOR_RETRY`. A API respeita o tempo estipulado do Backoff Exponencial, faz a segunda tentativa, recebe o 200 OK e, por fim, marca como `DELIVERED`. A API *não* pode descartar o evento no primeiro erro.

* **Cenário B:** O cliente desapareceu (Max Retries Excedido).
  * *Ação:* O servidor Mock retorna ininterruptamente `HTTP 500`.
  * *Espectativa:* A API tenta enviar N vezes (respeitando o limite máximo definido, por exemplo, 5). Após a última tentativa esgotada, o status do evento é consolidado como `FAILED` (ou enviado para uma Dead Letter Queue). Ele deve parar de tentar eternamente.

* **Cenário C:** Timeout (O cliente demora demais a responder).
  * *Ação:* O servidor Mock segura a resposta do HTTP por mais tempo que o Timeout máximo configurado da nossa `webhook-api` (ex: mais de 10 segundos).
  * *Espectativa:* O Worker não fica travado infinitamente aguardando. A conexão aborta por timeout, o evento é classificado como falha técnica temporária e segue para o fluxo de Retry (Cenário A).

---

## 3. Infraestrutura de Teste
- **Setup:** A `webhook-api` e uma instância do `Redis` subirão via `docker-compose`.
- **Servidor Mock de Destino:** O pytest subirá um pequeno servidor HTTP de mentira (ex: com a biblioteca `responses` ou `FastAPI` em background) para atuar como o "cliente que recebe o webhook". Nele configuraremos se ele deve responder `200`, `500` ou demorar.
- **Inserção Direta:** Durante os testes Black Box desta API específica, os eventos podem ser inseridos de forma bruta (`SQL INSERT`) na tabela de outbox, isolando o teste do sistema de Webhooks da necessidade de simular toda uma esteira de onboarding ou transação.
