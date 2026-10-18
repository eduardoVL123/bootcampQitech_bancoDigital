import hashlib
import ipaddress
import json
import time
from datetime import datetime, timedelta, timezone
from uuid import uuid4
from zoneinfo import ZoneInfo

from sqlalchemy.exc import IntegrityError

from constants import OWN_PARTICIPANT, TIME_SKEW_SECONDS
from controllers.base_controller import BaseController
from controllers.engine.context import NOT_TRIGGERED, PixContext, Location
from controllers.engine.decision import decide
from controllers.engine.scenario import scenario
from controllers.rules import RULES
from errors import (
    InvalidSchema, NotFoundPixAnalysis, PixIdReused, TransactionBeforeAccountOpening, TransactionDateInTheFuture,
)
from models import PixAnalysis
from repositories import (
    AccountRepository, ChallengeRepository, HistoryRepository, IpLocationRepository, PixRepository,
    PolicyRepository, ReputationRepository, WatchlistRepository,
)
from utils.document_number import has_valid_check_digits, is_legal_person, normalize_document
from utils.dates import parse_moment
from utils.geo import in_brazil, ip_network

AUTHENTICATION = {
    "none": [],
    "facial": ["facial"],
    "facial_document": ["facial", "document"],
}


class PixController(BaseController):
    """Recebe um Pix, consulta o historico, aplica as regras e grava a analise.

    A ordem dos passos e a que importa explicar:
    1. O replay e respondido antes de tudo: o mesmo id e o mesmo Pix, e
       repetir nao analisa de novo nem conta como tentativa.
    2. As datas impossiveis sao recusadas antes de gravar qualquer coisa.
    3. As contas sao criadas, e so entao as travas sao pedidas.
    4. Com as travas na mao, o replay e conferido de novo (outro pedido com
       o mesmo id pode ter terminado enquanto este esperava), e o historico
       e lido: ele ja contem o Pix que segurava a trava.
    5. Regras, decisao, cenario, e o commit na ultima linha, que solta as
       travas.
    """

    def __init__(self) -> None:
        super().__init__(__name__)
        self.pix_repo = PixRepository(self.context)
        self.account_repo = AccountRepository(self.context)
        self.history_repo = HistoryRepository(self.context)
        self.ip_location_repo = IpLocationRepository(self.context)
        self.policy_repo = PolicyRepository(self.context)
        self.challenge_repo = ChallengeRepository(self.context)
        self.reputation_repo = ReputationRepository(self.context)
        self.watchlist_repo = WatchlistRepository(self.context)

    def get(self, pix_id: str) -> PixAnalysis:
        analysis = self.pix_repo.get_by_pix_id(pix_id)
        if analysis is None:
            raise NotFoundPixAnalysis(pix_id)
        return analysis

    def challenge_of(self, analysis: PixAnalysis):
        return self.challenge_repo.get(analysis.id)

    def analyze(self, payload: dict) -> tuple:
        """Devolve (analise, ja_existia). O resource traduz em 201 ou 200."""
        inicio = time.perf_counter()
        canonical = self._canonical(payload)
        request_hash = hashlib.sha256(json.dumps(canonical, sort_keys=True, separators=(",", ":")).encode()).hexdigest()

        existente = self.pix_repo.get_by_pix_id(payload["id"])
        if existente is not None:
            return self._replay(existente, request_hash), True

        moment = parse_moment(payload["transaction_date"])
        self._check_dates(payload, moment)
        ip = self._check_ip(payload["source"]["ip"])

        policy = self.policy_repo.get_current()
        params = policy.parameters
        fuso = ZoneInfo(params["timezone"])

        origem = payload["source_account"]
        destino = payload["destination_account"]
        source_document = normalize_document(origem["owner"]["document_number"])
        destination_document = normalize_document(destino["owner"]["document_number"])
        # As contas sao criadas em ordem fixa (a da chave unica), e nao
        # "origem, depois destino". O INSERT de uma conta nova segura a chave
        # dela ate o commit: com A -> B e B -> A chegando juntos, as duas
        # contas da casa e nunca vistas, cada pedido criava a sua origem e
        # esperava a do outro. Era um deadlock ANTES das travas consultivas,
        # que so protegem o que vem depois delas.
        pedidos = {
            "source": (OWN_PARTICIPANT, origem["branch"], origem["account_number"],
                       parse_moment(origem["opening_date"]), source_document),
            "destination": (destino["participant"], destino["branch"], destino["account_number"],
                            parse_moment(destino["opening_date"]), destination_document),
        }
        contas = {}
        for lado, argumentos in sorted(pedidos.items(), key=lambda item: item[1][:3]):
            contas[lado] = self.account_repo.get_or_create(*argumentos)
        source_account, destination_account = contas["source"], contas["destination"]

        device_id = payload["source"]["device_id"]
        # O IP fica de fora das travas de proposito: atras de um CGNAT de
        # operadora, milhares de clientes dividem o mesmo IP, e travar por ele
        # enfileirava todos. A unica regra que conta por IP (IP_COMPARTILHADO,
        # +15) aceita errar por um num pico simultaneo.
        self.history_repo.lock([
            f"payer:{source_document}",
            f"payee:{destination_document}",
            f"account:{destination_account.id}",
            f"device:{device_id}",
        ])

        existente = self.pix_repo.get_by_pix_id(payload["id"])
        if existente is not None:
            return self._replay(existente, request_hash), True

        network = ip_network(ip)
        gps = None
        if payload["source"].get("geolocation"):
            local = payload["source"]["geolocation"]
            gps = Location(float(local["latitude"]), float(local["longitude"]), "gps",
                           "BR" if in_brazil(local["latitude"], local["longitude"]) else None)
        ip_location = self._locate_ip(ip, network, moment)

        ctx = PixContext(
            pix_id=payload["id"], amount=int(payload["amount"]), moment=moment,
            local_moment=moment.astimezone(fuso), source_account=source_account,
            destination_account=destination_account, source_document=source_document,
            destination_document=destination_document, device_id=device_id,
            channel=payload["source"]["channel"], ip=ip, network=network, gps=gps,
            ip_location=ip_location, history=self.history_repo,
            reputation=self.reputation_repo, watchlist=self.watchlist_repo,
        )
        ctx.cache["params"] = params

        resultados = []
        for regra in RULES:
            resultado = regra.evaluate(ctx, params)
            ctx.results[resultado.rule] = resultado
            resultados.append(resultado)

        decisao = decide(resultados, params)
        cenario, candidatos = scenario(ctx, decisao)
        metadata = self._metadata(ctx, policy, decisao, cenario, candidatos, resultados, inicio)

        analysis = PixAnalysis(
            analysis_key=str(uuid4()), pix_id=payload["id"], request_hash=request_hash,
            status_id=self.pix_repo.get_status(decisao.status).id, risk_score=decisao.score,
            authentication_level=decisao.level, scenario=cenario, reason=decisao.reason,
            source_account_id=source_account.id, destination_account_id=destination_account.id,
            source_document=source_document, destination_document=destination_document,
            amount=ctx.amount, transaction_date=moment, device_id=device_id, channel=ctx.channel,
            ip=ip, ip_network=network,
            latitude=gps.latitude if gps else None, longitude=gps.longitude if gps else None,
            ip_latitude=ip_location.latitude if ip_location else None,
            ip_longitude=ip_location.longitude if ip_location else None,
            ip_location_source=ip_location.source if ip_location else "unknown",
            policy_id=policy.id, metadata_=metadata,
        )
        try:
            self.pix_repo.create(analysis)
        except IntegrityError:
            # Outro pedido com o mesmo id gravou primeiro. A analise dele e a
            # resposta, como num replay.
            self.session.rollback()
            existente = self.pix_repo.get_by_pix_id(payload["id"])
            if existente is None:
                raise
            return self._replay(existente, request_hash), True

        self.session.commit()
        return analysis, False

    def _replay(self, existente: PixAnalysis, request_hash: str) -> PixAnalysis:
        if existente.request_hash != request_hash:
            raise PixIdReused(existente.pix_id)
        return existente

    def _canonical(self, payload: dict) -> dict:
        """O pedido na forma que define "o mesmo Pix": documentos so em digitos."""
        canonical = json.loads(json.dumps(payload))
        for lado in ("source_account", "destination_account"):
            dono = canonical[lado]["owner"]
            dono["document_number"] = normalize_document(dono["document_number"])
        return canonical

    def _check_dates(self, payload: dict, moment: datetime) -> None:
        agora = datetime.now(timezone.utc)
        if moment > agora + timedelta(seconds=TIME_SKEW_SECONDS):
            raise TransactionDateInTheFuture(payload["transaction_date"], TIME_SKEW_SECONDS)
        for lado in ("source_account", "destination_account"):
            if parse_moment(payload[lado]["opening_date"]) > moment:
                raise TransactionBeforeAccountOpening(lado)

    def _check_ip(self, ip: str) -> str:
        try:
            return str(ipaddress.ip_address(ip))
        except ValueError:
            raise InvalidSchema(f"source.ip: '{ip}' is not a valid IPv4 or IPv6 address")

    def _locate_ip(self, ip: str, network: str, moment: datetime):
        linha = self.ip_location_repo.from_table(ip)
        if linha is not None:
            return Location(float(linha.latitude), float(linha.longitude), "mock", linha.country)
        aprendido = self.ip_location_repo.learned(network, moment)
        if aprendido is not None:
            latitude, longitude = aprendido
            return Location(latitude, longitude, "learned", "BR" if in_brazil(latitude, longitude) else None)
        return None

    def _metadata(self, ctx, policy, decisao, cenario, candidatos, resultados, inicio) -> dict:
        # As regras que nao dispararam ficam so pelo codigo: era a frase de
        # cada uma, numa linha por regra (37 por Pix), que fazia a gravacao
        # pesar 4 vezes a analise (docs/testes/antifraude-escala.md).
        regras, nao_dispararam = [], []
        for resultado in resultados:
            if resultado.evaluation == NOT_TRIGGERED:
                nao_dispararam.append(resultado.rule)
                continue
            item = {
                "rule": resultado.rule, "evaluation": resultado.evaluation, "axis": resultado.axis,
                "family": resultado.family, "raw_points": resultado.raw_points,
                "effective_points": resultado.effective_points, "correlated": resultado.correlated,
                "hard_block": resultado.hard_block, "authentication_floor": resultado.floor,
                "detail": resultado.detail, "data_origin": resultado.data_origin,
                "evidence_ids": resultado.evidence_ids,
            }
            item.update(resultado.extra)
            regras.append(item)

        reputacao = ctx.result("REPUTACAO_EXTERNA")
        return {
            "policy_version": policy.version,
            "risk_score": decisao.score,
            "risk_axes": decisao.axes,
            "reason": decisao.reason,
            "reason_description": decisao.reason_description,
            "authentication": {
                "level": decisao.level,
                "required_checks": AUTHENTICATION[decisao.level],
                "execution": "required_not_executed" if decisao.level != "none" else "not_required",
            },
            "scenario": cenario,
            "scenario_candidates": candidatos,
            "rules": regras,
            "rules_not_triggered": nao_dispararam,
            "signals": self._signals(ctx),
            "reputation": (reputacao.extra.get("reputation") if reputacao else None)
            or {"provider": "mock_bureau", "is_mock": True, "signal": "not_evaluated"},
            "latency_ms": round((time.perf_counter() - inicio) * 1000, 1),
        }

    def _signals(self, ctx) -> dict:
        def idade(conta) -> float:
            return round((ctx.moment - conta.opening_date).total_seconds() / 86400, 1)

        offset = ctx.moment.utcoffset()
        return {
            "payer_type": "PJ" if is_legal_person(ctx.source_document) else "PF",
            "payee_type": "PJ" if is_legal_person(ctx.destination_document) else "PF",
            "source_document_check_digit_valid": has_valid_check_digits(ctx.source_document),
            "destination_document_check_digit_valid": has_valid_check_digits(ctx.destination_document),
            "source_account_age_days": idade(ctx.source_account),
            "destination_account_age_days": idade(ctx.destination_account),
            "utc_offset_minutes": int(offset.total_seconds() // 60) if offset is not None else None,
            "ip_location_source": ctx.ip_location.source if ctx.ip_location else "unknown",
            "local_time": ctx.local_moment.strftime("%Y-%m-%d %H:%M"),
        }
