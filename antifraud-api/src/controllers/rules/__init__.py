"""As regras do motor, na ordem do README.

A ordem importa so para as regras que leem o resultado de outras: a
RUPTURA_DE_CONTEXTO, por exemplo, vem depois das tres que ela combina.
"""
from controllers.rules.limite_por_pix import LimitePorPix
from controllers.rules.noturno import Noturno
from controllers.rules.geo_ausente import GeoAusente
from controllers.rules.mesma_titularidade import MesmaTitularidade
from controllers.rules.velocity import Velocity
from controllers.rules.limite_do_cliente import LimiteDoCliente
from controllers.rules.aumento_pendente import AumentoPendente
from controllers.rules.montante_24h import Montante24h
from controllers.rules.fatiamento import Fatiamento
from controllers.rules.sondagem_de_limite import SondagemDeLimite

RULES = [
    LimitePorPix(),
    Velocity(),
    Montante24h(),
    Fatiamento(),
    SondagemDeLimite(),
    LimiteDoCliente(),
    AumentoPendente(),
    Noturno(),
    GeoAusente(),
    MesmaTitularidade(),
]
