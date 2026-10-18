"""Proteger o cliente dele mesmo.

Aqui ninguem esta sendo enganado e ninguem invadiu a conta: e o proprio
titular, no aparelho dele, tomando uma decisao que pode machucar. O banco nao
deve tirar do cliente o direito de decidir, mas deve criar um momento de
pausa (a selfie, que na pratica pergunta "tem certeza?") quando o padrao foge
do habito de forma perigosa, e deve segurar o limite que o proprio cliente
escolheu para se controlar.

Por isso cada Pix medido aqui tem duas pontas:
  contido_por: a partir de onde a API protegeu (a pausa, facial; ou o
    bloqueio, quando o Pix passa do limite que o cliente mesmo pediu);
  aceitavel_ate: ate onde ela pode ir sem tirar do cliente o que e dele.
O titular passa na selfie: a pausa nao impede, so faz pensar.

Os Pix da mesma sequencia que ainda estao dentro do habito sao legitimos
comuns: proteger cedo demais e so atrito.
"""

from laboratorio.catalogo import perfil

FONTE_JOGO = "https://igamingbusiness.com/br/jogo-sustentavel/jogo-responsavel/sistema-brasileiro-de-autoexclusao-sera-lancado-ate-o-final-de-2025/"


@perfil(nome="apostas_compulsivas", tipo="autoprotecao", contido_por="facial",
        descricao="O cliente aposta, perde e manda valores cada vez maiores para a casa de apostas, muitas vezes de madrugada",
        botoes={"apostas": [8, 4, 12], "crescimento": [1.5, 1.2, 2.0], "hora": ["23:30", "02:00", "15:00"],
                "valor_inicial": [1, 3]},
        sinais=("varios Pix seguidos para o mesmo recebedor", "valores crescendo a cada Pix",
                "soma da noite varias vezes acima do habito"),
        defesa="Jogo responsavel (Lei 14.790/2023, Portaria SPA 1.231/2024) pede limite, pausa e alerta quando o padrao "
               "foge do habito. Do lado do banco: uma pausa com confirmacao quando a soma da sequencia passa varias vezes "
               "o habito, e carencia de verdade para aumento de limite pedido no meio dela.",
        ausente_no_contrato=("categoria do recebedor (casa de apostas autorizada)",
                             "autoexclusao do cliente na plataforma nacional"),
        fonte=FONTE_JOGO)
def apostas_compulsivas(ep, b):
    cliente = ep.cliente_comum("apostador", faixa=(3000, 15000))
    casa = ep.pessoa("casa-de-apostas", pj=True, idade_conta_dias=900)
    # O limite que o cliente escolhe e do BAS, que barra antes de o Pix chegar
    # ao antifraude: aqui so conta a pausa quando a sequencia foge do habito.
    alerta = cliente.mediana() * 5
    valor, gasto = cliente.mediana() * b["valor_inicial"], 0
    momentos = ep.sequencia(ep.momento(0, b["hora"], 20), b["apostas"], 4, 15)
    for quando in momentos:
        gasto += valor
        if gasto > alerta:
            ep.pix(cliente, casa, valor, quando, rotulo="autoprotecao", papel="alvo")
        else:
            ep.pix(cliente, casa, valor, quando, rotulo="legitimo", papel="alvo", aceitavel_ate="facial")
        valor *= b["crescimento"]


@perfil(nome="esvaziar_reserva_por_impulso", tipo="autoprotecao", contido_por="facial",
        descricao="Num impulso o cliente manda as economias inteiras para uma corretora de cripto ou uma 'oportunidade'",
        botoes={"multiplo": [40, 15, 80], "parcelas": [1, 3], "hora": ["03:00", "14:00"],
                "destino": ["corretora_cripto", "pessoa_nova"]},
        sinais=("valor dezenas de vezes acima do habito", "recebedor inedito", "madrugada"),
        defesa="Uma pausa com confirmacao (e, se o banco tiver, um contato de confianca avisado) quando o cliente "
               "move de uma vez muitas vezes o que costuma movimentar. Nao e bloqueio: o dinheiro e dele.",
        ausente_no_contrato=("saldo e reserva do cliente", "categoria do recebedor (corretora, exchange)"),
        fonte=FONTE_JOGO)
def esvaziar_reserva_por_impulso(ep, b):
    cliente = ep.cliente_comum("cliente", faixa=(5000, 30000))
    if b["destino"] == "corretora_cripto":
        destino = ep.pessoa("corretora", pj=True, idade_conta_dias=1500)
    else:
        destino = ep.pessoa("oportunidade", idade_conta_dias=20)
    parcela = cliente.mediana() * b["multiplo"] / b["parcelas"]
    for quando in ep.sequencia(ep.momento(0, b["hora"], 30), b["parcelas"], 3, 10):
        ep.pix(cliente, destino, parcela, quando, rotulo="autoprotecao", papel="alvo")
