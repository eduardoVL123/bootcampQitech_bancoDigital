"""As regras do motor, na ordem do README.

A ordem importa so para as regras que leem o resultado de outras: a
RUPTURA_DE_CONTEXTO, por exemplo, vem depois das tres que ela combina.
"""
from controllers.rules.limite_por_pix import LimitePorPix
from controllers.rules.noturno import Noturno
from controllers.rules.geo_ausente import GeoAusente
from controllers.rules.mesma_titularidade import MesmaTitularidade

RULES = [
    LimitePorPix(),
    Noturno(),
    GeoAusente(),
    MesmaTitularidade(),
]
