"""O grupo do titular do destino: o CPF responsavel, os CNPJs dele em aberto
e as contas novas que confirmam, ou nao, a rejeicao pelo eixo destino.

O banco nao e zerado entre rodadas, e as contas que um teste cria ficam.
Cada grupo do mock tem papel fixo (tests/utils/pix.py): no GRUPO, so testes
que esperam a confirmacao (conta a mais nao muda nada); na LOJA e no CNPJ
de vinculo vencido, sempre as mesmas contas (documento e instituicao), que
se juntam com as das rodadas anteriores. Os outros usam documentos novos.
"""
import random
from datetime import datetime, timedelta

from tests.utils.pix import (
    CNPJ_VINCULO_VENCIDO, GRUPO_CNPJS, GRUPO_CPF, LOJA_CNPJ, LOJA_CNPJ_BAIXADO, LOJA_CPF, SAO_PAULO, AntifraudApi,
    Pagador, Recebedor, analisa, apresenta_conta, disparou, nova_base, pix, regra, sem_mascara,
)

REGRA = "CONTAS_NOVAS_DO_GRUPO"


def _grupo(corpo):
    return corpo["metadata"]["destination_group"]


def _varios_pagam(recebedor, quantos, hoje):
    """Um pagador novo por minuto, R$ 50 cada. Devolve o payload e o corpo do ultimo Pix."""
    payload = corpo = None
    for indice in range(quantos):
        payload = pix(Pagador(), recebedor, 5000, (hoje + timedelta(minutes=indice)).isoformat())
        corpo = analisa(payload)
    return payload, corpo


def _antes_da_loja_abrir():
    """Um dia entre a baixa do MEI (30/11/2020) e a abertura da loja (24/02/2021), entre 10h e 17h.

    Nesse periodo a dona nao tem CNPJ em aberto, e o LOJA_CNPJ ainda nao
    esta no nome dela: o vinculo existe no mock, mas so comeca depois.
    """
    dia = datetime(2020, 12, 1, tzinfo=SAO_PAULO) + timedelta(days=random.randint(0, 80))
    return dia.replace(hour=random.randint(10, 16), minute=random.randint(0, 59))


def test_conta_laranja_num_grupo_com_tres_contas_novas_reprova():
    hoje = nova_base()
    apresenta_conta(GRUPO_CNPJS[1], "11111111", hoje - timedelta(days=5), hoje - timedelta(hours=2))
    apresenta_conta(GRUPO_CNPJS[2], "22222222", hoje - timedelta(days=3), hoje - timedelta(hours=2))

    payload, corpo = _varios_pagam(Recebedor(documento=GRUPO_CNPJS[0], aberta_em=hoje - timedelta(days=10)), 10, hoje)

    grupo, resultado = _grupo(corpo), regra(corpo, REGRA)
    assert corpo["metadata"]["risk_axes"]["destino"] == 80
    assert corpo["status"] == "rejected"
    assert corpo["metadata"]["authentication"]["level"] == "none"
    assert corpo["metadata"]["scenario"] == "conta_laranja"
    assert corpo["metadata"]["reason"] == "CONTA_LARANJA"
    assert disparou(corpo, REGRA)
    assert resultado["effective_points"] == 0
    assert resultado["data_origin"] == "mock"
    assert grupo["is_mock"] is True
    assert grupo["link"] == "found"
    assert grupo["responsible_cpf"] == "***.572.936-**"
    # O CNPJ que so esteve no nome dele em 2018 fica de fora.
    assert grupo["open_cnpjs"] == sorted(map(sem_mascara, GRUPO_CNPJS))
    assert grupo["new_accounts"] >= 3
    assert grupo["confirmed"] is True
    assert grupo["gate"] == "rejected"
    assert AntifraudApi.get(payload["id"]).json()["metadata"]["destination_group"] == grupo


def test_destino_pf_agrupa_os_cnpjs_em_aberto_do_proprio_cpf():
    hoje = nova_base()
    apresenta_conta(GRUPO_CNPJS[0], "11111111", hoje - timedelta(days=5), hoje - timedelta(hours=2))
    apresenta_conta(GRUPO_CNPJS[2], "22222222", hoje - timedelta(days=3), hoje - timedelta(hours=2))

    _, corpo = _varios_pagam(Recebedor(documento=GRUPO_CPF, aberta_em=hoje - timedelta(days=10)), 10, hoje)

    grupo = _grupo(corpo)
    assert corpo["metadata"]["risk_axes"]["destino"] == 80
    assert corpo["status"] == "rejected"
    assert grupo["link"] == "self"
    assert grupo["responsible_cpf"] == "***.572.936-**"
    assert grupo["open_cnpjs"] == sorted(map(sem_mascara, GRUPO_CNPJS))
    assert grupo["new_accounts"] >= 3
    assert grupo["gate"] == "rejected"


def test_loja_nova_sem_vinculo_no_mock_pede_facial_document():
    # O custo do eixo destino reprovando sempre: a loja nova, na primeira
    # semana, recebendo de 10 clientes numa hora. Sem grupo, so 2FA.
    hoje = nova_base()

    _, corpo = _varios_pagam(Recebedor(pj=True, aberta_em=hoje - timedelta(days=7)), 10, hoje)

    grupo = _grupo(corpo)
    assert corpo["metadata"]["risk_axes"]["destino"] == 80
    assert corpo["status"] == "two_factor_required"
    assert corpo["metadata"]["authentication"]["level"] == "facial_document"
    assert grupo["link"] == "not_found"
    assert grupo["responsible_cpf"] is None
    assert grupo["open_cnpjs"] == []
    assert grupo["new_accounts"] == 1
    assert grupo["confirmed"] is False
    assert grupo["gate"] == "facial_document"
    assert not disparou(corpo, REGRA)


def test_loja_nova_da_dona_pede_facial_document_e_o_mei_baixado_nao_conta():
    hoje = nova_base()
    # A conta pessoal nova da dona entra no grupo. A do MEI baixado e
    # artificial (empresa baixada nao abre conta): prova que ele fica de fora.
    apresenta_conta(LOJA_CPF, "11111111", hoje - timedelta(days=20), hoje - timedelta(hours=2))
    apresenta_conta(LOJA_CNPJ_BAIXADO, "22222222", hoje - timedelta(days=5), hoje - timedelta(hours=2))

    _, corpo = _varios_pagam(Recebedor(documento=LOJA_CNPJ, aberta_em=hoje - timedelta(days=7)), 10, hoje)

    grupo = _grupo(corpo)
    assert corpo["metadata"]["risk_axes"]["destino"] == 80
    assert corpo["status"] == "two_factor_required"
    assert corpo["metadata"]["authentication"]["level"] == "facial_document"
    assert grupo["link"] == "found"
    assert grupo["responsible_cpf"] == "***.149.527-**"
    assert grupo["open_cnpjs"] == [sem_mascara(LOJA_CNPJ)]
    # Com o MEI baixado seriam 3, e o Pix seria reprovado.
    assert grupo["new_accounts"] == 2
    assert grupo["confirmed"] is False
    assert grupo["gate"] == "facial_document"


def test_vinculo_fora_da_vigencia_nao_agrupa():
    hoje = nova_base()
    apresenta_conta(GRUPO_CNPJS[0], "11111111", hoje - timedelta(days=5), hoje - timedelta(hours=2))
    apresenta_conta(GRUPO_CNPJS[1], "22222222", hoje - timedelta(days=3), hoje - timedelta(hours=2))

    _, corpo = _varios_pagam(Recebedor(documento=CNPJ_VINCULO_VENCIDO, aberta_em=hoje - timedelta(days=10)), 10, hoje)

    grupo = _grupo(corpo)
    assert corpo["metadata"]["risk_axes"]["destino"] == 80
    assert corpo["status"] == "two_factor_required"
    assert corpo["metadata"]["authentication"]["level"] == "facial_document"
    assert grupo["link"] == "not_in_force"
    assert grupo["responsible_cpf"] is None
    assert grupo["open_cnpjs"] == []
    # Pelo vinculo de 2018 o grupo seria o do GRUPO_CPF: 3 ou mais, reprovado.
    assert grupo["new_accounts"] == 1
    assert grupo["gate"] == "facial_document"


def test_cnpj_antes_do_vinculo_comecar_nao_agrupa():
    hoje = _antes_da_loja_abrir()

    _, corpo = _varios_pagam(Recebedor(documento=LOJA_CNPJ, aberta_em=hoje - timedelta(days=7)), 10, hoje)

    grupo = _grupo(corpo)
    assert corpo["metadata"]["risk_axes"]["destino"] == 80
    assert corpo["status"] == "two_factor_required"
    assert corpo["metadata"]["authentication"]["level"] == "facial_document"
    # Contando o vinculo antes do available_from, o grupo seria o da dona.
    assert grupo["link"] == "not_in_force"
    assert grupo["responsible_cpf"] is None
    assert grupo["open_cnpjs"] == []
    assert grupo["new_accounts"] == 1
    assert grupo["gate"] == "facial_document"


def test_cnpj_que_ainda_nao_abriu_fica_fora_do_grupo_do_cpf():
    hoje = _antes_da_loja_abrir()

    _, corpo = _varios_pagam(
        Recebedor(documento=LOJA_CPF, aberta_em=hoje - timedelta(days=7), participante="11111111"), 10, hoje)

    grupo = _grupo(corpo)
    assert corpo["metadata"]["risk_axes"]["destino"] == 80
    assert corpo["status"] == "two_factor_required"
    assert grupo["link"] == "self"
    assert grupo["responsible_cpf"] == "***.149.527-**"
    # A loja so abre em 24/02/2021, e o MEI ja foi baixado.
    assert grupo["open_cnpjs"] == []
    assert grupo["new_accounts"] == 1
    assert grupo["gate"] == "facial_document"


def test_conta_de_mais_de_30_dias_e_a_mesma_instituicao_nao_somam():
    # Sem o limite de baixo da janela, ou contando conta por conta em vez de
    # por instituicao, seriam 3 e o Pix seria reprovado.
    hoje = nova_base()
    pessoa = Recebedor(aberta_em=hoje - timedelta(days=10))
    apresenta_conta(pessoa.documento, "11111111", hoje - timedelta(days=29), hoje - timedelta(hours=2))
    apresenta_conta(pessoa.documento, "22222222", hoje - timedelta(days=31), hoje - timedelta(hours=2))
    apresenta_conta(pessoa.documento, "60701190", hoje - timedelta(days=4), hoje - timedelta(hours=2))

    _, corpo = _varios_pagam(pessoa, 10, hoje)

    grupo = _grupo(corpo)
    assert corpo["metadata"]["risk_axes"]["destino"] == 80
    assert corpo["status"] == "two_factor_required"
    assert corpo["metadata"]["authentication"]["level"] == "facial_document"
    assert grupo["link"] == "self"
    assert grupo["open_cnpjs"] == []
    assert grupo["new_accounts"] == 2
    assert grupo["gate"] == "facial_document"


def test_cpf_com_contas_novas_em_tres_instituicoes_reprova():
    hoje = nova_base()
    pessoa = Recebedor(aberta_em=hoje - timedelta(days=10))
    apresenta_conta(pessoa.documento, "11111111", hoje - timedelta(days=4), hoje - timedelta(hours=2))
    apresenta_conta(pessoa.documento, "22222222", hoje - timedelta(days=12), hoje - timedelta(hours=2))

    _, corpo = _varios_pagam(pessoa, 10, hoje)

    grupo = _grupo(corpo)
    assert corpo["status"] == "rejected"
    assert grupo["link"] == "self"
    assert grupo["open_cnpjs"] == []
    assert grupo["new_accounts"] == 3
    assert grupo["gate"] == "rejected"
    assert regra(corpo, REGRA)["data_origin"] == "history"


def test_grupo_confirmado_com_eixo_destino_abaixo_de_80_nao_reprova():
    hoje = nova_base()
    apresenta_conta(GRUPO_CNPJS[1], "11111111", hoje - timedelta(days=5), hoje - timedelta(hours=2))
    apresenta_conta(GRUPO_CNPJS[2], "22222222", hoje - timedelta(days=3), hoje - timedelta(hours=2))

    _, corpo = _varios_pagam(Recebedor(documento=GRUPO_CNPJS[0], aberta_em=hoje - timedelta(days=10)), 5, hoje)

    assert corpo["metadata"]["risk_axes"]["destino"] == 60
    assert disparou(corpo, REGRA)
    assert regra(corpo, REGRA)["raw_points"] == 0
    assert corpo["status"] == "two_factor_required"
    assert corpo["metadata"]["authentication"]["level"] == "facial_document"
    assert _grupo(corpo)["confirmed"] is True
    assert _grupo(corpo)["gate"] == "not_reached"
