from datetime import timedelta

from sqlalchemy import text

from database import Context

LEARNED_WINDOW_DAYS = 30
LEARNED_MIN_POINTS = 3
LEARNED_MAX_POINTS = 200


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
        """A mediana do GPS dos ultimos Pix da rede, calculada no Postgres.

        Antes, todas as linhas com GPS da /24 em 30 dias vinham para o Python
        so para tirar a mediana: numa rede de operadora, milhares de linhas
        por Pix, e era a consulta mais pesada do banco. Agora o Postgres faz a
        conta (percentile_cont(0.5) e a mesma mediana do statistics.median,
        com a media dos dois do meio quando o numero e par) sobre os
        LEARNED_MAX_POINTS pontos mais novos da janela. O indice parcial
        pix_analysis_ip_network ja traz latitude e longitude, entao a leitura
        nem passa pela tabela. Onde fica uma rede muda pouco: 200 pontos
        recentes dizem isso tao bem quanto 20 mil.
        """
        linha = self.session.execute(text(
            "SELECT count(*), percentile_cont(0.5) WITHIN GROUP (ORDER BY latitude), "
            "percentile_cont(0.5) WITHIN GROUP (ORDER BY longitude) FROM ("
            "SELECT latitude::float8 AS latitude, longitude::float8 AS longitude FROM pix_analysis "
            "WHERE ip_network = CAST(:network AS cidr) AND latitude IS NOT NULL "
            "AND transaction_date > :inicio AND transaction_date <= :fim "
            "ORDER BY transaction_date DESC LIMIT :maximo) AS pontos"
        ), {"network": network, "inicio": moment - timedelta(days=LEARNED_WINDOW_DAYS), "fim": moment,
            "maximo": LEARNED_MAX_POINTS}).first()
        if linha[0] < LEARNED_MIN_POINTS:
            return None
        return float(linha[1]), float(linha[2])
