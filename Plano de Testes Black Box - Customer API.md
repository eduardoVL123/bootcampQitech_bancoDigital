# Plano de Testes Black Box: customer-api (MVP Pessoa Física)

## Estratégia de Testes (Aula 3 Tarde)
A abordagem aqui é **Black Box (Caixa Preta)**. O teste sobe o contexto da aplicação (ex: `@SpringBootTest`), conecta em um banco de dados real efêmero (via `Testcontainers` com PostgreSQL) e faz requisições HTTP reais (via `MockMvc`, `WebTestClient` ou `RestAssured`). 
Nenhum `@MockBean` para classes de Repository ou Service será usado. Nós enviamos o JSON e verificamos o Status HTTP, o JSON de retorno e o estado final do banco de dados.

---

## 1. Suíte de Testes: Criação de Cliente (`POST /internal/customer`)

**Objetivo:** Garantir a criação de clientes PF, protegendo contra duplicidade de CPF e falhas de rede (idempotência).

### 🟢 Cenários de Sucesso (Caminho Feliz)

*   **CT01 - Deve criar um novo cliente PF com sucesso**
    *   **Dado** um payload válido de PF com um CPF inédito e uma `request_key` nova.
    *   **Quando** eu fizer um POST para `/internal/customer`.
    *   **Então** o status deve ser `201 Created`.
    *   **E** o corpo da resposta deve conter a `customer_key` gerada, `type` "PF" e `created_at`.
    *   **E** uma linha deve ser inserida na tabela `CUSTOMER` no banco de dados.

*   **CT02 - Deve retornar o mesmo cliente em caso de retry (Idempotência)**
    *   **Dado** que um cliente já foi criado com a `request_key` "UUID-123".
    *   **Quando** eu fizer um segundo POST enviando exatamente o mesmo payload e a mesma `request_key` "UUID-123".
    *   **Então** o status deve ser `200 OK` (não 201).
    *   **E** a resposta deve trazer a mesma `customer_key` gerada no primeiro pedido.
    *   **E** não deve haver duplicidade na tabela `CUSTOMER` (apenas 1 registro para este CPF/Chave).

### 🔴 Cenários de Falha e Validação

*   **CT03 - Deve recusar a criação se o CPF já existir em outro pedido**
    *   **Dado** que o CPF "111.111.111-11" já pertence ao cliente A (criado com `request_key` "UUID-A").
    *   **Quando** eu fizer um POST com o mesmo CPF, mas com uma `request_key` nova ("UUID-B").
    *   **Então** a constraint de unicidade do banco deve barrar.
    *   **E** o status deve ser `409 Conflict`.
    *   **E** o código de erro no JSON deve ser `CUS004009` (Document Already Exists).

*   **CT04 - Deve recusar criação com formato de CPF inválido**
    *   **Dado** um payload com `document_number` = "123" (fora do padrão de máscara ou dígito incorreto).
    *   **Quando** eu fizer um POST para `/internal/customer`.
    *   **Então** o status deve ser `400 Bad Request` ou `422 Unprocessable Entity`.
    *   **E** a lista de `errors` deve indicar falha no campo `document_number`.

*   **CT05 - Deve recusar cadastro de cliente menor de idade**
    *   **Dado** um payload com `birth_date` calculando menos de 18 anos na data atual.
    *   **Quando** eu fizer um POST para `/internal/customer`.
    *   **Então** o status deve ser `400 Bad Request`.
    *   **E** a lista de `errors` deve indicar a regra de idade mínima.

*   **CT06 - Deve recusar payload sem campos obrigatórios**
    *   **Dado** um payload vazio `{}` ou faltando `name`.
    *   **Quando** eu fizer um POST para `/internal/customer`.
    *   **Então** o status deve ser `400 Bad Request` listando os campos faltantes.

---

## 2. Suíte de Testes: Consulta de Cliente (`GET /customer/{customer_key}`)

**Objetivo:** Validar a leitura dos dados cadastrais com isolamento de acesso.

### 🟢 Cenários de Sucesso
*   **CT07 - Deve retornar os dados do cliente com sucesso**
    *   **Dado** um cliente existente no banco com a chave "UUID-CUST-1".
    *   **Quando** eu fizer um GET para `/customer/UUID-CUST-1` passando o token JWT válido deste usuário.
    *   **Então** o status deve ser `200 OK`.
    *   **E** o corpo da resposta deve omitir dados estritamente internos (como a `request_key` ou a `PK` do banco), mostrando apenas o contrato DTO esperado.

### 🔴 Cenários de Falha
*   **CT08 - Deve retornar 404 para cliente inexistente**
    *   **Dado** uma `customer_key` que não existe no banco de dados.
    *   **Quando** eu fizer um GET para `/customer/{chave_invalida}`.
    *   **Então** o status deve ser `404 Not Found`.

---

## 3. Suíte de Testes: Metadados do Documento (`POST /internal/customer/{customer_key}/document`)

**Objetivo:** Garantir que o banco registre corretamente a foto enviada para o S3, sem permitir envios duplicados para o mesmo lado do documento.

### 🟢 Cenários de Sucesso
*   **CT09 - Deve salvar a referência do RG com sucesso**
    *   **Dado** um cliente existente.
    *   **Quando** eu fizer um POST informando `document_type`: "RG", `side`: "FRONT" e a `object_key` do S3.
    *   **Então** o status deve ser `201 Created`.
    *   **E** o registro deve ser inserido na tabela `CUSTOMER_DOCUMENT`.

### 🔴 Cenários de Falha
*   **CT10 - Deve impedir duplo envio do mesmo lado do RG (Unique Constraint)**
    *   **Dado** que o cliente já possui um RG lado "FRONT" salvo.
    *   **Quando** eu fizer um POST tentando salvar um novo RG "FRONT" para a mesma `customer_key`.
    *   **Então** o banco deve rejeitar por violação de índice (`UNIQUE(customer_id, document_type, side)`).
    *   **E** o status deve ser `409 Conflict`.

*   **CT11 - Deve recusar vínculo de documento para cliente inexistente**
    *   **Dado** uma `customer_key` inválida.
    *   **Quando** eu enviar o payload do documento.
    *   **Então** o banco deve rejeitar pela `Foreign Key`.
    *   **E** o status deve ser `404 Not Found`.

---

## 💡 Dicas para a Implementação dos Testes no Código

Ao abrir a sua IDE para codar estes testes, a estrutura mental (e de código) que você deve seguir para o **CT01** e **CT02**, por exemplo, usando JUnit 5 e MockMvc, seria parecida com isto:

```java
// Exemplo de mentalidade Black Box para o Teste de Idempotência
@Test
@DisplayName("CT02 - Deve retornar 200 OK com os mesmos dados ao enviar a mesma request_key (Idempotência)")
void shouldReturn200OnIdempotentReplay() throws Exception {
    // 1. ARRANGE (Prepara o payload)
    String payload = """
        {
          "request_key": "123e4567-e89b-12d3-a456-426614174000",
          "type": "PF",
          "name": "Maria da Silva",
          "document_number": "111.222.333-44",
          "birth_date": "1990-01-01"
        }
        """;

    // 2. ACT (Faz o primeiro request - Criação)
    ResultActions firstRequest = mockMvc.perform(post("/internal/customer")
            .contentType(MediaType.APPLICATION_JSON)
            .content(payload));
            
    // 3. ASSERT (Verifica a criação 201)
    firstRequest.andExpect(status().isCreated())
                .andExpect(jsonPath("$.customer_key").exists());

    // 4. ACT (Faz o segundo request idêntico - Replay da rede)
    ResultActions secondRequest = mockMvc.perform(post("/internal/customer")
            .contentType(MediaType.APPLICATION_JSON)
            .content(payload));

    // 5. ASSERT (Verifica o comportamento idempotente 200 OK)
    secondRequest.andExpect(status().isOk()) // Não é 201 de novo!
                 .andExpect(jsonPath("$.name").value("Maria da Silva"));
                 
    // Verifica no banco de dados real (via Repository de teste) se existe APENAS UM registro
    long count = customerRepository.countByDocumentNumber("111.222.333-44");
    assertThat(count).isEqualTo(1);
}
```