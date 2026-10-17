"""As regras do motor, na ordem do README.

A ordem importa so para as regras que leem o resultado de outras: a
RUPTURA_DE_CONTEXTO, por exemplo, vem depois das tres que ela combina.
"""
from controllers.rules.perfil import Perfil
from controllers.rules.perfil_sem_historico import PerfilSemHistorico
from controllers.rules.limite_por_pix import LimitePorPix
from controllers.rules.montante_diario_atipico import MontanteDiarioAtipico
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
    Perfil(),
    PerfilSemHistorico(),
    LimitePorPix(),
    Velocity(),
    Montante24h(),
    Fatiamento(),
    MontanteDiarioAtipico(),
    SondagemDeLimite(),
    LimiteDoCliente(),
    AumentoPendente(),
    Noturno(),
    GeoAusente(),
    MesmaTitularidade(),
]
