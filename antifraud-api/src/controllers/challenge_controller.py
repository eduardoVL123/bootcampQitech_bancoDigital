from datetime import datetime, timedelta, timezone

from psycopg2 import errorcodes
from sqlalchemy.exc import IntegrityError

from constants import TIME_SKEW_SECONDS
from controllers.base_controller import BaseController
from errors import (
    ChallengeAlreadyAnswered, ChallengeBeforeTransaction, ChallengeNotRequired, NotFoundPixAnalysis,
    TransactionDateInTheFuture,
)
from models import PixStatus
from repositories import ChallengeRepository, HistoryRepository, PixRepository, WatchlistRepository
from utils.dates import parse_moment

# A unicidade que protege "um resultado por analise" (UNIQUE(analysis_id) em
# database/antifraud.sql). E a unica violacao que vira releitura.
ONE_RESULT_PER_ANALYSIS = "pix_challenge_result_analysis_id_key"


class ChallengeController(BaseController):
    """O cliente informa o resultado do desafio que o motor pediu.

    A analise gravada nao muda: o resultado fica numa tabela propria, e o
    GET passa a mostra-lo em `metadata.challenge`. Duas consequencias:
    - `approved_by_client` vira dinheiro que saiu a partir da event_date, e
      entra no montante, no perfil e na familiaridade dos proximos Pix;
    - `reproved_by_client` e o titular dizendo "nao fui eu". O aparelho e o
      documento destino entram na lista interna, vigentes a partir da
      event_date. E a unica alimentacao automatica da lista, e nao vem da
      decisao do proprio motor.

    A ordem:
    1. A data precisa existir (30 de fevereiro e 400), inclusive na repeticao.
    2. A analise precisa existir e ter pedido o desafio.
    3. As travas sao as da propria analise (analysis_lock_keys, com os dados
       gravados), as mesmas do POST: a resposta espera o Pix da mesma conta
       que esta sendo analisado, e duas respostas do mesmo desafio esperam
       uma a outra.
    4. Com as travas, o resultado e relido. O mesmo resultado devolve o
       registro original (sem mudar a event_date nem repetir a denuncia); o
       oposto e 409.
    5. So a primeira resposta passa pela cronologia: nao antes do Pix, nem
       alem do relogio do servidor mais a folga. Nao ha prazo maximo de
       resposta: a data historica vale para a simulacao daquela epoca.
    6. Resultado e lista interna sao gravados juntos, no mesmo commit.
    """

    def __init__(self) -> None:
        super().__init__(__name__)
        self.pix_repo = PixRepository(self.context)
        self.challenge_repo = ChallengeRepository(self.context)
        self.history_repo = HistoryRepository(self.context)
        self.watchlist_repo = WatchlistRepository(self.context)

    def answer(self, pix_id: str, payload: dict):
        resultado = payload["challenge_result"]
        momento = parse_moment(payload["event_date"])
        analysis = self.pix_repo.get_by_pix_id(pix_id)
        if analysis is None:
            raise NotFoundPixAnalysis(pix_id)
        if analysis.status.enumerator != PixStatus.TWO_FACTOR_REQUIRED:
            raise ChallengeNotRequired(pix_id, analysis.status.enumerator.lower())

        self.history_repo.lock_analysis(analysis.source_document, analysis.destination_document,
                                        analysis.source_account_id, analysis.destination_account_id,
                                        analysis.device_id)
        existente = self.challenge_repo.get(analysis.id)
        if existente is not None:
            return analysis, self._replay(pix_id, existente, resultado)

        self._check_chronology(payload["event_date"], momento, analysis.transaction_date)
        try:
            registro = self.challenge_repo.create(analysis.id, resultado, momento)
        except IntegrityError as erro:
            # Defesa: com as travas, outra resposta do mesmo desafio nao grava
            # no meio desta. Se gravou, vale a dela. O rollback solta as
            # travas, entao daqui em diante so se le.
            if getattr(erro.orig, "pgcode", None) != errorcodes.UNIQUE_VIOLATION or \
                    getattr(erro.orig.diag, "constraint_name", None) != ONE_RESULT_PER_ANALYSIS:
                raise
            self.session.rollback()
            return analysis, self._replay(pix_id, self.challenge_repo.get(analysis.id), resultado)

        if resultado == "reproved_by_client":
            self.watchlist_repo.add_client_report("device", analysis.device_id,
                                                  f"challenge-{analysis.analysis_key}-device", momento)
            self.watchlist_repo.add_client_report("document", analysis.destination_document,
                                                  f"challenge-{analysis.analysis_key}-document", momento)
        self.session.commit()
        return analysis, registro

    def _replay(self, pix_id: str, existente, resultado: str):
        if existente.result != resultado:
            raise ChallengeAlreadyAnswered(pix_id, existente.result)
        return existente

    def _check_chronology(self, event_date: str, momento: datetime, transaction_date: datetime) -> None:
        if momento < transaction_date:
            raise ChallengeBeforeTransaction(event_date, transaction_date.isoformat())
        if momento > datetime.now(timezone.utc) + timedelta(seconds=TIME_SKEW_SECONDS):
            raise TransactionDateInTheFuture(event_date, TIME_SKEW_SECONDS)
