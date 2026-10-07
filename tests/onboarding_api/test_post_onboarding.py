"""F1: POST /onboarding, cadastro e começo da abertura (docs/testes/onboarding-api.md)."""
from datetime import datetime, timedelta, timezone
from uuid import UUID

import jwt
import pytest

from tests.utils.onboarding_api import (
    PRAZO_DA_ABERTURA_MINUTOS,
    VALIDADE_DA_CREDENCIAL_SEGUNDOS,
    Onboarding,
    amanha,
    ao_mesmo_tempo,
    cabecalhos_do_gateway,
    campos_e_regras,
    com_digito_errado,
    hoje,
    le_credencial,
    nascido_para_completar_amanha,
    nascido_para_completar_hoje,
    nova_chave,
    novo_cnpj,
    novo_cpf,
    pessoa_fisica,
    pessoa_juridica,
    sem,
    so_digitos,
)


CAMPOS_DA_RESPOSTA = {"onboarding_key", "customer_key", "status", "expires_at", "access_token", "next_step"}

OBRIGATORIOS_DOS_DOIS_TIPOS = ["type", "name", "document_number", "declared_monthly_income_cents", "pep_self_declared"]

# Teto da renda declarada no schema: R$ 100 bilhões por mês, em centavos.
RENDA_MAXIMA_CENTAVOS = 10_000_000_000_000


def e_uuid(valor: str) -> bool:
    try:
        return str(UUID(valor)) == valor
    except ValueError:
        return False


class TestCadastroCaminhoFeliz:
    def test_pf_valida_cadastra_e_comeca_abertura_em_draft(self):
        """F1-01. Dados certos: nasce o cliente e a abertura em DRAFT, que vence em 20 minutos."""
        # age
        resposta = Onboarding.cadastra(pessoa_fisica())

        # confere
        assert resposta.status_code == 201
        corpo = resposta.json()
        assert e_uuid(corpo["onboarding_key"])
        assert e_uuid(corpo["customer_key"])
        assert corpo["status"] == "DRAFT"
        assert corpo["next_step"] == "SEND_DOCUMENT"

        vencimento_esperado = datetime.now(timezone.utc) + timedelta(minutes=PRAZO_DA_ABERTURA_MINUTOS)
        vencimento = datetime.fromisoformat(corpo["expires_at"])
        assert abs((vencimento - vencimento_esperado).total_seconds()) < 60

    def test_pj_valida_cadastra_e_comeca_abertura_em_draft(self):
        """F1-02. O mesmo para empresa, com CNPJ e data de abertura."""
        # age
        resposta = Onboarding.cadastra(pessoa_juridica())

        # confere
        assert resposta.status_code == 201
        assert resposta.json()["status"] == "DRAFT"

    def test_resposta_traz_so_os_campos_do_contrato(self):
        """F1-03. Nenhum id interno (R5) e nenhum dado pessoal volta na resposta."""
        # age
        resposta = Onboarding.cadastra(pessoa_fisica())

        # confere
        assert resposta.status_code == 201
        assert set(resposta.json()) == CAMPOS_DA_RESPOSTA

    def test_credencial_e_um_jwt_hs256_do_cliente(self):
        """F1-04. A credencial é um JWT assinado com HS256, do próprio cliente,
        com escopo onboarding, que vale 1 hora e não carrega dado pessoal."""
        # age
        corpo = Onboarding.cadastra(pessoa_fisica()).json()

        # confere: a assinatura bate com o segredo e os campos são só estes cinco
        assert jwt.get_unverified_header(corpo["access_token"])["alg"] == "HS256"
        campos = le_credencial(corpo["access_token"])
        assert set(campos) == {"sub", "scope", "iat", "exp", "jti"}
        assert campos["sub"] == corpo["customer_key"]
        assert campos["scope"] == "onboarding"
        assert campos["exp"] - campos["iat"] == VALIDADE_DA_CREDENCIAL_SEGUNDOS
        assert e_uuid(campos["jti"])

    def test_aceita_pf_que_completa_18_anos_hoje(self):
        """F1-05. Borda da idade, o lado que passa: 18 anos completos hoje."""
        # age
        resposta = Onboarding.cadastra(pessoa_fisica(birth_date=nascido_para_completar_hoje(18)))

        # confere
        assert resposta.status_code == 201

    def test_aceita_pj_aberta_hoje(self):
        """F1-06. Borda da data no futuro, o lado que passa: empresa aberta hoje."""
        # age
        resposta = Onboarding.cadastra(pessoa_juridica(opening_date=hoje().isoformat()))

        # confere
        assert resposta.status_code == 201

    def test_aceita_renda_zero(self):
        """F1-07. Borda do mínimo, o lado que passa: renda zero é permitida."""
        # age
        resposta = Onboarding.cadastra(pessoa_fisica(declared_monthly_income_cents=0))

        # confere
        assert resposta.status_code == 201


class TestCampoObrigatorioAusente:
    @pytest.mark.parametrize(
        "dados_validos, campo_ausente",
        [pytest.param(pessoa_fisica, campo, id=f"PF sem {campo}") for campo in OBRIGATORIOS_DOS_DOIS_TIPOS]
        + [
            pytest.param(pessoa_fisica, "birth_date", id="PF sem birth_date"),
            pytest.param(pessoa_fisica, "occupation", id="PF sem occupation"),
        ]
        + [pytest.param(pessoa_juridica, campo, id=f"PJ sem {campo}") for campo in OBRIGATORIOS_DOS_DOIS_TIPOS if campo != "type"]
        + [pytest.param(pessoa_juridica, "opening_date", id="PJ sem opening_date")],
    )
    def test_recusa_campo_obrigatorio_ausente_e_diz_qual(self, dados_validos, campo_ausente):
        """F1-08. Falta um campo: 400 ONB005001, e o erro diz qual campo falta."""
        # prepara: um cadastro válido, sem um campo
        dados = sem(dados_validos(), campo_ausente)

        # age
        resposta = Onboarding.cadastra(dados)

        # confere
        assert resposta.status_code == 400
        corpo = resposta.json()
        assert corpo["code"] == "ONB005001"
        assert campos_e_regras(corpo) == [(campo_ausente, "required")]

    def test_corpo_vazio_lista_todos_os_obrigatorios(self):
        """F1-09. Corpo vazio: o erro lista os cinco campos comuns de uma vez."""
        # age
        resposta = Onboarding.cadastra({})

        # confere
        assert resposta.status_code == 400
        corpo = resposta.json()
        assert corpo["code"] == "ONB005001"
        assert sorted(campos_e_regras(corpo)) == sorted((campo, "required") for campo in OBRIGATORIOS_DOS_DOIS_TIPOS)

    def test_campo_ausente_vem_antes_do_campo_torto(self):
        """F1-10 (decisão D12). Com um campo faltando e outro torto, a resposta é a do que falta."""
        # prepara: tipo inválido e nome ausente
        dados = sem(pessoa_fisica(type="PX"), "name")

        # age
        resposta = Onboarding.cadastra(dados)

        # confere
        assert resposta.status_code == 400
        assert resposta.json()["code"] == "ONB005001"


class TestCampoForaDoFormato:
    @pytest.mark.parametrize(
        "dados, campo, regra",
        [
            pytest.param(pessoa_fisica(type="PX"), "type", "format", id="tipo que nao e PF nem PJ"),
            pytest.param(pessoa_fisica(document_number="12345678909"), "document_number", "format", id="CPF sem mascara"),
            pytest.param(pessoa_fisica(document_number=novo_cnpj()), "document_number", "format", id="PF com mascara de CNPJ"),
            pytest.param(pessoa_juridica(document_number=novo_cpf()), "document_number", "format", id="PJ com mascara de CPF"),
            pytest.param(pessoa_fisica(birth_date="17/05/1990"), "birth_date", "format", id="nascimento em outro formato"),
            pytest.param(pessoa_juridica(opening_date="2020-1-5"), "opening_date", "format", id="abertura sem os zeros"),
            pytest.param(pessoa_fisica(name=""), "name", "minimum", id="nome vazio"),
            pytest.param(pessoa_fisica(name="A" * 256), "name", "maximum", id="nome com 256 letras"),
            pytest.param(pessoa_fisica(occupation="A" * 101), "occupation", "maximum", id="ocupacao com 101 letras"),
            pytest.param(pessoa_fisica(declared_monthly_income_cents=-1), "declared_monthly_income_cents", "minimum", id="renda negativa"),
            pytest.param(pessoa_fisica(declared_monthly_income_cents=1000.5), "declared_monthly_income_cents", "type", id="renda em float"),
            pytest.param(pessoa_fisica(declared_monthly_income_cents="1000"), "declared_monthly_income_cents", "type", id="renda como texto"),
            pytest.param(
                pessoa_fisica(declared_monthly_income_cents=RENDA_MAXIMA_CENTAVOS + 1),
                "declared_monthly_income_cents", "maximum", id="renda acima do teto",
            ),
            pytest.param(pessoa_fisica(pep_self_declared="sim"), "pep_self_declared", "type", id="PEP como texto"),
        ],
    )
    def test_recusa_campo_fora_do_formato(self, dados, campo, regra):
        """F1-11. Campo com formato, tipo ou tamanho errado: 400 ONB000001,
        dizendo o campo e a regra. Dinheiro nunca é float (R6)."""
        # age
        resposta = Onboarding.cadastra(dados)

        # confere
        assert resposta.status_code == 400
        corpo = resposta.json()
        assert corpo["code"] == "ONB000001"
        assert (campo, regra) in campos_e_regras(corpo)

    def test_aceita_renda_no_teto(self):
        """F1-11, o outro lado da borda: renda exatamente no teto passa."""
        # age
        resposta = Onboarding.cadastra(pessoa_juridica(declared_monthly_income_cents=RENDA_MAXIMA_CENTAVOS))

        # confere
        assert resposta.status_code == 201

    def test_recusa_campo_que_nao_existe(self):
        """F1-12. Campo que o contrato não tem é recusado, e não ignorado."""
        # age
        resposta = Onboarding.cadastra(pessoa_fisica(email="ana@exemplo.com.br"))

        # confere
        assert resposta.status_code == 400
        corpo = resposta.json()
        assert corpo["code"] == "ONB000001"
        assert campos_e_regras(corpo) == [("email", "format")]

    @pytest.mark.parametrize(
        "dados, campo",
        [
            pytest.param(pessoa_fisica(opening_date="2015-03-10"), "opening_date", id="PF com data de abertura"),
            pytest.param(pessoa_juridica(birth_date="1990-05-17"), "birth_date", id="PJ com data de nascimento"),
            pytest.param(pessoa_juridica(occupation="Comerciante"), "occupation", id="PJ com ocupacao"),
        ],
    )
    def test_recusa_campo_do_outro_tipo_de_cliente(self, dados, campo):
        """F1-13 (decisão D6). Só se coleta o necessário (LGPD): campo de PJ
        numa PF, ou de PF numa PJ, é recusado."""
        # age
        resposta = Onboarding.cadastra(dados)

        # confere
        assert resposta.status_code == 400
        corpo = resposta.json()
        assert corpo["code"] == "ONB000001"
        assert campos_e_regras(corpo) == [(campo, "format")]

    def test_recusa_corpo_que_nao_e_json(self):
        """F1-14. Texto solto no lugar de JSON: 400 ONB000001."""
        # prepara
        cabecalhos = cabecalhos_do_gateway(extras={"Content-Type": "application/json"})

        # age
        resposta = Onboarding.envia("POST", "/onboarding", cabecalhos, data="abc")

        # confere
        assert resposta.status_code == 400
        assert resposta.json()["code"] == "ONB000001"


class TestValorImpossivel:
    def test_recusa_cpf_com_digito_errado(self):
        """F1-15. Formato certo, mas os dígitos verificadores não batem: 422 ONB005004."""
        # prepara
        dados = pessoa_fisica(document_number=com_digito_errado(novo_cpf()))

        # age
        resposta = Onboarding.cadastra(dados)

        # confere
        assert resposta.status_code == 422
        corpo = resposta.json()
        assert corpo["code"] == "ONB005004"
        assert campos_e_regras(corpo) == [("document_number", "cpf_check_digit")]

    def test_recusa_cpf_com_todos_os_digitos_iguais(self):
        """F1-16. A conta dos dígitos fecha, mas a Receita não emite esses números."""
        # age
        resposta = Onboarding.cadastra(pessoa_fisica(document_number="111.111.111-11"))

        # confere
        assert resposta.status_code == 422
        assert resposta.json()["code"] == "ONB005004"

    def test_recusa_cnpj_com_digito_errado(self):
        """F1-17. O mesmo para o CNPJ."""
        # prepara
        dados = pessoa_juridica(document_number=com_digito_errado(novo_cnpj()))

        # age
        resposta = Onboarding.cadastra(dados)

        # confere
        assert resposta.status_code == 422
        corpo = resposta.json()
        assert corpo["code"] == "ONB005004"
        assert campos_e_regras(corpo) == [("document_number", "cnpj_check_digit")]

    @pytest.mark.parametrize(
        "dados, campo",
        [
            pytest.param(pessoa_fisica(birth_date="2001-02-30"), "birth_date", id="30 de fevereiro"),
            pytest.param(pessoa_juridica(opening_date="2021-13-01"), "opening_date", id="mes 13"),
        ],
    )
    def test_recusa_data_que_nao_existe(self, dados, campo):
        """F1-18. A data tem o formato certo e não existe no calendário: 422 ONB005005."""
        # age
        resposta = Onboarding.cadastra(dados)

        # confere
        assert resposta.status_code == 422
        corpo = resposta.json()
        assert corpo["code"] == "ONB005005"
        assert campos_e_regras(corpo) == [(campo, "valid_date")]

    def test_recusa_nascimento_no_futuro(self):
        """F1-19. Ninguém nasce amanhã."""
        # age
        resposta = Onboarding.cadastra(pessoa_fisica(birth_date=amanha()))

        # confere
        assert resposta.status_code == 422
        assert resposta.json()["code"] == "ONB005005"

    def test_recusa_abertura_da_empresa_no_futuro(self):
        """F1-20. Nenhuma empresa abre amanhã."""
        # age
        resposta = Onboarding.cadastra(pessoa_juridica(opening_date=amanha()))

        # confere
        assert resposta.status_code == 422
        assert resposta.json()["code"] == "ONB005005"


class TestIdadeEDuplicidade:
    def test_recusa_pf_menor_de_18_anos(self):
        """F1-21. Borda da idade, o lado que é barrado: só completa 18 anos amanhã."""
        # age
        resposta = Onboarding.cadastra(pessoa_fisica(birth_date=nascido_para_completar_amanha(18)))

        # confere
        assert resposta.status_code == 400
        corpo = resposta.json()
        assert corpo["code"] == "ONB005002"
        assert campos_e_regras(corpo) == [("birth_date", "minimum_age")]

    def test_recusa_cpf_que_ja_e_cliente(self):
        """F1-22. Um CPF só pode ter um cadastro: o segundo pedido recebe 409."""
        # prepara: a Ana já é cliente
        ana = pessoa_fisica()
        Onboarding.comeca_abertura(ana)

        # age: alguém cadastra o mesmo CPF de novo, com outra chave
        resposta = Onboarding.cadastra(ana)

        # confere
        assert resposta.status_code == 409
        assert resposta.json()["code"] == "ONB005003"

    def test_recusa_cnpj_que_ja_e_cliente(self):
        """F1-23. O mesmo para o CNPJ."""
        # prepara: a padaria já é cliente
        padaria = pessoa_juridica()
        Onboarding.comeca_abertura(padaria)

        # age
        resposta = Onboarding.cadastra(padaria)

        # confere
        assert resposta.status_code == 409
        assert resposta.json()["code"] == "ONB005003"

    @pytest.mark.concurrency
    def test_cadastros_simultaneos_do_mesmo_cpf_criam_um_so(self):
        """F1-24. Cinco pedidos no mesmo instante, mesmo CPF, chaves diferentes:
        o UNIQUE do banco deixa um passar, e os outros recebem 409, nunca 500.
        São 5 porque 5 é o limite de tentativas por documento (F2)."""
        # prepara
        ana = pessoa_fisica()

        # age: os cinco saem juntos
        respostas = ao_mesmo_tempo([lambda: Onboarding.cadastra(ana) for _ in range(5)])

        # confere
        status = sorted(resposta.status_code for resposta in respostas)
        assert status == [201, 409, 409, 409, 409]
        for resposta in respostas:
            if resposta.status_code == 409:
                assert resposta.json()["code"] == "ONB005003"

    def test_pedido_recusado_nao_grava_nada(self):
        """F1-25. Depois de uma recusa, o mesmo CPF consegue se cadastrar: nada ficou gravado."""
        # prepara: um pedido recusado por data impossível
        ana = pessoa_fisica(birth_date="2001-02-30")
        assert Onboarding.cadastra(ana).status_code == 422

        # age: o mesmo CPF, agora com a data certa
        resposta = Onboarding.cadastra({**ana, "birth_date": "2001-02-28"})

        # confere
        assert resposta.status_code == 201

    def test_recusa_nao_gasta_a_chave(self):
        """F1-26. A chave de um pedido recusado continua livre para um pedido certo."""
        # prepara: a chave K leva um 409, porque o CPF já é cliente
        ana = pessoa_fisica()
        Onboarding.comeca_abertura(ana)
        chave = nova_chave()
        assert Onboarding.cadastra(ana, cabecalhos_do_gateway(chave=chave)).status_code == 409

        # age: a mesma chave K, com outra pessoa
        resposta = Onboarding.cadastra(pessoa_fisica(), cabecalhos_do_gateway(chave=chave))

        # confere
        assert resposta.status_code == 201


class TestRepeticaoComAMesmaChave:
    def test_mesma_chave_e_mesmo_pedido_devolvem_a_mesma_abertura(self):
        """F1-27. Repetir o pedido com a mesma chave não cria nada: volta a mesma
        abertura (200), com uma credencial nova. É assim que quem perdeu a
        credencial recebe outra (decisão D10)."""
        # prepara: o primeiro pedido
        ana = pessoa_fisica()
        chave = nova_chave()
        primeira = Onboarding.cadastra(ana, cabecalhos_do_gateway(chave=chave)).json()

        # age: o mesmo pedido, com a mesma chave
        resposta = Onboarding.cadastra(ana, cabecalhos_do_gateway(chave=chave))

        # confere: a mesma abertura...
        assert resposta.status_code == 200
        corpo = resposta.json()
        assert set(corpo) == CAMPOS_DA_RESPOSTA
        assert corpo["onboarding_key"] == primeira["onboarding_key"]
        assert corpo["customer_key"] == primeira["customer_key"]
        assert corpo["status"] == "DRAFT"
        assert datetime.fromisoformat(corpo["expires_at"]) == datetime.fromisoformat(primeira["expires_at"])

        # ...com uma credencial nova, do mesmo cliente
        nova_credencial = le_credencial(corpo["access_token"])
        assert nova_credencial["sub"] == primeira["customer_key"]
        assert nova_credencial["jti"] != le_credencial(primeira["access_token"])["jti"]

    def test_mesma_chave_com_outro_pedido_e_recusada(self):
        """F1-28 (decisão D8). A mesma chave com outra pessoa é recusada, e nada é criado."""
        # prepara: a chave K já foi usada pela Ana
        chave = nova_chave()
        Onboarding.cadastra(pessoa_fisica(), cabecalhos_do_gateway(chave=chave))
        bruno = pessoa_fisica(name="Bruno Lima")

        # age: o Bruno usa a mesma chave
        resposta = Onboarding.cadastra(bruno, cabecalhos_do_gateway(chave=chave))

        # confere: recusado, e o CPF do Bruno continua livre
        assert resposta.status_code == 409
        assert resposta.json()["code"] == "ONB000012"
        assert Onboarding.cadastra(bruno).status_code == 201

    def test_ordem_dos_campos_nao_muda_o_pedido(self):
        """F1-29. O mesmo conteúdo, com os campos em outra ordem, é o mesmo pedido."""
        # prepara
        ana = pessoa_fisica()
        chave = nova_chave()
        primeira = Onboarding.cadastra(ana, cabecalhos_do_gateway(chave=chave)).json()
        ana_de_tras_para_frente = dict(reversed(list(ana.items())))

        # age
        resposta = Onboarding.cadastra(ana_de_tras_para_frente, cabecalhos_do_gateway(chave=chave))

        # confere
        assert resposta.status_code == 200
        assert resposta.json()["onboarding_key"] == primeira["onboarding_key"]

    def test_exige_a_chave_idempotente(self):
        """F1-30 (decisão D7). Sem a X-Idempotency-Key, nada é gravado."""
        # prepara
        cabecalhos = cabecalhos_do_gateway()
        cabecalhos.pop("X-Idempotency-Key")

        # age
        resposta = Onboarding.cadastra(pessoa_fisica(), cabecalhos)

        # confere
        assert resposta.status_code == 400
        assert resposta.json()["code"] == "ONB000011"

    def test_recusa_chave_que_nao_e_uuid(self):
        """F1-31 (decisão D7). A chave precisa ser um UUID."""
        # age
        resposta = Onboarding.cadastra(pessoa_fisica(), cabecalhos_do_gateway(chave="abc"))

        # confere
        assert resposta.status_code == 400
        assert resposta.json()["code"] == "ONB000011"

    @pytest.mark.concurrency
    def test_pedidos_simultaneos_com_a_mesma_chave_criam_uma_abertura(self):
        """F1-32. Clique duplo sem o gateway na frente: dez pedidos iguais no
        mesmo instante viram uma abertura só (um 201 e nove 200)."""
        # prepara
        ana = pessoa_fisica()
        chave = nova_chave()

        # age: os dez saem juntos
        respostas = ao_mesmo_tempo(
            [lambda: Onboarding.cadastra(ana, cabecalhos_do_gateway(chave=chave)) for _ in range(10)]
        )

        # confere
        status = sorted(resposta.status_code for resposta in respostas)
        assert status == [200] * 9 + [201]
        assert len({resposta.json()["onboarding_key"] for resposta in respostas}) == 1


class TestCorpoDeErro:
    def test_corpo_de_erro_tem_os_campos_do_contrato(self):
        """F1-33. Todo erro tem code, title, description, translation, request_id
        (o mesmo do cabeçalho X-Request-ID) e a lista errors."""
        # age: um pedido com data impossível
        resposta = Onboarding.cadastra(pessoa_fisica(birth_date="2001-02-30"))

        # confere
        corpo = resposta.json()
        assert set(corpo) == {"code", "title", "description", "translation", "request_id", "errors"}
        assert corpo["request_id"] == resposta.headers["X-Request-ID"]
        assert set(corpo["errors"][0]) == {"field", "rule", "message"}

    def test_erro_nunca_repete_documento_nem_renda(self):
        """F1-34. Nenhuma recusa devolve o CPF (com ou sem máscara) nem a renda (LGPD)."""
        # prepara: uma cliente com renda fácil de reconhecer, e quatro pedidos tortos
        renda = 123456789
        ja_cliente = pessoa_fisica(declared_monthly_income_cents=renda)
        Onboarding.comeca_abertura(ja_cliente)
        cpf = novo_cpf()
        pedidos_recusados = {
            "CPF que ja e cliente": ja_cliente,
            "CPF com digito errado": pessoa_fisica(document_number=com_digito_errado(cpf), declared_monthly_income_cents=renda),
            "CPF sem mascara": pessoa_fisica(document_number=so_digitos(cpf), declared_monthly_income_cents=renda),
            "data impossivel": pessoa_fisica(document_number=cpf, birth_date="2001-02-30", declared_monthly_income_cents=renda),
            "renda como texto": pessoa_fisica(document_number=cpf, declared_monthly_income_cents=str(renda)),
        }

        for motivo, dados in pedidos_recusados.items():
            # age
            resposta = Onboarding.cadastra(dados)

            # confere
            assert resposta.status_code >= 400, motivo
            assert dados["document_number"] not in resposta.text, motivo
            assert so_digitos(dados["document_number"]) not in resposta.text, motivo
            assert str(renda) not in resposta.text, motivo
