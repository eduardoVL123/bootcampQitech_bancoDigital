"""Webhook de saida (RFC 06), pela porta da frente.

O parceiro e o Mockserver, que ja sobe no compose. Nenhum teste aqui le
o banco nem importa codigo da aplicacao: o que se confere e o que o
parceiro RECEBEU, que e exatamente o que importa.
"""
import hashlib
import hmac
import json
import time
from os import environ
from uuid import UUID, uuid4

import pytest

from tests.utils import PayloadGenerator, RequestGenerator
from tests.utils.credential import token_de_cliente, token_de_operador
from tests.utils.mockserver import Mockserver, cabecalho, corpo

ROTA_DO_PARCEIRO = "/parceiro/webhook"

# O mesmo segredo que o compose passa ao worker. O teste assina por
# conta propria e compara: se o worker usasse outra chave, ou nao
# assinasse, a comparacao quebra.
SEGREDO = environ.get("WEBHOOK_SECRET", "webhook_secret_de_estudo")

# Quanto o worker espera entre uma varredura e a seguinte, mais folga.
ESPERA_MAXIMA_SEGUNDOS = 25


def cliente_com_conta(centavos: int = 0) -> tuple:
    _status, cliente = RequestGenerator.POST_customer(PayloadGenerator.create_customer_payload())
    customer_key = cliente["customer_key"]
    status, conta = RequestGenerator.POST_account({"customer_key": customer_key})
    assert status == 201, conta
    account_key = conta["account_key"]

    if centavos:
        status, deposito = RequestGenerator.POST_transaction(
            {"type": "DEPOSIT", "destination_account_key": account_key, "amount": centavos},
            idempotency_key=str(uuid4()),
            credential=token_de_operador(),
        )
        assert status == 201, deposito

    return customer_key, account_key


def transfere(dono: str, origem: str, destino: str, centavos: int) -> tuple:
    return RequestGenerator.POST_transaction(
        {
            "type": "TRANSFER",
            "origin_account_key": origem,
            "destination_account_key": destino,
            "amount": centavos,
        },
        idempotency_key=str(uuid4()),
        credential=token_de_cliente(dono),
    )


def espera_entrega(transaction_key: str, quantas: int = 1, limite=ESPERA_MAXIMA_SEGUNDOS) -> list:
    """Espera o parceiro receber `quantas` entregas desta transacao.

    O worker roda em laco, entao a entrega nao e sincrona com a
    resposta da API: o teste espera, e nao dorme um tempo fixo.
    """
    fim = time.time() + limite
    pedidos = []
    while time.time() < fim:
        pedidos = Mockserver.pedidos(
            {"payload": {"transaction_key": transaction_key}}, ROTA_DO_PARCEIRO
        )
        if len(pedidos) >= quantas:
            return pedidos
        time.sleep(0.5)
    return pedidos


def nada_chegou(transaction_key: str, segundos: float = 6) -> bool:
    """Confere que NADA chega. Tem de esperar: provar ausencia leva tempo."""
    time.sleep(segundos)
    return Mockserver.pedidos(
        {"payload": {"transaction_key": transaction_key}}, ROTA_DO_PARCEIRO
    ) == []


def limpa_a_rota_do_parceiro() -> None:
    """Esquece o que ja chegou nesta rota, e so nela.

    Preparar a conta ja gera evento: o deposito de abertura e uma
    transacao como outra qualquer. Um teste que programa uma falha
    logo depois do deposito veria a falha ser consumida pelo evento
    DELE, e nao pelo da transferencia que ele quer testar. Por isso a
    limpeza, feita so nesta rota para nao mexer no que os testes da
    onboarding programaram.
    """
    Mockserver.envia("/mockserver/clear", {"path": ROTA_DO_PARCEIRO})


def espera_a_fila_esvaziar(segundos: float = 4) -> None:
    """Deixa os eventos da preparacao serem entregues antes de comecar."""
    time.sleep(segundos)


def assinatura_esperada(pedido: dict) -> str:
    bruto = pedido.get("body")
    if isinstance(bruto, dict):
        bruto = bruto.get("string") or json.dumps(bruto.get("json"), separators=(",", ":"))
    return hmac.new(SEGREDO.encode(), bruto.encode(), hashlib.sha256).hexdigest()


class TestWebhookDelivery:
    """Cada teste comeca com a rota do parceiro limpa.

    Sem isto, o W-08 deixa uma queda de conexao programada para 99
    vezes, com prioridade alta, e ela sobrevive ao fim do pytest: o
    Mockserver e um container, nao morre entre uma rodada e outra. Na
    rodada seguinte, um teste que espera 202 levaria a queda do teste
    anterior e falharia sem ter nada a ver com isso. Foi exatamente o
    que aconteceu aqui antes desta limpeza existir.
    """

    @pytest.fixture(autouse=True)
    def rota_limpa(self):
        limpa_a_rota_do_parceiro()

    def test_w01_transferencia_entrega_o_evento_ao_parceiro(self):
        Mockserver.programa(ROTA_DO_PARCEIRO, {}, 200, {"ok": True})
        dono, ana = cliente_com_conta(100000)
        _b, bruno = cliente_com_conta()

        status, transacao = transfere(dono, ana, bruno, 10000)
        assert status == 201, transacao

        pedidos = espera_entrega(transacao["transaction_key"])

        assert len(pedidos) == 1, "o parceiro tinha de receber a transferencia"
        evento = corpo(pedidos[0])
        assert evento["event_type"] == "transaction.success"
        assert evento["payload"]["transaction_key"] == transacao["transaction_key"]
        assert evento["payload"]["amount"] == 10000

    def test_w02_o_evento_vai_assinado(self):
        """Sem assinatura, qualquer um forja um webhook nosso no parceiro."""
        Mockserver.programa(ROTA_DO_PARCEIRO, {}, 200, {"ok": True})
        dono, ana = cliente_com_conta(100000)
        _b, bruno = cliente_com_conta()
        _status, transacao = transfere(dono, ana, bruno, 10000)

        pedidos = espera_entrega(transacao["transaction_key"])
        assert pedidos, "nada chegou ao parceiro"

        assinatura = cabecalho(pedidos[0], "X-Banco-Signature")
        assert assinatura, "faltou o cabecalho de assinatura"
        assert assinatura == assinatura_esperada(pedidos[0])

    def test_w03_evento_traz_identificador_proprio(self):
        """O event_id e o que permite ao parceiro descartar repeticao."""
        Mockserver.programa(ROTA_DO_PARCEIRO, {}, 200, {"ok": True})
        dono, ana = cliente_com_conta(100000)
        _b, bruno = cliente_com_conta()
        _status, transacao = transfere(dono, ana, bruno, 10000)

        pedidos = espera_entrega(transacao["transaction_key"])
        assert pedidos, "nada chegou ao parceiro"

        evento = corpo(pedidos[0])
        UUID(evento["event_id"])
        assert cabecalho(pedidos[0], "X-Banco-Event-Id") == evento["event_id"]

    def test_w04_parceiro_que_responde_202_nao_recebe_de_novo(self):
        """202 e sucesso. Tratar so 200 como sucesso faz o parceiro
        receber o mesmo evento cinco vezes e depois ser dado como
        perdido."""
        Mockserver.programa(ROTA_DO_PARCEIRO, {}, 202, {"aceito": True})
        dono, ana = cliente_com_conta(100000)
        _b, bruno = cliente_com_conta()
        _status, transacao = transfere(dono, ana, bruno, 10000)

        pedidos = espera_entrega(transacao["transaction_key"])
        assert len(pedidos) == 1, "202 e sucesso: nao pode haver segunda tentativa"

        time.sleep(8)
        de_novo = Mockserver.pedidos(
            {"payload": {"transaction_key": transacao["transaction_key"]}}, ROTA_DO_PARCEIRO
        )
        assert len(de_novo) == 1, f"o evento foi reenviado {len(de_novo)} vezes"

    def test_w05_parceiro_fora_do_ar_recebe_depois(self):
        """A primeira tentativa cai, a segunda entrega.

        E o que o recuo exponencial existe para fazer: nao desistir no
        primeiro erro, e nao martelar o parceiro que ja esta com
        problema.
        """
        Mockserver.programa(ROTA_DO_PARCEIRO, {}, 200, {"ok": True})
        dono, ana = cliente_com_conta(100000)
        _b, bruno = cliente_com_conta()
        espera_a_fila_esvaziar()

        limpa_a_rota_do_parceiro()
        Mockserver.derruba_a_conexao(ROTA_DO_PARCEIRO, {}, vezes=1)
        Mockserver.programa(ROTA_DO_PARCEIRO, {}, 200, {"ok": True})

        _status, transacao = transfere(dono, ana, bruno, 10000)

        pedidos = espera_entrega(transacao["transaction_key"], quantas=2)

        assert len(pedidos) == 2, (
            "esperava duas chegadas: a que caiu e a que entregou, "
            f"veio {len(pedidos)}"
        )

    def test_w08_parceiro_sumido_vira_fila_morta(self):
        """Depois do limite, para de tentar. Nao tenta para sempre.

        Com o recuo de 2 segundos do compose, as cinco tentativas levam
        2 mais 4 mais 8 mais 16: por isso este teste e o mais lento do
        arquivo.
        """
        Mockserver.programa(ROTA_DO_PARCEIRO, {}, 200, {"ok": True})
        dono, ana = cliente_com_conta(100000)
        _b, bruno = cliente_com_conta()
        espera_a_fila_esvaziar()

        limpa_a_rota_do_parceiro()
        Mockserver.derruba_a_conexao(ROTA_DO_PARCEIRO, {}, vezes=99)

        _status, transacao = transfere(dono, ana, bruno, 10000)

        pedidos = espera_entrega(transacao["transaction_key"], quantas=5, limite=45)
        assert len(pedidos) == 5, f"esperava cinco tentativas, veio {len(pedidos)}"

        time.sleep(10)
        depois = Mockserver.pedidos(
            {"payload": {"transaction_key": transacao["transaction_key"]}}, ROTA_DO_PARCEIRO
        )
        assert len(depois) == 5, f"continuou tentando depois do limite: {len(depois)}"

    def test_w06_transacao_recusada_nao_gera_evento(self):
        """O Outbox provado pela porta da frente: sem COMMIT, sem evento.

        A transferencia e recusada por saldo, entao nada e gravado. Se o
        evento fosse publicado fora da transacao do banco, o parceiro
        seria avisado de uma transferencia que nunca aconteceu.
        """
        Mockserver.programa(ROTA_DO_PARCEIRO, {}, 200, {"ok": True})
        dono, ana = cliente_com_conta(1000)
        _b, bruno = cliente_com_conta()

        status, recusa = transfere(dono, ana, bruno, 500000)

        assert status == 409, recusa
        assert nada_chegou(recusa.get("transaction_key", "nao-existe"))
        assert Mockserver.pedidos({"event_type": "transaction.success"}, ROTA_DO_PARCEIRO) is not None

    def test_w07_deposito_tambem_avisa(self):
        Mockserver.programa(ROTA_DO_PARCEIRO, {}, 200, {"ok": True})
        _dono, conta = cliente_com_conta()

        status, transacao = RequestGenerator.POST_transaction(
            {"type": "DEPOSIT", "destination_account_key": conta, "amount": 50000},
            idempotency_key=str(uuid4()),
            credential=token_de_operador(),
        )
        assert status == 201, transacao

        pedidos = espera_entrega(transacao["transaction_key"])
        assert len(pedidos) == 1
        assert corpo(pedidos[0])["event_type"] == "transaction.success"
