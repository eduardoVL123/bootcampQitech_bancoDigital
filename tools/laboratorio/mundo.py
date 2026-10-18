"""O mundo simulado: relogio, cidades, pessoas e episodios.

Um episodio e uma historia curta (um golpe ou um cliente comum) contada em
eventos: os Pix e os pedidos de limite que a API recebe. Cada evento leva o
rotulo do que ele e de verdade, e o rotulo nunca vai para a API.

Duas fontes de acaso, separadas de proposito:
  a semente do episodio decide a estrutura (valores, horarios, quantos Pix),
  entao repetir a semente repete a historia;
  as identidades (CPF, conta, aparelho, IP) vem de outra fonte e sao sempre
  novas, para que uma rodada nao esbarre no historico gravado pela anterior.
"""

import random
import statistics
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

from laboratorio import pix_base as pix_utils

BRT = timezone(timedelta(hours=-3))

# So estas tres cidades tem IP no seed da API. Inventar outra cidade faria a
# API resolver o IP para o lugar errado e acusar uma divergencia que nao existe.
CIDADES = {
    "sp": (pix_utils.IP_SP, pix_utils.GPS_SP),
    "recife": (pix_utils.IP_RECIFE, pix_utils.GPS_RECIFE),
    "lisboa": (pix_utils.IP_LISBOA, pix_utils.GPS_LISBOA),
    "sydney": (pix_utils.IP_SYDNEY, pix_utils.GPS_SYDNEY),  # fora do seed: a API nao sabe onde fica
}

# Decisoes em ordem de severidade. "erro" (resposta que nao e decisao) fica fora.
ORDEM = {"approved": 0, "facial": 1, "facial_document": 2, "rejected": 3}

# Referencias regulatorias usadas so para apontar descumprimento. Confira a
# vigencia no site do Banco Central antes de tratar como regra do projeto.
LIMITE_NOTURNO_PF = 100000  # R$ 1.000 entre 20h e 6h, Pix entre pessoas fisicas (IN BCB 512/2024, na redacao da IN BCB 669/2025)
LIMITE_APARELHO_NOVO = 20000  # R$ 200 por Pix em aparelho nunca usado (Res. BCB 403/2024)
LIMITE_DIARIO_APARELHO_NOVO = 100000  # R$ 1.000 por dia nesse aparelho


@dataclass
class Pessoa:
    apelido: str
    documento: str
    conta: dict  # branch, account_number e opening_date, como no contrato
    participante: str
    aparelho: str
    cidade: str
    casa: dict
    pj: bool = False
    canal: str = "app"
    usa_gps: bool = True
    valores: list = field(default_factory=list)
    conhecidos: list = field(default_factory=list)
    aparelhos: set = field(default_factory=set)

    def mediana(self) -> int:
        return int(statistics.median(self.valores)) if self.valores else 5000

    def como_origem(self) -> dict:
        return {**self.conta, "owner": {"document_number": self.documento}}

    def como_destino(self, conta: dict = None) -> dict:
        return {"participant": self.participante, **(conta or self.conta), "owner": {"document_number": self.documento}}


@dataclass
class Evento:
    id: str
    quando: datetime
    metodo: str
    caminho: str
    corpo: dict
    rotulo: str  # legitimo, fraude, autoprotecao ou neutro (preparo do golpista que nao lesa ninguem)
    papel: str  # rotina (historico), alvo (o que se mede) ou preparo
    perfil: str
    episodio: str
    valor: int = 0
    contido_por: str = None  # fraude: a decisao minima que segura o golpe; autoprotecao: a que protege
    aceitavel_ate: str = None  # legitimo: a decisao mais dura que ainda nao e erro
    regulatorio: str = None  # regra do BCB que bloquearia este Pix, se houver
    confirma: bool = False  # se a API pedir selfie, o titular passa (approved_by_client)


class Mundo:
    def __init__(self, tag: str, hoje: str, variar_ip: bool = True):
        self.tag = tag
        self.hoje = datetime.strptime(hoje, "%Y-%m-%d").replace(tzinfo=BRT)
        self.variar_ip = variar_ip
        self._acaso = random.Random()
        self._seq = 0

    def _proximo(self) -> int:
        self._seq += 1
        return self._seq

    def novo_id(self, prefixo: str = "lab") -> str:
        return f"{prefixo}-{self.tag}-{self._proximo():05d}"

    def novo_aparelho(self) -> str:
        return self.novo_id("dev")

    def documento(self, pj: bool = False) -> str:
        while True:
            if pj:
                doc = pix_utils.cnpj_com_digitos(f"{self._acaso.randrange(10 ** 8):08d}0001")
            else:
                doc = pix_utils.cpf_com_digitos(f"{self._acaso.randrange(10 ** 9):09d}")
            if pix_utils.documento_valido(doc):
                return doc

    def ip(self, cidade: str) -> str:
        base, _ = CIDADES[cidade]
        if not self.variar_ip:
            return base
        if ":" in base:
            return f"{base.rsplit(':', 1)[0]}:{self._acaso.randrange(1, 0xffff):x}"
        return f"{base.rsplit('.', 1)[0]}.{self._acaso.randrange(2, 255)}"

    def pessoa(self, apelido: str, pj: bool = False, idade_conta_dias: int = 1500, cidade: str = "sp",
               canal: str = "app", usa_gps: bool = True, documento: str = None) -> Pessoa:
        _, centro = CIDADES[cidade]
        aberta = (self.hoje - timedelta(days=idade_conta_dias)).replace(hour=9).isoformat()
        aparelho = self.novo_aparelho()
        return Pessoa(
            apelido=apelido,
            documento=documento or self.documento(pj),
            conta={"branch": f"{self._acaso.randrange(1, 10000):04d}",
                   "account_number": f"{self._acaso.randrange(10 ** 8):08d}", "opening_date": aberta},
            # Todo mundo e cliente da casa: so assim a API liga o que uma conta
            # recebeu com o que ela paga depois (repasse, laranja, rede).
            participante=pix_utils.PARTICIPANTE_CASA,
            aparelho=aparelho,
            cidade=cidade,
            casa={"latitude": round(centro["latitude"] + self._acaso.uniform(-0.03, 0.03), 5),
                  "longitude": round(centro["longitude"] + self._acaso.uniform(-0.03, 0.03), 5)},
            pj=pj,
            canal=canal,
            usa_gps=usa_gps,
            aparelhos={aparelho},
        )


def _janela_noturna(quando: datetime):
    """A noite a que o horario pertence (20h ate 6h), ou None de dia."""
    if quando.hour >= 20:
        return quando.date()
    if quando.hour < 6:
        return (quando - timedelta(days=1)).date()
    return None


class Episodio:
    def __init__(self, mundo: Mundo, perfil, botoes: dict, semente: int, fator_valor: float = 1.0):
        self.mundo = mundo
        self.perfil = perfil
        self.botoes = dict(botoes)
        self.semente = semente
        self.fator_valor = fator_valor
        self.acaso = random.Random(f"{perfil.nome}:{semente}")
        self.id = mundo.novo_id("ep")
        self.eventos = []
        self._noite = {}
        self._aparelho_novo_dia = {}

    # -- tempo e lugar -------------------------------------------------

    def momento(self, dias_atras: float = 0, hora: str = "12:00", espalhar_min: int = 0) -> datetime:
        hh, mm = (int(x) for x in hora.split(":"))
        base = self.mundo.hoje - timedelta(days=dias_atras) + timedelta(hours=hh, minutes=mm)
        if espalhar_min:
            base += timedelta(minutes=self.acaso.randrange(espalhar_min + 1))
        return base

    def gps_em(self, lugar, raio: float = 0.005) -> dict:
        centro = lugar if isinstance(lugar, dict) else CIDADES[lugar][1]
        return {"latitude": round(centro["latitude"] + self.acaso.uniform(-raio, raio), 5),
                "longitude": round(centro["longitude"] + self.acaso.uniform(-raio, raio), 5)}

    def valor(self, minimo: int, maximo: int, passo: int = 100) -> int:
        return self.acaso.randrange(minimo, maximo + 1, passo)

    def sequencia(self, inicio: datetime, n: int, de_min: int, ate_min: int) -> list:
        """n momentos a partir de inicio, com intervalo sorteado entre de_min e ate_min minutos."""
        momentos, atual = [], inicio
        for _ in range(n):
            momentos.append(atual)
            atual = atual + timedelta(minutes=self.acaso.randint(de_min, ate_min))
        return momentos

    # -- gente -----------------------------------------------------------

    def pessoa(self, apelido: str, **kwargs) -> Pessoa:
        return self.mundo.pessoa(apelido, **kwargs)

    def historico(self, pessoa: Pessoa, n: int = 12, faixa: tuple = (3000, 9000), contrapartes: int = 3,
                  de_dias: int = 40, ate_dias: int = 1, horas: tuple = (8, 20), conhecidos: list = None) -> list:
        """Pix aprovaveis do passado, que dao a pessoa um habito."""
        if conhecidos is None:
            conhecidos = [self.pessoa(f"{pessoa.apelido}-contraparte", pj=self.acaso.random() < 0.5)
                          for _ in range(contrapartes)]
        dias = list(range(ate_dias, de_dias + 1))
        escolhidos = self.acaso.sample(dias, n) if n <= len(dias) else [self.acaso.choice(dias) for _ in range(n)]
        for dia in sorted(escolhidos, reverse=True):
            hora = f"{self.acaso.randrange(*horas):02d}:{self.acaso.randrange(60):02d}"
            self.pix(pessoa, self.acaso.choice(conhecidos), self.valor(*faixa), self.momento(dia, hora),
                     rotulo="legitimo", papel="rotina")
        pessoa.conhecidos.extend(c for c in conhecidos if c not in pessoa.conhecidos)
        return conhecidos

    def cliente_comum(self, apelido: str = "cliente", faixa: tuple = None, n: int = 14, **kwargs) -> Pessoa:
        if faixa is None:
            faixa = self.acaso.choice([(2000, 9000), (5000, 20000), (10000, 50000)])
        cliente = self.pessoa(apelido, **kwargs)
        self.historico(cliente, n=n, faixa=faixa)
        return cliente

    # -- eventos -----------------------------------------------------------

    def pix(self, origem: Pessoa, destino: Pessoa, valor: int, quando: datetime, *, rotulo: str, papel: str,
            aparelho: str = None, ip_de: str = None, ip: str = None, gps=None, canal: str = None,
            conta_destino: dict = None, contido_por: str = None, aceitavel_ate: str = None,
            golpista: bool = None) -> str:
        """Um Pix. gps None calcula sozinho, False nao manda, dict manda o que vier.

        golpista diz quem esta com o aparelho na mao. O golpista nao passa na
        selfie, entao o desafio fica sem resposta. O titular (cliente honesto,
        vitima enganada ou dono da laranja) passa e confirma. Sem valor
        explicito, e golpista quem pratica o golpe que a selfie seguraria.
        """
        if papel != "rotina":
            valor = valor * self.fator_valor
        valor = max(100, int(round(valor)))
        canal = canal or origem.canal
        aparelho = aparelho or origem.aparelho
        if gps is None:
            gps = self.gps_em(origem.casa) if canal == "app" and origem.usa_gps else False

        pix_id = self.mundo.novo_id()
        corpo = pix_utils.pix_normal(id=pix_id, amount=valor, transaction_date=quando.isoformat())
        corpo = pix_utils.mutar(corpo, "source_account", origem.como_origem())
        corpo = pix_utils.mutar(corpo, "destination_account", destino.como_destino(conta_destino))
        corpo = pix_utils.mutar(corpo, "source", {
            "device_id": aparelho, "channel": canal, "ip": ip or self.mundo.ip(ip_de or origem.cidade),
        })
        if gps:
            corpo = pix_utils.mutar(corpo, "source.geolocation", gps)
        for lado in ("source_account", "destination_account"):
            if datetime.fromisoformat(corpo[lado]["opening_date"]) > quando:
                raise ValueError(f"{self.perfil.nome}: Pix de {quando} antes da abertura da conta ({lado})")

        regulatorio = self._regulatorio(origem, destino, valor, quando, aparelho, canal)
        if rotulo == "fraude":
            contido_por = contido_por or self.perfil.contido_por
        elif rotulo == "legitimo":
            aceitavel_ate = aceitavel_ate or "approved"
        elif rotulo == "autoprotecao":
            contido_por = contido_por or self.perfil.contido_por or "facial"
            aceitavel_ate = aceitavel_ate or "facial_document"
        if golpista is None:
            golpista = rotulo == "fraude" and contido_por == "facial"
        self.eventos.append(Evento(pix_id, quando, "POST", "/pix/transaction", corpo, rotulo, papel, self.perfil.nome,
                                   self.id, valor, contido_por, aceitavel_ate, regulatorio, not golpista))
        if papel == "rotina":
            origem.valores.append(valor)
            origem.aparelhos.add(aparelho)
        return pix_id

    def _regulatorio(self, origem, destino, valor, quando, aparelho, canal):
        motivos = []
        noite = _janela_noturna(quando)
        if noite and not origem.pj and not destino.pj:
            chave = (origem.documento, noite)
            self._noite[chave] = self._noite.get(chave, 0) + valor
            if self._noite[chave] > LIMITE_NOTURNO_PF:
                motivos.append("limite noturno de R$ 1.000 entre pessoas fisicas")
        if canal == "app" and aparelho not in origem.aparelhos:
            chave = (origem.documento, aparelho, quando.date())
            self._aparelho_novo_dia[chave] = self._aparelho_novo_dia.get(chave, 0) + valor
            if valor > LIMITE_APARELHO_NOVO or self._aparelho_novo_dia[chave] > LIMITE_DIARIO_APARELHO_NOVO:
                motivos.append("aparelho novo acima de R$ 200 por Pix ou R$ 1.000 por dia")
        return "; ".join(motivos) or None
