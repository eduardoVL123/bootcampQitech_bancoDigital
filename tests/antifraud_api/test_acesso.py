"""Acesso e localizacao: aparelho novo, viagem impossivel por GPS
ou IP, GPS longe do IP, ambiente fora do Brasil, infraestrutura
compartilhada e a ruptura de contexto."""
import random
from datetime import timedelta

from tests.utils.pix import (
    LISBOA_GPS, RECIFE_GPS, REDE_LISBOA, REDE_RECIFE, SAO_PAULO_GPS, Pagador, Recebedor, analisa, disparou, paga,
    historico, nova_base, novo_ip, pix, pontos, regra,
)


def _rede_desconhecida() -> str:
    return f"100.{random.randint(64, 127)}.{random.randint(0, 255)}"


def _com_historico(pagador, hoje, quantidade=3):
    historico(pagador, [5000] * quantidade, hoje - timedelta(days=3), timedelta(hours=6), recebedores_novos=True)


def test_aparelho_novo_com_historico_soma_20():
    pagador, hoje = Pagador(), nova_base()
    _com_historico(pagador, hoje)

    corpo = analisa(pix(pagador, Recebedor(), 5000, hoje.isoformat(), aparelho="dvc-novo-" + pagador.conta))

    assert pontos(corpo, "APARELHO_NOVO") == 20


def test_primeiro_pix_da_vida_nao_e_aparelho_novo():
    corpo = analisa(pix(Pagador(), Recebedor(), 5000, nova_base().isoformat()))

    assert not disparou(corpo, "APARELHO_NOVO")


def test_aparelho_novo_numa_rede_desconhecida_soma_so_os_20_do_aparelho():
    # A rede nova nao pesa mais sozinha (a REDE_NOVA saiu): rede de celular
    # muda o tempo todo, e quem conta a troca de acesso e o aparelho.
    pagador, hoje = Pagador(), nova_base()
    _com_historico(pagador, hoje)

    corpo = analisa(pix(pagador, Recebedor(), 5000, hoje.isoformat(), aparelho="dvc-x-" + pagador.conta,
                        ip=f"{_rede_desconhecida()}.9"))

    assert pontos(corpo, "APARELHO_NOVO") == 20
    assert corpo["metadata"]["risk_axes"]["acesso"] == 20


def test_sao_paulo_e_recife_em_15_min_por_gps_soma_40():
    pagador, hoje = Pagador(), nova_base()
    analisa(pix(pagador, Recebedor(), 5000, hoje.isoformat()))

    corpo = analisa(pix(pagador, Recebedor(), 5000, (hoje + timedelta(minutes=15)).isoformat(), gps=RECIFE_GPS))

    assert pontos(corpo, "VIAGEM_IMPOSSIVEL") == 40


def test_mesma_cidade_em_15_min_nao_dispara():
    pagador, hoje = Pagador(), nova_base()
    analisa(pix(pagador, Recebedor(), 5000, hoje.isoformat()))

    corpo = analisa(pix(pagador, Recebedor(), 5000, (hoje + timedelta(minutes=15)).isoformat(), gps=(-23.60, -46.70)))

    assert not disparou(corpo, "VIAGEM_IMPOSSIVEL")


def test_voo_de_5_horas_nao_dispara():
    pagador, hoje = Pagador(), nova_base()
    analisa(pix(pagador, Recebedor(), 5000, hoje.isoformat()))

    corpo = analisa(pix(pagador, Recebedor(), 5000, (hoje + timedelta(hours=5)).isoformat(), gps=RECIFE_GPS,
                        ip=novo_ip(REDE_RECIFE)))

    assert not disparou(corpo, "VIAGEM_IMPOSSIVEL")


def test_dois_pix_no_mesmo_segundo_nao_dividem_por_zero():
    pagador, hoje = Pagador(), nova_base()
    analisa(pix(pagador, Recebedor(), 5000, hoje.isoformat()))

    corpo = analisa(pix(pagador, Recebedor(), 5000, hoje.isoformat(), gps=RECIFE_GPS))

    assert regra(corpo, "VIAGEM_IMPOSSIVEL")["evaluation"] == "not_evaluable"


def test_sem_gps_a_viagem_impossivel_usa_o_ip():
    pagador, hoje = Pagador(), nova_base()
    analisa(pix(pagador, Recebedor(), 5000, hoje.isoformat(), gps=None))

    corpo = analisa(pix(pagador, Recebedor(), 5000, (hoje + timedelta(minutes=15)).isoformat(), gps=None,
                        ip=novo_ip(REDE_RECIFE)))

    assert pontos(corpo, "VIAGEM_IMPOSSIVEL") == 40
    assert regra(corpo, "VIAGEM_IMPOSSIVEL")["data_origin"] == "ip_location"


def test_gps_em_sao_paulo_e_ip_em_recife_soma_30():
    corpo = analisa(pix(Pagador(), Recebedor(), 5000, nova_base().isoformat(), gps=SAO_PAULO_GPS,
                        ip=novo_ip(REDE_RECIFE)))

    assert pontos(corpo, "GEO_IP_DIVERGENTE") == 30


def test_ip_em_lisboa_dispara_ambiente_incoerente():
    corpo = analisa(pix(Pagador(), Recebedor(), 5000, nova_base().isoformat(), gps=None, ip=novo_ip(REDE_LISBOA)))

    assert pontos(corpo, "AMBIENTE_INCOERENTE") == 20


def test_gps_em_lisboa_dispara_ambiente_incoerente():
    corpo = analisa(pix(Pagador(), Recebedor(), 5000, nova_base().isoformat(), gps=LISBOA_GPS))

    assert regra(corpo, "AMBIENTE_INCOERENTE")["raw_points"] == 20


def test_fuso_de_noronha_nao_e_alerta():
    base = nova_base()
    data = f"{base.date().isoformat()}T14:00:00-02:00"

    corpo = analisa(pix(Pagador(), Recebedor(), 5000, data))

    assert not disparou(corpo, "AMBIENTE_INCOERENTE")
    assert corpo["metadata"]["signals"]["utc_offset_minutes"] == -120


def test_ip_desconhecido_aprende_pelo_gps_do_historico():
    rede, hoje = _rede_desconhecida(), nova_base()
    for indice in range(3):
        analisa(pix(Pagador(), Recebedor(), 5000, (hoje - timedelta(hours=indice + 1)).isoformat(),
                    gps=RECIFE_GPS, ip=f"{rede}.{indice + 10}"))

    corpo = analisa(pix(Pagador(), Recebedor(), 5000, hoje.isoformat(), gps=None, ip=f"{rede}.99"))

    assert corpo["metadata"]["signals"]["ip_location_source"] == "learned"


def test_sem_gps_e_ip_desconhecido_deixam_a_viagem_nao_avaliavel():
    pagador, hoje = Pagador(), nova_base()
    analisa(pix(pagador, Recebedor(), 5000, hoje.isoformat()))

    corpo = analisa(pix(pagador, Recebedor(), 5000, (hoje + timedelta(minutes=15)).isoformat(), gps=None,
                        ip=f"{_rede_desconhecida()}.5"))

    assert regra(corpo, "VIAGEM_IMPOSSIVEL")["evaluation"] == "not_evaluable"


def test_aparelho_novo_e_viagem_impossivel_pedem_facial_document():
    pagador, hoje = Pagador(), nova_base()
    _com_historico(pagador, hoje)
    analisa(pix(pagador, Recebedor(), 5000, hoje.isoformat()))

    corpo = analisa(pix(pagador, Recebedor(), 5000, (hoje + timedelta(minutes=15)).isoformat(), gps=RECIFE_GPS,
                        aparelho="dvc-ladrao-" + pagador.conta))

    assert regra(corpo, "VIAGEM_IMPOSSIVEL")["authentication_floor"] == "facial_document"
    assert corpo["metadata"]["authentication"]["level"] == "facial_document"


def test_aparelho_de_tres_titulares_soma_25_sem_rejeitar():
    aparelho, hoje = f"dvc-familia-{random.randint(0, 10**9)}", nova_base()
    for indice in range(2):
        analisa(pix(Pagador(), Recebedor(), 5000, (hoje - timedelta(days=indice + 1)).isoformat(), aparelho=aparelho))

    corpo = analisa(pix(Pagador(), Recebedor(), 5000, hoje.isoformat(), aparelho=aparelho))

    assert pontos(corpo, "APARELHO_COMPARTILHADO") == 25
    assert corpo["status"] != "rejected"


def test_cinco_titulares_no_mesmo_ip_soma_15():
    ip, hoje = f"{_rede_desconhecida()}.77", nova_base()
    for indice in range(4):
        analisa(pix(Pagador(), Recebedor(), 5000, (hoje - timedelta(minutes=indice + 1)).isoformat(), ip=ip))

    corpo = analisa(pix(Pagador(), Recebedor(), 5000, hoje.isoformat(), ip=ip))

    assert pontos(corpo, "IP_COMPARTILHADO") == 15


def test_aparelho_sem_cadastro_acima_de_200_pede_facial():
    # Res. BCB 403/2024: aparelho nunca usado pelo cliente fica em R$ 200 por
    # Pix; acima disso, precisa de cadastro (a verificacao).
    hoje, pagador = nova_base(), Pagador()
    _com_historico(pagador, hoje)

    corpo = analisa(pix(pagador, Recebedor(), 25000, hoje.isoformat(), aparelho=f"dvc-{random.randint(0, 10**9)}"))

    assert disparou(corpo, "APARELHO_NAO_CADASTRADO")
    assert corpo["status"] == "two_factor_required"


def test_pessoa_fisica_pela_api_com_aparelho_sem_cadastro_pede_facial():
    # Pela api, o aparelho da empresa e o sistema dela. A pessoa fisica que
    # sempre usou o app e aparece pela api e a credencial dela num iniciador
    # de pagamento: a regra do aparelho vale para ela.
    hoje, pagador = nova_base(), Pagador()
    _com_historico(pagador, hoje)

    corpo = analisa(pix(pagador, Recebedor(), 65000, hoje.isoformat(), aparelho=f"dvc-{random.randint(0, 10**9)}",
                        canal="api", gps=None))

    assert disparou(corpo, "APARELHO_NAO_CADASTRADO")
    assert corpo["status"] == "two_factor_required"


def test_empresa_pela_api_com_aparelho_novo_nao_cai_na_regra_do_aparelho():
    hoje, empresa = nova_base(), Pagador(pj=True)
    _com_historico(empresa, hoje)

    corpo = analisa(pix(empresa, Recebedor(pj=True), 65000, hoje.isoformat(),
                        aparelho=f"dvc-{random.randint(0, 10**9)}", canal="api", gps=None))

    assert not disparou(corpo, "APARELHO_NAO_CADASTRADO")


def test_aparelho_sem_cadastro_ate_200_passa_mas_o_dia_soma_ate_1000():
    # Um destino so: seis destinos novos no dia ja pediriam a verificacao pela
    # DISPERSAO_DE_SAIDA, antes de o dia somar R$ 1.000 no aparelho.
    hoje, pagador, recebedor = nova_base(), Pagador(), Recebedor()
    _com_historico(pagador, hoje)
    novo = f"dvc-{random.randint(0, 10**9)}"
    corpos = [analisa(pix(pagador, recebedor, 19000, (hoje + timedelta(minutes=20 * i)).isoformat(), aparelho=novo))
              for i in range(6)]

    assert not disparou(corpos[0], "APARELHO_NAO_CADASTRADO")
    assert disparou(corpos[5], "APARELHO_NAO_CADASTRADO")  # 6 x R$ 190 = R$ 1.140 no dia


def test_aparelho_confirmado_numa_verificacao_fica_cadastrado():
    hoje, pagador = nova_base(), Pagador()
    _com_historico(pagador, hoje)
    novo = f"dvc-{random.randint(0, 10**9)}"
    primeiro = pix(pagador, Recebedor(), 25000, hoje.isoformat(), aparelho=novo)
    paga(primeiro)  # pede a facial, e o cliente confirma: o aparelho fica cadastrado

    corpo = analisa(pix(pagador, Recebedor(), 25000, (hoje + timedelta(hours=1)).isoformat(), aparelho=novo))

    assert not disparou(corpo, "APARELHO_NAO_CADASTRADO")


def test_ip_de_operadora_na_rede_de_sempre_nao_soma():
    # CGNAT: seis clientes da mesma operadora, cada um no IP de sempre,
    # pagando um amigo de sempre as 21h. Antes, do quinto em diante levava
    # NOTURNO 25 + IP_COMPARTILHADO 15 = 40 e a facial.
    hoje = nova_base().replace(hour=21, minute=0)
    ip = f"{_rede_desconhecida()}.88"
    corpos = []
    for indice in range(6):
        amigo, cliente = Recebedor(), Pagador()
        cliente.ip = ip
        historico(cliente, [150000] * 3, hoje - timedelta(days=40), timedelta(days=3), recebedor=amigo)
        corpos.append(analisa(pix(cliente, amigo, 150000, (hoje + timedelta(minutes=indice)).isoformat())))

    assert not any(disparou(corpo, "IP_COMPARTILHADO") for corpo in corpos)
    assert all(corpo["status"] == "approved" for corpo in corpos)


def _cliente_estabelecido(hoje):
    pagador = Pagador()
    historico(pagador, [28000, 29000, 30000, 31000, 32000, 28000, 29000, 30000, 31000, 32000],
              hoje - timedelta(days=6), timedelta(hours=12), recebedores_novos=True)
    return pagador


def test_ruptura_de_contexto_pede_facial_document_sem_somar_pontos():
    # Perfil moderado (R$ 800 contra mediana de R$ 300: +30) e aparelho novo
    # (+20) somam 50, que sozinho pediria so a facial. A ruptura nao soma
    # nada e sobe o nivel para facial e documento.
    hoje = nova_base()
    pagador = _cliente_estabelecido(hoje)

    corpo = analisa(pix(pagador, Recebedor(), 80000, hoje.isoformat(), aparelho="dvc-outro-" + pagador.conta))

    ruptura = regra(corpo, "RUPTURA_DE_CONTEXTO")
    assert ruptura["evaluation"] == "triggered"
    assert ruptura["raw_points"] == 0
    assert corpo["metadata"]["risk_score"] == 50
    assert corpo["metadata"]["authentication"]["level"] == "facial_document"
    assert corpo["metadata"]["scenario"] == "conta_tomada"


def test_ruptura_nao_reduz_uma_rejeicao():
    hoje = nova_base()
    pagador = _cliente_estabelecido(hoje)

    corpo = analisa(pix(pagador, Recebedor(), 2500000, hoje.isoformat(), aparelho="dvc-outro-" + pagador.conta))

    assert disparou(corpo, "RUPTURA_DE_CONTEXTO")
    assert corpo["status"] == "rejected"


def test_ruptura_nao_dispara_so_com_a_reserva_da_velocity():
    hoje = nova_base()
    pagador = Pagador()
    historico(pagador, [5000] * 10, hoje - timedelta(days=6), timedelta(hours=12), recebedores_novos=True)
    aparelho = "dvc-outro-" + pagador.conta

    corpos = [analisa(pix(pagador, Recebedor(), 5000, (hoje + timedelta(seconds=30 * i)).isoformat(),
                          aparelho=aparelho)) for i in range(3)]

    assert disparou(corpos[-1], "VELOCITY")
    assert not disparou(corpos[-1], "RUPTURA_DE_CONTEXTO")


def test_gps_ausente_nao_conta_como_localizacao_diferente_na_ruptura():
    hoje = nova_base()
    pagador = _cliente_estabelecido(hoje)

    corpo = analisa(pix(pagador, Recebedor(), 80000, hoje.isoformat(), gps=None))

    assert disparou(corpo, "PERFIL")
    assert not disparou(corpo, "RUPTURA_DE_CONTEXTO")
