from datetime import datetime, timedelta, timezone

from constants import TIME_SKEW_SECONDS
from controllers.base_controller import BaseController
from errors import ChallengeAlreadyAnswered, ChallengeNotRequired, NotFoundPixAnalysis, TransactionDateInTheFuture
from models import PixStatus
from repositories import (
    ChallengeRepository, HistoryRepository, PixRepository, PolicyRepository, ReputationRepository, WatchlistRepository,
)
from utils.dates import parse_moment


class ChallengeController(BaseController):
    """O cliente informa o resultado do desafio que o motor pediu.

    A analise gravada nao muda: o resultado fica numa tabela propria, e o
    GET passa a mostra-lo em `metadata.challenge`. Duas consequencias:
    - `approved_by_client` vira dinheiro que saiu, e entra no montante, no
      perfil e na familiaridade dos proximos Pix;
    - `reproved_by_client` e o titular dizendo "nao fui eu". E a unica
      alimentacao automatica da lista interna, e nao vem da decisao do
      proprio motor. Ver _nao_fui_eu.
    """

    def __init__(self) -> None:
        super().__init__(__name__)
        self.pix_repo = PixRepository(self.context)
        self.challenge_repo = ChallengeRepository(self.context)
        self.watchlist_repo = WatchlistRepository(self.context)
        self.history_repo = HistoryRepository(self.context)
        self.policy_repo = PolicyRepository(self.context)
        self.reputation_repo = ReputationRepository(self.context)

    def answer(self, pix_id: str, payload: dict):
        analysis = self.pix_repo.get_by_pix_id(pix_id)
        if analysis is None:
            raise NotFoundPixAnalysis(pix_id)
        if analysis.status.enumerator != PixStatus.TWO_FACTOR_REQUIRED:
            raise ChallengeNotRequired(pix_id, analysis.status.enumerator.lower())

        resultado = payload["challenge_result"]
        # Duas respostas juntas para o mesmo Pix (clique duplo, retry do app):
        # sem a trava, as duas viam "sem resposta" e a segunda estourava a
        # chave unica (500). Com ela, a segunda le a primeira e responde
        # 200 (mesmo resultado) ou 409 (outro resultado).
        self.history_repo.lock([f"challenge:{analysis.id}"])
        existente = self.challenge_repo.get(analysis.id)
        if existente is not None:
            if existente.result != resultado:
                raise ChallengeAlreadyAnswered(pix_id, existente.result)
            return analysis, existente

        momento = parse_moment(payload["event_date"])
        if momento > datetime.now(timezone.utc) + timedelta(seconds=TIME_SKEW_SECONDS):
            raise TransactionDateInTheFuture(payload["event_date"], TIME_SKEW_SECONDS)
        registro = self.challenge_repo.create(analysis.id, resultado, momento)
        if resultado == "reproved_by_client":
            # Ninguem nega um Pix antes de ele acontecer: o event_date anterior
            # a ele e relogio errado do chamador, e nao pode fazer a cautelar
            # nascer vencida. Vale a data do Pix.
            self._nao_fui_eu(analysis, max(momento, analysis.transaction_date))
        self.session.commit()
        return analysis, registro

    def _nao_fui_eu(self, analysis, momento) -> None:
        """O aparelho entra na lista, e o documento destino entra em cautelar.

        A cautelar e a palavra de um titular so: +40 por 24 horas, sem bloquear
        e sem espalhar suspeita pela rede. Se ninguem mais reclamar, ela vence
        sozinha e a conta fica livre. Vira fraude confirmada (bloqueio e
        ancora da rede) quando chega uma segunda fonte independente:
        - outro titular, distinto, diz "nao fui eu" para o mesmo documento nos
          30 dias seguintes. O mesmo titular reclamando duas vezes conta uma;
        - a reputacao externa (DICT ou mock) ja tinha denuncia ou marcacao de
          golpe contra ele.

        A trava e a mesma do recebedor no Pix: duas denuncias simultaneas para
        o mesmo documento se enxergam, e o Pix seguinte ja ve a cautelar.
        """
        p = self.policy_repo.get_current().parameters["REPUTACAO_INTERNA"]
        destino, chave = analysis.destination_document, analysis.analysis_key
        self.history_repo.lock([f"payee:{destino}"])
        # As duas entradas valem desde o Pix contestado, e nao so desde a
        # denuncia: quem responde dias depois nao deixa o golpista livre no
        # meio-tempo. A duracao conta da denuncia.
        desde = analysis.transaction_date
        self.watchlist_repo.add_client_report("device", analysis.device_id, f"challenge-{chave}-device", momento,
                                              hours=p["device_days"] * 24, since=desde)
        self.watchlist_repo.add_client_report("document", destino, f"challenge-{chave}-document", momento,
                                              hours=p["cautelar_hours"], reporter=analysis.source_document, since=desde)

        denunciantes = self.watchlist_repo.reporters_of(destino, momento, p["reports_window_days"])
        if len(denunciantes) >= p["min_reporters"] or self.reputation_repo.suspected(destino, momento):
            self.watchlist_repo.confirm(destino, f"confirmed-{chave}", momento, p["confirmed_days"])
