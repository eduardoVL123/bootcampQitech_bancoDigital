from datetime import date

from tests.utils import PayloadGenerator, RandomGenerator, RequestGenerator


def birthdate_for_age(age_in_years: int) -> str:
    """A data de nascimento de quem faz essa idade hoje.

    O recuo de 1 dia existe por causa do 29 de fevereiro: nascido em
    29/02, a data não existe no ano-alvo e o `date()` levanta
    ValueError — a suíte ficaria vermelha um dia a cada quatro anos.
    """
    today = date.today()

    if today.month == 2 and today.day == 29:
        return date(today.year - age_in_years, 2, 28).isoformat()

    return date(today.year - age_in_years, today.month, today.day).isoformat()


class TestSampleEntityCreate:
    def test_refuses_empty_body(self):
        payload = {}
        status, response = RequestGenerator.POST_sample_entity(payload)
        assert status == 400
        assert response["code"] == "QIT000001"

    def test_schema_refuses_unknown_field(self):
        """Campo que o schema nao pediu e erro, nao um campo ignorado.

        Quem escreve `{"hllo": "mundo"}` com erro de digitacao prefere
        receber um 400 agora a descobrir amanha que o campo nunca chegou.
        Quem garante isso e o "additionalProperties": false do
        src/schemas/post_sample_entity.json.
        """
        payload = PayloadGenerator.create_sample_entity_payload()
        payload["campo_que_nao_existe"] = 1

        status, response = RequestGenerator.POST_sample_entity(payload)
        assert status == 400
        assert response["code"] == "QIT000001"

    def test_schema_refuses_malformed_person_fields(self):
        """Cada campo de pessoa tem um formato, e o schema cobra os tres.

        Estao juntos num teste so porque sao a MESMA regra vista tres
        vezes: um `pattern` no src/schemas/post_sample_entity.json. Cada
        volta do laco derruba um deles e mantem os outros certos — assim,
        quando este teste ficar vermelho, a mensagem diz qual formato
        parou de ser cobrado.

        O `pattern` nao e frescura: o `format` do JSON Schema ("email",
        "date") NAO valida nada na biblioteca que este projeto usa. Ele e
        so uma anotacao. Escrever "format": "email" e achar que esta
        protegido e o erro que este teste existe pra impedir.
        """
        campos_tortos = [
            ("email", "isto-nao-e-um-email"),
            ("document_number", "12345678901"),
            ("birthdate", "17/05/1990"),
        ]

        for campo, valor_torto in campos_tortos:
            payload = PayloadGenerator.create_sample_entity_payload()
            payload[campo] = valor_torto

            status, response = RequestGenerator.POST_sample_entity(payload)

            assert status == 400, f"o campo '{campo}' aceitou o valor '{valor_torto}'"
            assert response["code"] == "QIT000001"

    def test_creates_entity_in_pending(self):
        document_number = RandomGenerator.generate_cpf()
        payload = PayloadGenerator.create_sample_entity_payload()
        payload["document_number"] = document_number

        status, response = RequestGenerator.POST_sample_entity(payload)
        assert status == 201

        _key = response["sample_entity_key"]

        status, response = RequestGenerator.GET_sample_entity(_key)
        assert status == 200
        assert response["sample_entity_key"] == _key
        assert response["status"] == "pending"
        assert response["hello"] == payload["hello"]
        assert response["name"] == payload["name"]
        assert response["email"] == payload["email"]
        assert response["document_number"] == document_number
        assert response["birthdate"] == payload["birthdate"]
        assert response["counter"] == 0
        assert len(response["status_events"]) == 1
        assert response["status_events"][0]["status"] == "pending"

    def test_refuses_impossible_birthdate(self):
        """Formato certo, data inexistente: 422, nunca 500.

        O `pattern` do schema conta dígitos; ele não sabe que fevereiro
        não tem dia 30. Estas duas datas passam pelo regex inteiras, e
        quem as recusa é o controller.
        """
        for impossible_birthdate in ["9999-99-99", "2025-02-30"]:
            payload = PayloadGenerator.create_sample_entity_payload()
            payload["birthdate"] = impossible_birthdate

            status, response = RequestGenerator.POST_sample_entity(payload)
            assert status == 422
            assert response["code"] == "QIT001007"

    def test_refuses_invalid_document_number(self):
        """CPF com a mascara certa e os digitos errados nao passa.

        O schema ja cobrou o FORMATO (tres pontos, um hifen, onze
        digitos). Esta regra e outra: os dois ultimos digitos sao uma
        conta feita sobre os nove primeiros, e um numero que erra essa
        conta nao existe como CPF. Formato certo e valor impossivel — por
        isso a resposta e 422, e nao 400.
        """
        payload = PayloadGenerator.create_sample_entity_payload()
        payload["document_number"] = "111.222.333-44"

        status, response = RequestGenerator.POST_sample_entity(payload)

        assert status == 422
        assert response["code"] == "QIT001003"

    def test_refuses_duplicated_document_number(self):
        primeira = PayloadGenerator.create_sample_entity_payload()
        status, _response = RequestGenerator.POST_sample_entity(primeira)
        assert status == 201

        segunda = PayloadGenerator.create_sample_entity_payload()
        segunda["document_number"] = primeira["document_number"]

        status, response = RequestGenerator.POST_sample_entity(segunda)

        assert status == 409
        assert response["code"] == "QIT001004"

    def test_refuses_duplicated_email(self):
        primeira = PayloadGenerator.create_sample_entity_payload()
        status, _response = RequestGenerator.POST_sample_entity(primeira)
        assert status == 201

        segunda = PayloadGenerator.create_sample_entity_payload()
        segunda["email"] = primeira["email"]

        status, response = RequestGenerator.POST_sample_entity(segunda)

        assert status == 409
        assert response["code"] == "QIT001005"

    def test_refuses_underage(self):
        payload = PayloadGenerator.create_sample_entity_payload()
        payload["birthdate"] = birthdate_for_age(17)

        status, response = RequestGenerator.POST_sample_entity(payload)

        assert status == 422
        assert response["code"] == "QIT001006"

    def test_over_eighty_is_created_as_failed(self):
        """Passar de oitenta nao e erro: e outro desfecho.

        Repare na diferenca em relacao aos testes acima. Menor de idade
        recebe 422 e NAO vira entidade nenhuma; quem passa de oitenta e
        criado normalmente, com 201, e nasce em 'failed' em vez de
        'pending'. Uma regra recusa o pedido, a outra decide o estado —
        e sao coisas diferentes.
        """
        payload = PayloadGenerator.create_sample_entity_payload()
        payload["birthdate"] = birthdate_for_age(81)

        status, response = RequestGenerator.POST_sample_entity(payload)
        assert status == 201

        _key = response["sample_entity_key"]

        status, response = RequestGenerator.GET_sample_entity(_key)
        assert status == 200
        assert response["status"] == "failed"
