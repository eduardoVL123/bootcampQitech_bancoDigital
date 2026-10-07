from sqlalchemy import BigInteger, CHAR, Column, DateTime, ForeignKey, UniqueConstraint, func
from sqlalchemy.orm import relationship

from models.account import Account
from models.base import Base


class LedgerEntry(Base):
    """O livro: cada movimento de dinheiro numa conta, com sinal.

    Append-only: ha uma trigger no banco recusando UPDATE e DELETE.
    Corrigir e lancar outro por cima, nunca editar o que ja aconteceu.

    `balance_after` e `sequence` sao nulos em conta tecnica, amarrados
    por um CHECK. Isso faz do lancamento tecnico um INSERT puro, que nao
    le nada da linha da conta: e o que impede a conta de tarifa de virar
    fila de espera do banco inteiro. Extrato existe so para conta de
    cliente, que e o unico extrato que alguem pede.

    O extrato pagina por `sequence`, nunca por offset: o livro recebe
    escrita o tempo todo, e offset duplicaria itens entre paginas.
    """

    __tablename__ = "ledger_entry"

    id = Column(BigInteger, primary_key=True)
    entry_key = Column(CHAR(36), nullable=False, unique=True)
    posting_id = Column(BigInteger, ForeignKey("posting.id"), nullable=False)
    account_id = Column(BigInteger, ForeignKey(Account.id), nullable=False)
    amount = Column(BigInteger, nullable=False)
    balance_after = Column(BigInteger, nullable=True)
    sequence = Column(BigInteger, nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())

    __table_args__ = (
        UniqueConstraint("entry_key"),
        UniqueConstraint("account_id", "sequence"),
    )

    posting = relationship("Posting", back_populates="entries")
    account = relationship("Account", foreign_keys=[account_id], lazy="selectin")
