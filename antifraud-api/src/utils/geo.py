import ipaddress
import math

EARTH_RADIUS_KM = 6371.0

# Um retangulo em volta do Brasil, de Chui a Roraima e do Acre a Joao
# Pessoa. Nao e a fronteira: e um corte barato para "claramente fora".
BRAZIL_BOX = {"lat_min": -34.0, "lat_max": 5.3, "lon_min": -74.0, "lon_max": -34.8}


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Distancia em km entre dois pontos da superficie da Terra."""
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    delta_phi = math.radians(lat2 - lat1)
    delta_lambda = math.radians(lon2 - lon1)
    a = math.sin(delta_phi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(delta_lambda / 2) ** 2
    return 2 * EARTH_RADIUS_KM * math.asin(math.sqrt(a))


def in_brazil(latitude: float, longitude: float) -> bool:
    return (
        BRAZIL_BOX["lat_min"] <= latitude <= BRAZIL_BOX["lat_max"]
        and BRAZIL_BOX["lon_min"] <= longitude <= BRAZIL_BOX["lon_max"]
    )


def ip_network(ip: str) -> str:
    """A rede do IP: o /24 no IPv4 e o /48 no IPv6.

    E a "vizinhanca" do endereco. Operadoras trocam o ultimo octeto o tempo
    todo, entao comparar redes, e nao IPs, diz se o cliente mudou de lugar
    e nao so de endereco.
    """
    endereco = ipaddress.ip_address(ip)
    prefixo = 24 if endereco.version == 4 else 48
    return str(ipaddress.ip_network(f"{ip}/{prefixo}", strict=False))
