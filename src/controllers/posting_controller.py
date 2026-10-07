from controllers.base_controller import BaseController
from errors import (
    AccountNotActive,
    InsufficientBalance,
    NotFoundAccount,
    PostingDoesNotSumZero,
)
from models import AccountStatus
from repositories import PostingRepository


class PostingController(BaseController):
    """A unica regra de negocio que move dinheiro.

    Um posting e um conjunto de lancamentos que SOMA ZERO, aplicado numa
    transacao ACID so. Ou todos acontecem, ou nenhum.
    """

    def __init__(self) -> None:
        super().__init__(__name__)
        self.posting_repo = PostingRepository(self.context)

    def apply(self, payload: dict):
        """Devolve (posting, ja_existia). O resource traduz em 201 ou 200.

        A ordem dos passos nao e arbitraria, e e o que vale explicar:

        1. O replay e respondido antes de tudo, sem travar nada.
        2. As contas sao resolvidas e a soma zero conferida ANTES da
           trava: sao recusas que se respondem sem incomodar ninguem.
        3. A trava vem depois, em ordem crescente de id.
        4. Saldo e estado sao conferidos DEPOIS da trava. Antes dela, o
           saldo lido e o de um instante que ja passou: outra
           transferencia pode debitar a mesma conta entre a leitura e a
           escrita, e as duas passariam na conferencia.
        5. O commit e a ultima linha, e e o que libera a trava.
        """
        posting_key = payload["posting_key"]

        existente = self.posting_repo.get_by_key(posting_key)
        if existente:
            return existente, True

        entradas = self._resolve(payload["entries"])

        total = sum(amount for _conta, amount in entradas)
        if total != 0:
            raise PostingDoesNotSumZero(total)

        ids_de_cliente = sorted(
            {conta.id for conta, _amount in entradas if conta.balance is not None}
        )
        travadas = {
            conta.id: conta
            for conta in self.posting_repo.get_accounts_for_update(ids_de_cliente)
        }

        self._check_state_and_balance(entradas, travadas)

        posting = self.posting_repo.create_posting(posting_key, payload["type"])
        for conta, amount in entradas:
            self.posting_repo.add_entry(posting.id, travadas.get(conta.id, conta), amount)

        self.session.commit()
        return posting, False

    def reconciliation(self) -> dict:
        return self.posting_repo.reconciliation()

    def _resolve(self, entries: list) -> list:
        """Troca a chave publica, ou o codigo da conta tecnica, pela linha."""
        resolvidas = []
        for entry in entries:
            if "account_key" in entry:
                conta = self.posting_repo.get_account_by_key(entry["account_key"])
                if not conta:
                    raise NotFoundAccount(entry["account_key"])
            else:
                conta = self.posting_repo.get_account_by_code(entry["account_code"])
                if not conta:
                    raise NotFoundAccount(entry["account_code"])
            resolvidas.append((conta, entry["amount"]))
        return resolvidas

    def _check_state_and_balance(self, entradas: list, travadas: dict) -> None:
        """Confere com o saldo DE AGORA, que a trava garante que nao muda.

        A conferencia e pelo total da conta, e nao lancamento a
        lancamento: numa transferencia a origem aparece duas vezes, uma
        pelo valor e outra pela tarifa, e o que importa e se ela cobre
        as duas juntas.
        """
        delta_por_conta = {}
        for conta, amount in entradas:
            delta_por_conta.setdefault(conta.id, 0)
            delta_por_conta[conta.id] += amount

        for conta_id, delta in delta_por_conta.items():
            conta = travadas.get(conta_id)
            if conta is None:
                continue  # conta tecnica: nao tem saldo nem estado a conferir

            if conta.status.enumerator != AccountStatus.ACTIVE:
                raise AccountNotActive(conta.account_key.strip(), conta.status.enumerator)

            if conta.balance + delta < 0:
                raise InsufficientBalance(conta.account_key.strip())
