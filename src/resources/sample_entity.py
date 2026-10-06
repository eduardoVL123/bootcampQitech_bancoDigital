from fastapi import Request, Response
from fastapi import status as http_status
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse

from controllers import SampleEntityController
from utils.schema_handler import SchemaHandler

DEFAULT_LIMIT = 10
DEFAULT_PAGE = 0


class SampleEntityResource:
    """A porta de entrada HTTP da Sample Entity.

    ────────────────────────────────────────────────────────────────
    O QUE UM RESOURCE FAZ — E O QUE ELE NÃO FAZ
    ────────────────────────────────────────────────────────────────
    Ele faz três coisas, nesta ordem, e nada além disso:

      1. confere o corpo da requisição (o decorator do schema);
      2. chama o controller;
      3. devolve o que o controller respondeu.

    Repare no que NÃO está aqui: nenhuma regra de negócio, nenhum
    `if` sobre o estado da entidade, nenhuma linha de SQL. Um método
    daqui cabe em três linhas, e quando não couber é sinal de que uma
    regra vazou da camada de baixo pra cá.

    ────────────────────────────────────────────────────────────────
    POR QUE OS MÉTODOS SE CHAMAM `on_post`, `on_get_by_key`...
    ────────────────────────────────────────────────────────────────
    Porque é assim nos serviços da QI Tech, e a semelhança é de
    propósito — você vai abrir um deles na segunda-feira e encontrar
    exatamente estes nomes.

    Vale saber a diferença, porque ela é boa: lá o framework é o
    Falcon, que DESCOBRE o método pelo nome — chegou um POST, ele
    procura um `on_post`. Aqui o FastAPI não faz isso; quem liga o
    endereço ao método é o `src/app.py`, uma linha por rota, à vista.
    O nome é uma escolha nossa, e escolhemos o que o time já lê.

    ────────────────────────────────────────────────────────────────
    UMA REGRA QUE O CÓDIGO NÃO CONSEGUE COBRAR SOZINHO
    ────────────────────────────────────────────────────────────────
    O `src/app.py` cria UM resource e ele vive enquanto a API estiver
    no ar — não nasce um por requisição. Repare que não existe
    `__init__` aqui, e que nenhum método escreve `self.alguma_coisa`:
    isso é de propósito.

    No dia em que um método guardar algo no `self`, esse algo passa a
    ser compartilhado por TODAS as requisições ao mesmo tempo — e o
    sintoma é uma resposta levando o dado de outra pessoa, sob carga,
    sem erro nenhum no log. O que é de uma requisição fica no
    contexto dela (veja o `get_context` em src/database.py); o que
    fica aqui é de todo mundo.

    ────────────────────────────────────────────────────────────────
    O STATUS DA RESPOSTA É DECIDIDO AQUI
    ────────────────────────────────────────────────────────────────
    201 pra criação, 202 pra "recebi e vou fazer", 204 pra "pronto e
    não tenho nada a dizer", 200 pro resto. Todos saem destes métodos,
    e é por isso que eles devolvem um `JSONResponse` em vez de um
    dicionário solto: o dicionário sozinho não sabe dizer com que
    status ele quer sair, e o FastAPI, sem essa informação, responde
    200 pra tudo.

    É o mesmo desenho dos serviços da QI. No Falcon o resource escreve
    `resp.status = falcon.code_to_http_status(201)` na última linha;
    aqui ele devolve a resposta já com o número dentro. Muda a
    escrita, não o dono.

    O `src/app.py` fica só com a tabela de endereços — ele diz QUEM
    atende cada rota, nunca COMO a resposta sai. Um lugar, uma
    decisão: se a resposta do POST deixar de ser 201 um dia, este
    arquivo é o único que muda.

    ────────────────────────────────────────────────────────────────
    POR QUE O `jsonable_encoder`
    ────────────────────────────────────────────────────────────────
    Quando a rota devolve um dicionário, o FastAPI passa esse
    dicionário por um tradutor antes de virar JSON — é ele que sabe
    transformar uma data, um Decimal ou um UUID em texto. Devolvendo
    o `JSONResponse` na mão, esse passo não acontece sozinho: sem a
    chamada, o dia em que alguém acrescentar uma data no DTO a
    resposta estoura em runtime, e só naquele endpoint.
    """

    @SchemaHandler.validate("post_sample_entity.json")
    def on_post(self, payload: dict) -> JSONResponse:
        # Se o código chegou até aqui, o payload JÁ foi conferido contra
        # o src/schemas/post_sample_entity.json. O resource não checa
        # nada: ele só chama a regra de negócio.
        controller = SampleEntityController()
        sample_entity = controller.create(payload)

        return JSONResponse(
            content=jsonable_encoder(sample_entity),
            status_code=http_status.HTTP_201_CREATED,
        )

    def on_get_by_key(self, sample_entity_key: str) -> JSONResponse:
        controller = SampleEntityController()
        sample_entity = controller.get_by_key(sample_entity_key)

        return JSONResponse(
            content=jsonable_encoder(sample_entity),
            status_code=http_status.HTTP_200_OK,
        )

    @SchemaHandler.validate("put_sample_entity.json")
    def on_put_by_key(self, sample_entity_key: str, payload: dict) -> JSONResponse:
        controller = SampleEntityController()
        sample_entity = controller.update_status(sample_entity_key, payload["status"])

        return JSONResponse(
            content=jsonable_encoder(sample_entity),
            status_code=http_status.HTTP_202_ACCEPTED,
        )

    def on_put_increment_counter(self, sample_entity_key: str) -> Response:
        controller = SampleEntityController()
        controller.webhook_increment_counter(sample_entity_key)
        return Response(status_code=http_status.HTTP_204_NO_CONTENT)

    @SchemaHandler.validate_query_params("get_sample_entities.json")
    def on_get_list(self, request: Request) -> JSONResponse:
        """A pagina pedida, com os filtros que vierem na query string.

        O decorator ja conferiu tudo contra o
        src/schemas/get_sample_entities.json antes desta primeira linha
        rodar — mesmo mecanismo que confere o corpo do POST, mesmo tipo
        de arquivo. Por isso os `int()` abaixo nao tem try: o schema
        garantiu que so chega digito.

        A conversao de DATA nao acontece aqui. O schema garante o
        formato (quatro digitos, traco, dois, traco, dois), mas nao sabe
        que fevereiro nao tem dia 30 — e quem recusa valor impossivel e
        o controller, nao o resource.
        """
        controller = SampleEntityController()

        query_params = request.query_params

        limit = int(query_params.get("limit", DEFAULT_LIMIT))
        page = int(query_params.get("page", DEFAULT_PAGE))

        # Os filtros viajam juntos num dicionario em vez de seis
        # argumentos soltos: cada filtro novo passa a custar uma linha
        # aqui, e nenhuma assinatura nova nas camadas de baixo.
        filters = {
            "status_enumerators": query_params.getlist("status"),
            "name": query_params.get("name"),
            "email": query_params.get("email"),
            "document_number": query_params.get("document_number"),
            "birthdate_from": query_params.get("birthdate_from"),
            "birthdate_to": query_params.get("birthdate_to"),
        }

        offset = page * limit
        sample_entities_page = controller.get_list(limit, offset, filters)

        # A paginação é assunto do endereço (?limit=&page=), não da
        # entidade: por isso quem monta o envelope da página é o
        # resource, e não o DTO.
        #
        # É a exceção ao "um método daqui cabe em três linhas", e é
        # deliberada: o envelope fala de limit e page, que são
        # vocabulário de HTTP. Empurrá-lo pro controller obrigaria a
        # regra de negócio a saber o que é uma página.
        page_envelope = {
            "data": sample_entities_page["sample_entities_list_dto"],
            "limit": limit,
            "page": page,
            "is_last_page": sample_entities_page["is_last_page"],
        }

        return JSONResponse(
            content=jsonable_encoder(page_envelope),
            status_code=http_status.HTTP_200_OK,
        )
