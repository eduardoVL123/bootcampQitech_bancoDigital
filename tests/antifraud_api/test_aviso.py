"""O aviso ao pagador junto da verificacao (`metadata.authentication.payer_warning`).

Contra o golpe em que o dono da conta, enganado, faz o Pix, a facial nao
protege: ele passa. O que protege e a informacao na hora, e o app a mostra
junto da verificacao. O texto nao expoe dado do recebedor.
"""
from datetime import timedelta

from tests.utils.pix import Pagador, Recebedor, analisa, disparou, nova_base, pix, regra

OUTRO_BANCO = "00000001"


def _aviso(corpo):
    return corpo["metadata"]["authentication"].get("payer_warning")


def _piso_do_destino_novo(corpo):
    return regra(corpo, "DESTINO_NOVO")["authentication_floor"]


def test_conta_segura_no_proprio_cpf_em_outro_banco_pede_verificacao_com_aviso():
    # A falsa central manda "proteger o saldo" numa conta aberta ha 2 horas,
    # no nome da propria vitima, em outro banco. Reprovar toda transferencia
    # alta para conta nova no proprio CPF barraria quem so troca de banco.
    hoje, vitima = nova_base(), Pagador()
    conta_segura = Recebedor(documento=vitima.documento, aberta_em=hoje - timedelta(hours=2), participante=OUTRO_BANCO)

    corpo = analisa(pix(vitima, conta_segura, 800000, hoje.isoformat()))

    assert corpo["status"] == "two_factor_required"
    assert _aviso(corpo)["code"] == "safe_account"
    assert "conta segura" in _aviso(corpo)["message"]


def test_falso_parente_com_conta_de_3_horas_pede_facial_com_aviso():
    # "Troquei de numero, me faz um Pix?": R$ 700 para uma conta aberta ha 3
    # horas, que o pagador nunca pagou.
    hoje = nova_base()

    corpo = analisa(pix(Pagador(), Recebedor(aberta_em=hoje - timedelta(hours=3)), 70000, hoje.isoformat()))

    assert _piso_do_destino_novo(corpo) == "facial"
    assert corpo["status"] == "two_factor_required"
    assert _aviso(corpo)["code"] == "new_payee_account"


def test_pix_pequeno_para_conta_de_3_horas_passa_sem_aviso():
    hoje = nova_base()

    corpo = analisa(pix(Pagador(), Recebedor(aberta_em=hoje - timedelta(hours=3)), 15000, hoje.isoformat()))

    assert disparou(corpo, "DESTINO_NOVO")
    assert corpo["status"] == "approved"
    assert _aviso(corpo) is None


def test_concentracao_em_conta_nova_pede_verificacao_com_aviso_de_risco_no_recebedor():
    # Dez pagadores numa hora para uma conta de 10 dias: 80 no eixo destino,
    # sem denuncia, pede facial e documento. O aviso e o generico: nao diz
    # nada sobre o recebedor alem de "ha sinais de risco".
    hoje = nova_base()
    recebedor = Recebedor(aberta_em=hoje - timedelta(days=10))
    corpos = [analisa(pix(Pagador(), recebedor, 5000, (hoje + timedelta(minutes=i)).isoformat())) for i in range(10)]

    assert corpos[-1]["status"] == "two_factor_required"
    assert _aviso(corpos[-1])["code"] == "destination_risk"


def test_verificacao_so_pelo_valor_nao_tem_aviso():
    corpo = analisa(pix(Pagador(), Recebedor(), 2500000, nova_base().isoformat()))

    assert corpo["status"] == "two_factor_required"
    assert _aviso(corpo) is None
