from uuid import uuid4

from tests.utils import DbUtils, PayloadGenerator, RequestGenerator


def extract_keys(response: dict) -> list:
    """As chaves da pagina, na ordem em que a API devolveu."""
    sample_entity_keys = []
    for sample_entity in response["data"]:
        sample_entity_keys.append(sample_entity["sample_entity_key"])
    return sample_entity_keys


class TestSampleEntities:
    def test_get_pages(self):
        DbUtils.rollback()

        # Um payload novo por entidade, e nao o mesmo tres vezes: cada
        # cadastro precisa do proprio CPF e do proprio e-mail, senao o
        # segundo POST bate na regra de duplicidade do controller.
        for _entidade in range(3):
            payload = PayloadGenerator.create_sample_entity_payload()
            status, response = RequestGenerator.POST_sample_entity(payload)
            assert status == 201

        status, response = RequestGenerator.GET_sample_entities()
        assert status == 200
        assert len(response["data"]) == 3
        assert response["is_last_page"] is True

        status, response = RequestGenerator.GET_sample_entities({"limit": 2})
        assert status == 200
        assert len(response["data"]) == 2
        assert response["is_last_page"] is False

        status, response = RequestGenerator.GET_sample_entities({"limit": 2, "page": 1})
        assert status == 200
        assert len(response["data"]) == 1
        assert response["is_last_page"] is True

    def test_get_filtered(self):
        DbUtils.rollback()

        payload = PayloadGenerator.create_sample_entity_payload()
        status, response = RequestGenerator.POST_sample_entity(payload)
        assert status == 201

        _key1 = response["sample_entity_key"]

        for _entidade in range(2):
            payload = PayloadGenerator.create_sample_entity_payload()
            status, response = RequestGenerator.POST_sample_entity(payload)
            assert status == 201

        new_status = "success"
        payload = {"status": new_status}

        status, response = RequestGenerator.PUT_sample_entity(_key1, payload)
        assert status == 202

        status, response = RequestGenerator.GET_sample_entities({"status": "success"})
        assert status == 200
        assert len(response["data"]) == 1
        assert response["is_last_page"] is True
        assert response["data"][0]["sample_entity_key"] == _key1

        status, response = RequestGenerator.GET_sample_entities({"status": "pending"})
        assert status == 200
        assert len(response["data"]) == 2
        assert response["is_last_page"] is True

    def test_wrong_params(self):
        status, response = RequestGenerator.GET_sample_entities({"page": -3})
        assert status == 400
        assert response["code"] == "QIT000001"

        status, response = RequestGenerator.GET_sample_entities({"limit": 500})
        assert status == 400
        assert response["code"] == "QIT000001"

    def test_list_does_not_carry_the_status_trail(self):
        """A pagina traz o resumo; a historia so no GET por chave.

        Nao e economia de bytes: a trilha e uma segunda tabela, e
        monta-la item a item custa uma consulta por entidade. Medido
        com 28 entidades na pagina: 11 ms com o resumo, 45 ms com a
        trilha junto.

        Este teste e guarda de regressao — ele ja nascia verde. Troque
        o obj_to_simplified_dict por obj_to_dict no
        list_obj_to_list_dict e ele fica vermelho.
        """
        payload = PayloadGenerator.create_sample_entity_payload()
        status, response = RequestGenerator.POST_sample_entity(payload)
        assert status == 201
        created_key = response["sample_entity_key"]

        status, response = RequestGenerator.GET_sample_entities(
            {"document_number": payload["document_number"]}
        )
        assert status == 200
        assert extract_keys(response) == [created_key]
        assert "status_events" not in response["data"][0]
        assert response["data"][0]["status"] == "pending"

    def test_refuses_unknown_query_param(self):
        """Nome de parametro errado e erro, nao silencio.

        Este e o ganho menos obvio de validar a query string por
        schema. Quem escreve `?stauts=pending` com a letra trocada
        recebia 200 com a lista inteira e concluia que o filtro nao
        funciona — porque um framework so entrega o que ele declarou, e
        o que ele nao conhece ele ignora calado. O
        `additionalProperties: false` do schema devolve o engano.
        """
        status, response = RequestGenerator.GET_sample_entities({"stauts": "pending"})
        assert status == 400
        assert response["code"] == "QIT000001"

    def test_filters_by_partial_name_ignoring_case(self):
        """Nome casa por PEDACO e ignora maiuscula/minuscula.

        E o filtro que a pessoa usa quando lembra so metade do nome. Por
        isso ele nao compara igualdade: compara conteudo. A busca abaixo
        manda o sobrenome TODO EM MAIUSCULO de proposito — se o filtro
        fosse sensivel a caixa, nao acharia nada.
        """
        unique_surname = f"Zimmerman{uuid4().hex[:8]}"

        payload = PayloadGenerator.create_sample_entity_payload(name=f"Ana {unique_surname}")
        status, response = RequestGenerator.POST_sample_entity(payload)
        assert status == 201
        matching_key = response["sample_entity_key"]

        payload = PayloadGenerator.create_sample_entity_payload(name="Bruno Carvalho")
        status, response = RequestGenerator.POST_sample_entity(payload)
        assert status == 201

        status, response = RequestGenerator.GET_sample_entities({"name": unique_surname.upper()})
        assert status == 200
        assert extract_keys(response) == [matching_key]

    def test_filters_by_exact_email_and_document_number(self):
        """E-mail e CPF casam por IGUALDADE, nao por pedaco.

        A ultima busca manda so o comeco do e-mail. Se o filtro fosse
        parcial como o de nome, ela acharia o cadastro — e e exatamente
        isso que o teste proibe.
        """
        payload = PayloadGenerator.create_sample_entity_payload()
        status, response = RequestGenerator.POST_sample_entity(payload)
        assert status == 201
        created_key = response["sample_entity_key"]

        status, response = RequestGenerator.GET_sample_entities({"email": payload["email"]})
        assert status == 200
        assert extract_keys(response) == [created_key]

        status, response = RequestGenerator.GET_sample_entities(
            {"document_number": payload["document_number"]}
        )
        assert status == 200
        assert extract_keys(response) == [created_key]

        status, response = RequestGenerator.GET_sample_entities({"email": payload["email"][:10]})
        assert status == 200
        assert created_key not in extract_keys(response)

    def test_filters_by_inclusive_birthdate_range(self):
        """As duas pontas do intervalo ENTRAM no resultado.

        Os dois nascimentos do meio sao exatamente as bordas pedidas. Se
        o filtro usasse > e < no lugar de >= e <=, o resultado viria
        vazio — e esse e o erro classico que este teste existe pra pegar.

        O filtro de nome entra junto so pra limitar a busca as entidades
        deste teste: sem ele, cadastros de outras rodadas com a mesma
        data apareceriam no meio.
        """
        family_name = f"Bernoulli{uuid4().hex[:8]}"
        birthdates = ["1931-01-01", "1931-01-02", "1931-01-03", "1931-01-04"]

        created_keys = []
        for birthdate in birthdates:
            payload = PayloadGenerator.create_sample_entity_payload(
                name=family_name, birthdate=birthdate
            )
            status, response = RequestGenerator.POST_sample_entity(payload)
            assert status == 201
            created_keys.append(response["sample_entity_key"])

        status, response = RequestGenerator.GET_sample_entities(
            {"name": family_name, "birthdate_from": "1931-01-02", "birthdate_to": "1931-01-03"}
        )
        assert status == 200
        assert sorted(extract_keys(response)) == sorted([created_keys[1], created_keys[2]])

    def test_combines_filters_with_and(self):
        """Dois filtros juntos ESTREITAM o resultado, nao o alargam.

        Os dois cadastros tem o mesmo nome; so um nasceu depois do corte.
        Se os filtros fossem somados com OU, os dois voltariam.
        """
        team_name = f"Curie{uuid4().hex[:8]}"

        payload = PayloadGenerator.create_sample_entity_payload(
            name=team_name, birthdate="1940-03-01"
        )
        status, response = RequestGenerator.POST_sample_entity(payload)
        assert status == 201

        payload = PayloadGenerator.create_sample_entity_payload(
            name=team_name, birthdate="1960-03-01"
        )
        status, response = RequestGenerator.POST_sample_entity(payload)
        assert status == 201
        younger_key = response["sample_entity_key"]

        status, response = RequestGenerator.GET_sample_entities(
            {"name": team_name, "birthdate_from": "1950-01-01"}
        )
        assert status == 200
        assert extract_keys(response) == [younger_key]

    def test_lists_newest_first_and_pages_do_not_overlap(self):
        """A pagina tem ORDEM, e por isso paginar nao repete nem pula.

        Sem um ORDER BY, `limit` e `offset` respondem sobre um conjunto
        que o banco pode devolver em qualquer ordem — e "os 2 primeiros"
        seguido de "pulando 2" chega a repetir uma linha e sumir com
        outra. Nao e teoria: e o que o SQL permite quando ninguem manda
        ordenar.

        As tres entidades nascem em sequencia, entao a mais recente e a
        ultima criada.
        """
        batch_name = f"Noether{uuid4().hex[:8]}"

        created_keys = []
        for _entidade in range(3):
            payload = PayloadGenerator.create_sample_entity_payload(name=batch_name)
            status, response = RequestGenerator.POST_sample_entity(payload)
            assert status == 201
            created_keys.append(response["sample_entity_key"])

        created_keys.reverse()

        status, response = RequestGenerator.GET_sample_entities({"name": batch_name, "limit": 2})
        assert status == 200
        assert extract_keys(response) == created_keys[:2]
        assert response["is_last_page"] is False

        status, response = RequestGenerator.GET_sample_entities(
            {"name": batch_name, "limit": 2, "page": 1}
        )
        assert status == 200
        assert extract_keys(response) == created_keys[2:]
        assert response["is_last_page"] is True

    def test_refuses_inverted_birthdate_range(self):
        """Intervalo de cabeca pra baixo e erro, nao lista vazia.

        Pedir de 2000 ate 1990 nunca pode dar resultado — e quando uma
        pergunta nao tem como ser respondida, devolver zero linhas mente:
        parece que a busca rodou e nao achou ninguem. O 400 diz a verdade,
        que a pergunta e que estava errada.
        """
        status, response = RequestGenerator.GET_sample_entities(
            {"birthdate_from": "2000-01-01", "birthdate_to": "1990-01-01"}
        )
        assert status == 400
        assert response["code"] == "QIT000010"

    def test_filters_by_more_than_one_status(self):
        """O filtro de status aceita VARIOS valores, somados com OU.

        Repare que este filtro se comporta ao contrario dos outros: name
        junto com email ESTREITA a busca (os dois precisam bater), mas
        dois status ALARGAM (basta um bater). Faz sentido pensando no que
        a pessoa quer dizer: "me mostra o que deu errado E o que deu
        certo" nao e um pedido impossivel — sao dois baldes do mesmo
        campo, e uma entidade so esta num deles.
        """
        batch_name = f"Kovalevskaya{uuid4().hex[:8]}"

        created_keys = []
        for _entidade in range(3):
            payload = PayloadGenerator.create_sample_entity_payload(name=batch_name)
            status, response = RequestGenerator.POST_sample_entity(payload)
            assert status == 201
            created_keys.append(response["sample_entity_key"])

        status, response = RequestGenerator.PUT_sample_entity(
            created_keys[0], PayloadGenerator.create_new_status_payload("success")
        )
        assert status == 202

        status, response = RequestGenerator.PUT_sample_entity(
            created_keys[1], PayloadGenerator.create_new_status_payload("failed")
        )
        assert status == 202

        status, response = RequestGenerator.GET_sample_entities(
            {"name": batch_name, "status": ["success", "failed"]}
        )
        assert status == 200
        assert sorted(extract_keys(response)) == sorted([created_keys[0], created_keys[1]])

        status, response = RequestGenerator.GET_sample_entities(
            {"name": batch_name, "status": ["pending"]}
        )
        assert status == 200
        assert extract_keys(response) == [created_keys[2]]

    def test_refuses_unknown_status_filter(self):
        """Status que nao existe e erro, nao lista vazia.

        Quem recusa e o `enum` do src/schemas/get_sample_entities.json,
        o mesmo mecanismo que confere o corpo de um POST. Uma lista
        vazia mentiria aqui, dizendo que a busca rodou e nao achou
        ninguem.
        """
        status, response = RequestGenerator.GET_sample_entities({"status": ["status_que_nao_existe"]})
        assert status == 400
        assert response["code"] == "QIT000001"

        status, response = RequestGenerator.GET_sample_entities(
            {"status": ["pending", "status_que_nao_existe"]}
        )
        assert status == 400
        assert response["code"] == "QIT000001"
