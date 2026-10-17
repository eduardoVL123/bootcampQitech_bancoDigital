from controllers.base_controller import BaseController
from errors import ChallengeAlreadyAnswered, ChallengeNotRequired, NotFoundPixAnalysis
from models import PixStatus
from repositories import ChallengeRepository, PixRepository, WatchlistRepository
from utils.dates import parse_moment


class ChallengeController(BaseController):
    """O cliente informa o resultado do desafio que o motor pediu.

    A analise gravada nao muda: o resultado fica numa tabela propria, e o
    GET passa a mostra-lo em `metadata.challenge`. Duas consequencias:
    - `approved_by_client` vira dinheiro que saiu, e entra no montante, no
      perfil e na familiaridade dos proximos Pix;
    - `reproved_by_client` e o titular dizendo "nao fui eu". O aparelho e o
      documento destino entram na lista interna. E a unica alimentacao
      automatica da lista, e nao vem da decisao do proprio motor.
    """

    def __init__(self) -> None:
        super().__init__(__name__)
        self.pix_repo = PixRepository(self.context)
        self.challenge_repo = ChallengeRepository(self.context)
        self.watchlist_repo = WatchlistRepository(self.context)

    def answer(self, pix_id: str, payload: dict):
        analysis = self.pix_repo.get_by_pix_id(pix_id)
        if analysis is None:
            raise NotFoundPixAnalysis(pix_id)
        if analysis.status.enumerator != PixStatus.TWO_FACTOR_REQUIRED:
            raise ChallengeNotRequired(pix_id, analysis.status.enumerator.lower())

        resultado = payload["challenge_result"]
        existente = self.challenge_repo.get(analysis.id)
        if existente is not None:
            if existente.result != resultado:
                raise ChallengeAlreadyAnswered(pix_id, existente.result)
            return analysis, existente

        momento = parse_moment(payload["event_date"])
        registro = self.challenge_repo.create(analysis.id, resultado, momento)
        if resultado == "reproved_by_client":
            self.watchlist_repo.add_client_report("device", analysis.device_id,
                                                  f"challenge-{analysis.analysis_key}-device", momento)
            self.watchlist_repo.add_client_report("document", analysis.destination_document,
                                                  f"challenge-{analysis.analysis_key}-document", momento)
        self.session.commit()
        return analysis, registro
