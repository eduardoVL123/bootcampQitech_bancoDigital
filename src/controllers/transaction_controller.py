import hashlib
import json

from sqlalchemy.exc import IntegrityError

from controllers.base_controller import BaseController
from controllers.posting_controller import PostingController
from errors import (
    IdempotencyKeyReused,
    MissingIdempotencyKey,
    NotFoundAccount,
    TransactionShapeInvalid,
)
from models import Account
from repositories import PostingRepository, TransactionRepository


class TransactionController(BaseController):
    """Decide a regra e PEDE o posting. Nunca escreve um centavo.

    O que move dinheiro e o livro, e ele mora no PostingController.
    Aqui ficam as perguntas de negocio: que tipo e este, quais contas
    entram, quanto e a tarifa de hoje.
    """

    def __init__(self) -> None:
        super().__init__(__name__)
        self.transaction_repo = TransactionRepository(self.context)
        self.posting_repo = PostingRepository(self.context)
        self.posting_controller = PostingController()

    def create(self, idempotency_key: str, payload: dict):
        """Devolve (transacao, ja_existia). O resource traduz em 201 ou 200."""
        if not idempotency_key:
            raise MissingIdempotencyKey()

        request_hash = self._hash(payload)

        existente = self.transaction_repo.get_by_idempotency_key(idempotency_key)
        if existente:
            return self._mesma_ou_conflito(existente, idempotency_key, request_hash)

        origem, destino = self._resolve_accounts(payload)
        politica = self.transaction_repo.get_current_fee_policy()
        tarifa = politica.transfer_fee_cents if payload["type"] == "TRANSFER" else 0

        self._lock_accounts(origem, destino)

        try:
            transaction = self.transaction_repo.create(
                {
                    "idempotency_key": idempotency_key,
                    "request_hash": request_hash,
                    "type": payload["type"],
                    "fee_policy_id": politica.id if payload["type"] == "TRANSFER" else None,
                    "origin_account_id": origem.id if origem else None,
                    "destination_account_id": destino.id if destino else None,
                    "amount": payload["amount"],
                    "fee_amount": tarifa,
                }
            )
        except IntegrityError:
            # Outro pedido com a mesma chave chegou primeiro. O INSERT
            # esperou o COMMIT dele e so entao estourou o UNIQUE: agora
            # a transacao dele existe e e a resposta certa.
            self.session.rollback()
            existente = self.transaction_repo.get_by_idempotency_key(idempotency_key)
            if not existente:
                raise
            return self._mesma_ou_conflito(existente, idempotency_key, request_hash)

        # A transferencia inteira cabe num COMMIT so: o cabecalho, os
        # quatro lancamentos e os dois saldos. Por isso o posting e
        # aplicado SEM commit, e quem fecha e esta funcao.
        self.posting_controller.apply_in_current_transaction(
            {
                "posting_key": transaction.transaction_key,
                "type": payload["type"],
                "entries": self._build_entries(payload, origem, destino, tarifa),
            },
            transaction_id=transaction.id,
        )

        self.transaction_repo.mark_completed(transaction)
        self.session.commit()
        return transaction, False

    def _lock_accounts(self, origem, destino) -> None:
        """Trava as contas ANTES de gravar o cabecalho da transacao.

        O motivo e sutil e custou um deadlock para aparecer. A FK de
        transaction para account faz o proprio INSERT do cabecalho
        pegar um KEY SHARE nas duas contas citadas. Se a trava forte
        viesse so depois, duas transferencias para o mesmo destino
        segurariam cada uma o KEY SHARE daquela linha e as duas
        pediriam o upgrade para FOR UPDATE: isso fecha um ciclo, e o
        Postgres mata uma das duas com deadlock. O cliente receberia
        500 numa operacao que deveria apenas esperar a vez.

        Ordem crescente de id nao basta por si: ela resolve o ciclo
        entre duas travas fortes, nao o upgrade de uma fraca que a FK
        pegou antes. Pedindo FOR UPDATE primeiro, o KEY SHARE da FK ja
        esta contido na trava que a transacao tem.

        So conta de cliente entra: conta tecnica tem balance nulo,
        nao tem linha de saldo para disputar, e travar a de tarifa
        serializaria toda transferencia do sistema.
        """
        ids = sorted(
            {
                conta.id
                for conta in (origem, destino)
                if conta is not None and conta.balance is not None
            }
        )
        if ids:
            self.posting_repo.get_accounts_for_update(ids)

    def get_by_key(self, transaction_key: str):
        transaction = self.transaction_repo.get_by_key(transaction_key)
        if not transaction:
            raise NotFoundAccount(transaction_key)
        return transaction

    def create_fee_policy(self, payload: dict):
        politica = self.transaction_repo.create_fee_policy(payload["transfer_fee_cents"])
        self.session.commit()
        return politica

    def _mesma_ou_conflito(self, existente, idempotency_key, request_hash):
        """Mesma chave e mesmo pedido devolve o original. Outro pedido e 409."""
        if existente.request_hash != request_hash:
            raise IdempotencyKeyReused(idempotency_key)
        return existente, True

    def _hash(self, payload: dict) -> str:
        """SHA-256 do pedido, e nao o pedido.

        Guardar o hash basta para reconhecer a repeticao, e nenhum dado
        do cliente fica guardado aqui duas vezes.
        """
        canonico = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(canonico.encode()).hexdigest()

    def _resolve_accounts(self, payload: dict):
        """Confere o formato por tipo e troca as chaves pelas linhas.

        Esta regra nao esta no banco porque um CHECK nao le o enumerator
        da tabela de lookup: ele so enxerga as colunas da propria linha.
        Por isso ela mora aqui, com teste cobrindo cada caso.
        """
        tipo = payload["type"]
        origem_key = payload.get("origin_account_key")
        destino_key = payload.get("destination_account_key")

        if tipo == "DEPOSIT":
            if origem_key:
                raise TransactionShapeInvalid("um deposito nao tem conta de origem")
            if not destino_key:
                raise TransactionShapeInvalid("um deposito precisa de conta de destino")
            return self._settlement(), self._por_chave(destino_key)

        if not origem_key or not destino_key:
            raise TransactionShapeInvalid("uma transferencia precisa de origem e de destino")
        if origem_key == destino_key:
            raise TransactionShapeInvalid("origem e destino nao podem ser a mesma conta")

        return self._por_chave(origem_key), self._por_chave(destino_key)

    def _build_entries(self, payload: dict, origem, destino, tarifa: int) -> list:
        """Os lancamentos que somam zero.

        Deposito, dois: entra na conta, sai da liquidacao.
        Transferencia, quatro: sai o valor e a tarifa da origem, entra o
        valor no destino e a tarifa na conta de espera.
        """
        valor = payload["amount"]

        if payload["type"] == "DEPOSIT":
            return [
                {"account_key": destino.account_key.strip(), "amount": valor},
                {"account_code": Account.SETTLEMENT, "amount": -valor},
            ]

        entries = [
            {"account_key": origem.account_key.strip(), "amount": -valor},
            {"account_key": destino.account_key.strip(), "amount": valor},
        ]
        if tarifa:
            entries.append({"account_key": origem.account_key.strip(), "amount": -tarifa})
            entries.append({"account_code": Account.FEE_HOLD, "amount": tarifa})
        return entries

    def _por_chave(self, account_key: str):
        conta = self.posting_repo.get_account_by_key(account_key)
        if not conta:
            raise NotFoundAccount(account_key)
        return conta

    def _settlement(self):
        return self.posting_repo.get_account_by_code(Account.SETTLEMENT)
