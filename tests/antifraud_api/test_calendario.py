"""O calendario do proprio cliente: pagamentos grandes concentrados numa
janela de dias do mes, aprendida dos meses anteriores. E uma das referencias
do PERFIL (a fase do mes).

Versao enxuta: so o dia do mes, com tolerancia de 2 dias. Sem dia util nem
feriado."""
from datetime import timedelta

from tests.utils.pix import Pagador, Recebedor, analisa, disparou, nova_base, paga, pix


def _mes_anterior(data, meses):
    ano, mes = data.year, data.month - meses
    while mes < 1:
        ano, mes = ano - 1, mes + 12
    return data.replace(year=ano, month=mes)


def _rotina(pagador, hoje, meses=3):
    senhorio, conta_de_luz = Recebedor(), Recebedor(pj=True)
    for atras in range(meses, 0, -1):
        mes = _mes_anterior(hoje, atras)
        paga(pix(pagador, senhorio, 250000, mes.replace(day=5, hour=10).isoformat()))
        paga(pix(pagador, conta_de_luz, 120000, mes.replace(day=6, hour=10).isoformat()))
        for dia in (12, 15, 18, 25):
            paga(pix(pagador, Recebedor(), 5000, mes.replace(day=dia, hour=13).isoformat()))


def _hoje(dia):
    return nova_base().replace(day=dia, hour=14, minute=0)


def test_dentro_da_janela_o_perfil_compara_com_a_fase_do_mes():
    pagador, hoje = Pagador(), _hoje(5)
    _rotina(pagador, hoje, meses=5)

    corpo = analisa(pix(pagador, Recebedor(), 250000, (hoje + timedelta(minutes=1)).isoformat()))

    # Contra as saidas gerais (a maioria de R$ 50), R$ 2.500 dispararia o
    # perfil. Contra a fase do mes (os pagamentos grandes dos dias 5 e 6),
    # e normal.
    assert not disparou(corpo, "PERFIL")
