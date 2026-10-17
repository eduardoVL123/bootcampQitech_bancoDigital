from datetime import timedelta
from statistics import median

from sqlalchemy import text

from database import Context

LEARNED_WINDOW_DAYS = 30
LEARNED_MIN_POINTS = 3


class IpLocationRepository:
    """Onde fica um IP: primeiro a tabela de faixas, depois o que o motor aprendeu.

    A tabela `ip_range_location` tem, no hackathon, faixas de documentacao
    com lugares ficticios (mock); em producao receberia uma base real. Quando
    a faixa nao esta la, o motor usa a mediana do GPS dos Pix anteriores da
    mesma rede (/24): se tres Pix daquela rede vieram de Campinas, a rede
    fica em Campinas. O mapa cresce sozinho.
    """

    def __init__(self, context: Context) -> None:
        self.session = context.db_session

    def from_table(self, ip: str):
        return self.session.execute(text(
            "SELECT latitude, longitude, country FROM ip_range_location "
            "WHERE network >>= CAST(:ip AS inet) ORDER BY masklen(network) DESC LIMIT 1"
        ), {"ip": ip}).first()

    def learned(self, network: str, moment):
        linhas = self.session.execute(text(
            "SELECT latitude, longitude FROM pix_analysis "
            "WHERE ip_network = CAST(:network AS cidr) AND latitude IS NOT NULL "
            "AND transaction_date > :inicio AND transaction_date <= :fim"
        ), {"network": network, "inicio": moment - timedelta(days=LEARNED_WINDOW_DAYS), "fim": moment}).all()
        if len(linhas) < LEARNED_MIN_POINTS:
            return None
        return (median(float(l.latitude) for l in linhas), median(float(l.longitude) for l in linhas))
