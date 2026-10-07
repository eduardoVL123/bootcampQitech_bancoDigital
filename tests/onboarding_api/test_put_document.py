"""F4: PUT /onboarding/{onboarding_key}/document, o envio do RG (docs/testes/onboarding-api.md).

O RG completo é frente e verso (front e back), ou uma imagem com os dois
lados (both). A abertura guarda no máximo duas imagens, e cada uma é JPEG
ou PNG de até 5 MB, conferido pelos primeiros bytes. O teste nunca lê o
bucket (R1): o que ficou guardado ele vê pelo GET /onboarding/{key}.
"""
import pytest

from tests.utils.onboarding_api import (
    FALHA_SIMULADA_LIGADA,
    LIMITE_DA_IMAGEM_BYTES,
    Onboarding,
    ao_mesmo_tempo,
    bytes_de_jpeg,
    bytes_de_pdf,
    bytes_de_png,
    cabecalhos_do_gateway,
    campos_e_regras,
    credencial_de_compliance,
    imagem,
    imagens,
    nova_chave,
)


def envia(abertura: dict, arquivos: list, cabecalhos: dict = None):
    """O dono da abertura manda as imagens do RG."""
    return Onboarding.envia_rg(abertura["onboarding_key"], abertura["access_token"], arquivos, cabecalhos)


def consulta(abertura: dict) -> dict:
    """A abertura como o dono vê, pelo GET."""
    resposta = Onboarding.consulta_abertura(abertura["onboarding_key"], abertura["access_token"])
    assert resposta.status_code == 200, resposta.text
    return resposta.json()


def historico(corpo: dict) -> list:
    """As etapas por onde a abertura passou, em ordem. Depois do RG completo, o
    worker pode já ter seguido com ela (F6): por isso os testes desta fatia
    conferem o começo do histórico, e não a etapa de agora."""
    return [evento["status"] for evento in corpo["status_events"]]


def lados_recebidos(abertura: dict) -> list:
    return [documento["side"] for documento in consulta(abertura)["documents"]]


def abertura_com(*lados: str) -> dict:
    """Uma abertura nova que já recebeu estes lados do RG."""
    abertura = Onboarding.comeca_abertura()

    if lados:
        resposta = envia(abertura, imagens(*lados))
        assert resposta.status_code in (200, 202), resposta.text

    return abertura


class TestRgCompleto:
    def test_frente_e_verso_juntos_completam_o_rg(self):
        """F4-01. Frente e verso no mesmo envio: o RG está completo, a abertura
        entra na fila da análise e a pessoa só espera."""
        # prepara
        abertura = Onboarding.comeca_abertura()

        # age
        resposta = envia(abertura, imagens("front", "back"))

        # confere
        assert resposta.status_code == 202
        corpo = resposta.json()
        assert corpo["onboarding_key"] == abertura["onboarding_key"]
        assert corpo["status"] == "PENDING_KYC"
        assert corpo["next_step"] == "WAIT"

    def test_uma_imagem_com_os_dois_lados_completa_o_rg(self):
        """F4-02. Uma imagem só, com os dois lados (both), também completa o RG."""
        # prepara
        abertura = Onboarding.comeca_abertura()

        # age
        resposta = envia(abertura, imagens("both"))

        # confere
        assert resposta.status_code == 202
        assert resposta.json()["status"] == "PENDING_KYC"
        assert lados_recebidos(abertura) == ["BOTH"]

    def test_so_a_frente_mantem_draft_e_pede_o_verso(self):
        """F4-03. Só a frente: a abertura continua em DRAFT, e o próximo passo é o verso."""
        # prepara
        abertura = Onboarding.comeca_abertura()

        # age
        resposta = envia(abertura, imagens("front"))

        # confere
        assert resposta.status_code == 200
        corpo = resposta.json()
        assert corpo["status"] == "DRAFT"
        assert corpo["next_step"] == "SEND_BACK"

    def test_so_o_verso_mantem_draft_e_pede_a_frente(self):
        """F4-21 (decisão D23). Só o verso: continua em DRAFT, e o próximo passo é a frente."""
        # prepara
        abertura = Onboarding.comeca_abertura()

        # age
        resposta = envia(abertura, imagens("back"))

        # confere
        assert resposta.status_code == 200
        corpo = resposta.json()
        assert corpo["status"] == "DRAFT"
        assert corpo["next_step"] == "SEND_FRONT"

    def test_verso_depois_da_frente_completa_o_rg(self):
        """F4-04. A frente num envio e o verso em outro: o segundo completa o RG."""
        # prepara
        abertura = abertura_com("front")

        # age
        resposta = envia(abertura, imagens("back"))

        # confere
        assert resposta.status_code == 202
        corpo = resposta.json()
        assert corpo["status"] == "PENDING_KYC"
        assert corpo["next_step"] == "WAIT"

    def test_abertura_mostra_os_lados_recebidos(self):
        """F4-05. O GET mostra os lados já recebidos e o próximo passo de cada
        momento. De cada imagem sai só o lado, o tipo, o tamanho e a hora,
        nunca o caminho no bucket (decisão D22)."""
        # prepara
        abertura = Onboarding.comeca_abertura()

        # age: primeiro a frente, depois o verso
        envia(abertura, imagens("front"))
        depois_da_frente = consulta(abertura)
        envia(abertura, imagens("back"))
        depois_do_verso = consulta(abertura)

        # confere
        assert [documento["side"] for documento in depois_da_frente["documents"]] == ["FRONT"]
        assert depois_da_frente["status"] == "DRAFT"
        assert depois_da_frente["next_step"] == "SEND_BACK"

        assert [documento["side"] for documento in depois_do_verso["documents"]] == ["FRONT", "BACK"]
        assert historico(depois_do_verso)[:2] == ["DRAFT", "PENDING_KYC"]
        assert depois_do_verso["next_step"] == "WAIT"

        for documento in depois_do_verso["documents"]:
            assert set(documento) == {"side", "content_type", "size_bytes", "created_at"}

    def test_rg_completo_entra_no_historico(self):
        """F4-20. A ida para PENDING_KYC grava um evento no histórico, feito pela
        API. Daí em diante, o worker pega a abertura da fila (F6), e o histórico segue."""
        # prepara
        abertura = Onboarding.comeca_abertura()

        # age
        envia(abertura, imagens("front", "back"))

        # confere
        eventos = consulta(abertura)["status_events"]
        assert [evento["status"] for evento in eventos][:2] == ["DRAFT", "PENDING_KYC"]
        assert eventos[1]["actor"] == "api"


class TestArquivos:
    def test_aceita_png(self):
        """F4-06. JPEG e PNG são aceitos, e o tipo guardado é o que os bytes dizem."""
        # prepara
        abertura = Onboarding.comeca_abertura()
        frente_em_png = imagem("front", bytes_de_png(), "rg-frente.png", "image/png")

        # age
        resposta = envia(abertura, [frente_em_png, imagem("back")])

        # confere
        assert resposta.status_code == 202
        tipos = {documento["side"]: documento["content_type"] for documento in consulta(abertura)["documents"]}
        assert tipos == {"FRONT": "image/png", "BACK": "image/jpeg"}

    def test_aceita_arquivo_de_exatamente_5_mb(self):
        """F4-07. A borda do tamanho: 5 MB cravados (5 x 1024 x 1024 bytes) passam."""
        # prepara
        abertura = Onboarding.comeca_abertura()

        # age
        resposta = envia(abertura, [imagem("front", bytes_de_jpeg(LIMITE_DA_IMAGEM_BYTES))])

        # confere
        assert resposta.status_code == 200
        assert consulta(abertura)["documents"][0]["size_bytes"] == LIMITE_DA_IMAGEM_BYTES

    def test_recusa_arquivo_acima_de_5_mb(self):
        """F4-08. Um byte além dos 5 MB: 413, e nada é guardado."""
        # prepara
        abertura = Onboarding.comeca_abertura()

        # age
        resposta = envia(abertura, [imagem("front", bytes_de_jpeg(LIMITE_DA_IMAGEM_BYTES + 1))])

        # confere
        assert resposta.status_code == 413
        corpo = resposta.json()
        assert corpo["code"] == "ONB005011"
        assert campos_e_regras(corpo) == [("front", "max_size")]
        assert lados_recebidos(abertura) == []

    def test_recusa_arquivo_que_nao_e_jpeg_nem_png(self):
        """F4-09. Um PDF não é foto do RG: 422."""
        # prepara
        abertura = Onboarding.comeca_abertura()

        # age
        resposta = envia(abertura, [imagem("front", bytes_de_pdf(), "rg.pdf", "application/pdf")])

        # confere
        assert resposta.status_code == 422
        corpo = resposta.json()
        assert corpo["code"] == "ONB005012"
        assert campos_e_regras(corpo) == [("front", "file_type")]
        assert lados_recebidos(abertura) == []

    def test_tipo_do_arquivo_vem_dos_bytes_e_nao_do_nome(self):
        """F4-10. Quem decide o tipo são os primeiros bytes, e não o nome do
        arquivo nem o Content-Type que o cliente declara."""
        # prepara
        abertura_do_pdf = Onboarding.comeca_abertura()
        abertura_do_jpeg = Onboarding.comeca_abertura()
        pdf_disfarcado_de_jpeg = imagem("front", bytes_de_pdf(), "rg.jpg", "image/jpeg")
        jpeg_com_nome_de_pdf = imagem("front", bytes_de_jpeg(), "rg.pdf", "application/pdf")

        # age
        resposta_do_pdf = envia(abertura_do_pdf, [pdf_disfarcado_de_jpeg])
        resposta_do_jpeg = envia(abertura_do_jpeg, [jpeg_com_nome_de_pdf])

        # confere
        assert resposta_do_pdf.status_code == 422
        assert resposta_do_pdf.json()["code"] == "ONB005012"
        assert resposta_do_jpeg.status_code == 200
        assert consulta(abertura_do_jpeg)["documents"][0]["content_type"] == "image/jpeg"

    def test_recusa_envio_sem_arquivo(self):
        """F4-11. Sem nenhuma imagem: 400, falta o dado obrigatório."""
        # prepara
        abertura = Onboarding.comeca_abertura()

        # age
        resposta = envia(abertura, [])

        # confere
        assert resposta.status_code == 400
        assert resposta.json()["code"] == "ONB005001"


class TestLimiteDeImagens:
    @pytest.mark.parametrize(
        "lados_antes, lados_do_envio",
        [
            pytest.param([], ["front", "back", "both"], id="front, back e both no mesmo envio"),
            pytest.param(["front"], ["front", "back"], id="front e depois front e back"),
        ],
    )
    def test_recusa_mais_de_duas_imagens(self, lados_antes, lados_do_envio):
        """F4-12. A abertura guarda no máximo duas imagens do RG."""
        # prepara
        abertura = abertura_com(*lados_antes)

        # age
        resposta = envia(abertura, imagens(*lados_do_envio))

        # confere
        assert resposta.status_code == 409
        assert resposta.json()["code"] == "ONB005009"

    @pytest.mark.parametrize(
        "lados_antes, lados_do_envio",
        [
            pytest.param(["front"], ["front"], id="front e depois front"),
            pytest.param(["front"], ["both"], id="front e depois both"),
            pytest.param([], ["front", "front"], id="front duas vezes no mesmo envio"),
            pytest.param([], ["front", "both"], id="front e both no mesmo envio"),
        ],
    )
    def test_recusa_lado_repetido(self, lados_antes, lados_do_envio):
        """F4-13. Cada lado do RG vai uma vez só, e a imagem both já traz os dois lados."""
        # prepara
        abertura = abertura_com(*lados_antes)

        # age
        resposta = envia(abertura, imagens(*lados_do_envio))

        # confere
        assert resposta.status_code == 409
        assert resposta.json()["code"] == "ONB005009"

    @pytest.mark.parametrize(
        "lados_antes, arquivos, status_esperado, codigo_esperado",
        [
            pytest.param(
                ["front"], imagens("front", "back"), 409, "ONB005009",
                id="409 frente de novo com o verso junto",
            ),
            pytest.param(
                [], [imagem("front"), imagem("back", bytes_de_jpeg(LIMITE_DA_IMAGEM_BYTES + 1))], 413, "ONB005011",
                id="413 verso grande com a frente boa junto",
            ),
            pytest.param(
                [], [imagem("front"), imagem("back", bytes_de_pdf())], 422, "ONB005012",
                id="422 verso em PDF com a frente boa junto",
            ),
        ],
    )
    def test_envio_recusado_nao_muda_nada(self, lados_antes, arquivos, status_esperado, codigo_esperado):
        """F4-14. Um envio recusado não guarda nada, nem a imagem boa que veio junto."""
        # prepara
        abertura = abertura_com(*lados_antes)
        antes_do_envio = consulta(abertura)

        # age
        resposta = envia(abertura, arquivos)

        # confere
        assert resposta.status_code == status_esperado
        assert resposta.json()["code"] == codigo_esperado
        depois_do_envio = consulta(abertura)
        assert depois_do_envio["documents"] == antes_do_envio["documents"]
        assert depois_do_envio["status"] == antes_do_envio["status"]

    def test_recusa_envio_fora_de_draft(self):
        """F4-15. Com o RG completo, a abertura saiu de DRAFT e não espera mais imagem."""
        # prepara
        abertura = abertura_com("front", "back")

        # age
        resposta = envia(abertura, imagens("front"))

        # confere
        assert resposta.status_code == 409
        assert resposta.json()["code"] == "ONB005008"
        assert lados_recebidos(abertura) == ["FRONT", "BACK"]


class TestQuemPodeEnviar:
    @pytest.mark.parametrize(
        "quem_envia",
        [
            pytest.param(lambda ana, bruno: (ana["onboarding_key"], bruno["access_token"]), id="abertura de outra pessoa"),
            pytest.param(lambda ana, bruno: (nova_chave(), bruno["access_token"]), id="abertura que ninguem criou"),
            pytest.param(lambda ana, bruno: (ana["onboarding_key"], credencial_de_compliance()), id="credencial de compliance"),
        ],
    )
    def test_envio_para_abertura_de_outra_pessoa_responde_404(self, quem_envia):
        """F4-16 (R8). Só o dono manda o RG da abertura. Para qualquer outro, a
        abertura não existe, e nada muda nela."""
        # prepara: a Ana tem uma abertura, e o Bruno tem a dele
        ana = Onboarding.comeca_abertura()
        bruno = Onboarding.comeca_abertura()
        chave_da_abertura, credencial = quem_envia(ana, bruno)

        # age
        resposta = Onboarding.envia_rg(chave_da_abertura, credencial, imagens("front", "back"))

        # confere
        assert resposta.status_code == 404
        assert resposta.json()["code"] == "ONB005006"
        assert lados_recebidos(ana) == []

    def test_envio_exige_a_chave_idempotente(self):
        """F4-19 (decisão D7). Sem a X-Idempotency-Key, a API recusa e não guarda nada."""
        # prepara
        abertura = Onboarding.comeca_abertura()
        sem_chave = cabecalhos_do_gateway()
        sem_chave.pop("X-Idempotency-Key")

        # age
        resposta = envia(abertura, imagens("front"), sem_chave)

        # confere
        assert resposta.status_code == 400
        assert resposta.json()["code"] == "ONB000011"
        assert lados_recebidos(abertura) == []


@pytest.mark.fault_injection
@pytest.mark.skipif(not FALHA_SIMULADA_LIGADA, reason="precisa da API e do pytest com FAULT_INJECTION_ENABLED=true")
class TestBucketFora:
    def test_bucket_fora_responde_503_e_nao_grava_nada(self):
        """F4-17. Primeiro o bucket, depois o banco: com o bucket fora, nada é
        gravado e a abertura continua em DRAFT. Repetir com a mesma chave dá certo."""
        # prepara
        abertura = Onboarding.comeca_abertura()
        chave = nova_chave()
        com_o_bucket_fora = cabecalhos_do_gateway(chave=chave, extras={"X-Fault-Injection": "bucket_unavailable"})

        # age
        resposta = envia(abertura, imagens("front", "back"), com_o_bucket_fora)

        # confere
        assert resposta.status_code == 503
        assert resposta.json()["code"] == "ONB005015"
        depois_da_falha = consulta(abertura)
        assert depois_da_falha["status"] == "DRAFT"
        assert depois_da_falha["documents"] == []

        # age de novo: a mesma chave, com o bucket de volta
        repeticao = envia(abertura, imagens("front", "back"), cabecalhos_do_gateway(chave=chave))

        # confere
        assert repeticao.status_code == 202


class TestEnviosSimultaneos:
    @pytest.mark.concurrency
    def test_envios_simultaneos_do_mesmo_lado_gravam_um_so(self):
        """F4-18. Cinco envios da frente no mesmo instante: um passa, e os
        outros recebem 409, nunca 500 (UNIQUE(onboarding_id, side))."""
        # prepara
        abertura = Onboarding.comeca_abertura()

        # age
        respostas = ao_mesmo_tempo([lambda: envia(abertura, imagens("front")) for _ in range(5)])

        # confere
        assert sorted(resposta.status_code for resposta in respostas) == [200, 409, 409, 409, 409]
        for resposta in respostas:
            if resposta.status_code == 409:
                assert resposta.json()["code"] == "ONB005009"
        assert lados_recebidos(abertura) == ["FRONT"]

    @pytest.mark.concurrency
    def test_frente_e_verso_em_envios_simultaneos_completam_o_rg(self):
        """F4-22. A frente e o verso em dois pedidos que chegam juntos: um deles
        vê o RG completo, e a abertura vai para PENDING_KYC uma vez só. Sem a
        trava da abertura, cada pedido veria só o próprio lado, e ela ficaria
        presa em DRAFT. São cinco aberturas ao mesmo tempo, para o choque
        acontecer. Depois do PENDING_KYC, o worker já pode ter pegado a abertura (F6)."""
        # prepara
        aberturas = [Onboarding.comeca_abertura() for _ in range(5)]
        chamadas = []
        for abertura in aberturas:
            chamadas.append(lambda abertura=abertura: envia(abertura, imagens("front")))
            chamadas.append(lambda abertura=abertura: envia(abertura, imagens("back")))

        # age
        respostas = ao_mesmo_tempo(chamadas)

        # confere
        assert sorted(resposta.status_code for resposta in respostas) == [200] * 5 + [202] * 5
        for abertura in aberturas:
            etapas = historico(consulta(abertura))
            assert etapas[:2] == ["DRAFT", "PENDING_KYC"]
            assert etapas.count("PENDING_KYC") == 1

    @pytest.mark.concurrency
    def test_frente_e_imagem_com_os_dois_lados_juntas_gravam_uma_so(self):
        """F4-23. A frente e uma imagem both chegando juntas repetem a frente:
        só uma das duas é guardada, e a outra recebe 409. O UNIQUE do banco não
        pega esse caso, porque os lados gravados são diferentes (FRONT e BOTH).
        São cinco aberturas ao mesmo tempo, para o choque acontecer."""
        # prepara
        aberturas = [Onboarding.comeca_abertura() for _ in range(5)]
        chamadas = []
        for abertura in aberturas:
            chamadas.append(lambda abertura=abertura: envia(abertura, imagens("front")))
            chamadas.append(lambda abertura=abertura: envia(abertura, imagens("both")))

        # age
        respostas = ao_mesmo_tempo(chamadas)

        # confere: em cada abertura, um envio passou e o outro deu 409
        for frente, dois_lados in zip(respostas[0::2], respostas[1::2]):
            status_do_par = sorted([frente.status_code, dois_lados.status_code])
            assert status_do_par in ([200, 409], [202, 409])
        for abertura in aberturas:
            assert len(lados_recebidos(abertura)) == 1
