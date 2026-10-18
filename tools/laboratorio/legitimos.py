"""Clientes de verdade, inclusive os que parecem golpe.

O alvo de cada perfil diz ate onde a API pode ir sem errar:
  aceitavel_ate "approved": qualquer atrito ja e excesso;
  "facial": pedir a selfie e razoavel;
  "facial_document": pedir documento ainda e razoavel.
Rejeitar um legitimo e sempre falso positivo, a menos que uma regra do BCB
obrigue o bloqueio (o evento marca isso sozinho, em mundo.py).
"""

from datetime import timedelta

from laboratorio.catalogo import perfil

FAIXAS = {"baixa": (2000, 9000), "media": (10000, 50000), "alta": (50000, 300000)}
HORAS = {"comercial": "14:00", "noite": "21:30", "madrugada": "02:40"}


@perfil(nome="rotina_pf", tipo="legitimo",
        descricao="Pix do dia a dia para quem a pessoa sempre paga",
        botoes={"faixa": ["baixa", "media", "alta"], "hora": ["comercial", "noite", "madrugada"]})
def rotina_pf(ep, b):
    cliente = ep.cliente_comum("cliente", faixa=FAIXAS[b["faixa"]])
    ep.pix(cliente, ep.acaso.choice(cliente.conhecidos), cliente.mediana(), ep.momento(0, HORAS[b["hora"]], 20),
           rotulo="legitimo", papel="alvo", aceitavel_ate="approved" if b["hora"] == "comercial" else "facial")


@perfil(nome="pagamento_recorrente", tipo="legitimo",
        descricao="Aluguel ou mensalidade alta para o mesmo recebedor, todo mes perto do mesmo dia",
        botoes={"meses": [3, 6, 2], "desvio_dias": [0, 2, 5], "multiplo": [30, 60, 120]})
def pagamento_recorrente(ep, b):
    cliente = ep.cliente_comum("inquilino", faixa=(3000, 9000))
    imobiliaria = ep.pessoa("imobiliaria", pj=True, idade_conta_dias=4000)
    valor = cliente.mediana() * b["multiplo"]
    for mes in range(b["meses"], 0, -1):
        dia = 30 * mes + ep.acaso.randint(-b["desvio_dias"], b["desvio_dias"])
        ep.pix(cliente, imobiliaria, valor, ep.momento(dia, "10:00", 240), rotulo="legitimo", papel="rotina")
    habito_firme = b["meses"] >= 3 and b["desvio_dias"] <= 2
    ep.pix(cliente, imobiliaria, valor, ep.momento(0, "10:00", 240), rotulo="legitimo", papel="alvo",
           aceitavel_ate="approved" if habito_firme else "facial")


@perfil(nome="pj_fornecedor", tipo="legitimo",
        descricao="Empresa que paga o mesmo fornecedor por integracao (API, sem GPS)",
        botoes={"valor": [4000000, 1500000, 9000000], "variacao_pct": [5, 25, 60], "pagamentos": [5, 3, 10]})
def pj_fornecedor(ep, b):
    empresa = ep.pessoa("empresa", pj=True, idade_conta_dias=3000, canal="api", usa_gps=False)
    fornecedor = ep.pessoa("fornecedor", pj=True, idade_conta_dias=3000)
    ep.historico(empresa, n=6, faixa=(50000, 500000))
    for i in range(b["pagamentos"]):
        dia = 3 + i * ep.acaso.randint(3, 6)
        ep.pix(empresa, fornecedor, b["valor"] * ep.acaso.uniform(0.95, 1.05), ep.momento(dia, "10:00", 60),
               rotulo="legitimo", papel="rotina")
    ep.pix(empresa, fornecedor, b["valor"] * (1 + b["variacao_pct"] / 100), ep.momento(0, "10:00", 60),
           rotulo="legitimo", papel="alvo", aceitavel_ate="approved" if b["variacao_pct"] <= 25 else "facial")


@perfil(nome="troca_de_celular", tipo="legitimo",
        descricao="Cliente trocou de celular e faz um Pix pequeno no aparelho novo",
        botoes={"valor": [8000, 15000, 20000], "contraparte": ["conhecida", "nova"]})
def troca_de_celular(ep, b):
    cliente = ep.cliente_comum("cliente", faixa=(5000, 20000))
    destino = ep.acaso.choice(cliente.conhecidos) if b["contraparte"] == "conhecida" else ep.pessoa("contraparte-nova")
    ep.pix(cliente, destino, b["valor"], ep.momento(0, "13:00", 300), aparelho=ep.mundo.novo_aparelho(),
           rotulo="legitimo", papel="alvo", aceitavel_ate="facial_document")


@perfil(nome="viajante", tipo="legitimo",
        descricao="Pix no aeroporto de SP e, horas depois, outro na cidade de destino",
        botoes={"destino": ["recife", "lisboa"], "horas_depois": [8, 5, 3], "valor": ["habitual", "alto"],
                "gps": ["ligado", "desligado"]})
def viajante(ep, b):
    cliente = ep.cliente_comum("viajante", faixa=(5000, 30000))
    saida = ep.momento(0, "06:30", 30)
    ep.pix(cliente, ep.acaso.choice(cliente.conhecidos), cliente.mediana(), saida, rotulo="legitimo", papel="alvo")
    horas = b["horas_depois"] + (10 if b["destino"] == "lisboa" else 0)
    hotel = ep.pessoa("hotel", pj=True, idade_conta_dias=2500, cidade=b["destino"])
    gps = ep.gps_em(b["destino"]) if b["gps"] == "ligado" else False
    valor = cliente.mediana() * (1 if b["valor"] == "habitual" else 8)
    ep.pix(cliente, hotel, valor, saida + timedelta(hours=horas), ip_de=b["destino"], gps=gps,
           rotulo="legitimo", papel="alvo", aceitavel_ate="facial")


@perfil(nome="compra_grande_planejada", tipo="legitimo",
        descricao="Entrada de carro ou reforma: valor muito acima do habito, para empresa, de dia",
        botoes={"multiplo": [10, 30, 80], "idade_conta_destino_dias": [3000, 400, 45], "hora": ["comercial", "noite"]})
def compra_grande_planejada(ep, b):
    cliente = ep.cliente_comum("comprador", faixa=(5000, 30000))
    loja = ep.pessoa("loja", pj=True, idade_conta_dias=b["idade_conta_destino_dias"])
    ep.pix(cliente, loja, cliente.mediana() * b["multiplo"], ep.momento(0, HORAS[b["hora"]], 30),
           rotulo="legitimo", papel="alvo", aceitavel_ate="facial_document")


@perfil(nome="autonomo_recebedor", tipo="legitimo",
        descricao="Manicure, diarista ou feirante que recebe de muitos clientes no mesmo dia",
        botoes={"clientes": [8, 15, 30], "janela_horas": [8, 3, 1], "idade_conta_dias": [1500, 200, 20]})
def autonomo_recebedor(ep, b):
    autonomo = ep.pessoa("autonomo", idade_conta_dias=b["idade_conta_dias"])
    inicio = ep.momento(0, "09:00")
    for i in range(b["clientes"]):
        pagador = ep.cliente_comum(f"cliente-{i}", n=5, faixa=(3000, 15000))
        quando = inicio + timedelta(minutes=ep.acaso.randrange(b["janela_horas"] * 60))
        ep.pix(pagador, autonomo, ep.valor(5000, 25000, 500), quando,
               rotulo="legitimo", papel="alvo", aceitavel_ate="facial")


@perfil(nome="racha_da_conta", tipo="legitimo",
        descricao="Amigos pagam quem acertou a conta do bar, todos em poucos minutos, de noite",
        botoes={"amigos": [5, 8, 12], "ja_pagaram_antes": [True, False], "hora": ["23:30", "01:10", "21:00"]})
def racha_da_conta(ep, b):
    anfitriao = ep.cliente_comum("anfitriao", faixa=(3000, 12000), n=8)
    inicio = ep.momento(0, b["hora"])
    for i in range(b["amigos"]):
        amigo = ep.cliente_comum(f"amigo-{i}", n=6, faixa=(3000, 12000))
        if b["ja_pagaram_antes"]:
            ep.pix(amigo, anfitriao, ep.valor(3000, 9000), ep.momento(ep.acaso.randint(5, 30), "20:00", 120),
                   rotulo="legitimo", papel="rotina")
        ep.pix(amigo, anfitriao, ep.valor(4000, 15000), inicio + timedelta(minutes=ep.acaso.randrange(20)),
               rotulo="legitimo", papel="alvo", aceitavel_ate="facial")


@perfil(nome="familia_noturna", tipo="legitimo",
        descricao="Pai ou mae manda dinheiro ao filho tarde da noite",
        botoes={"multiplo": [1, 5, 15], "hora": ["22:30", "01:30", "04:00"], "filho": ["conhecido", "conta_nova"]})
def familia_noturna(ep, b):
    pai = ep.cliente_comum("pai", faixa=(5000, 20000))
    filho = ep.pessoa("filho", idade_conta_dias=2000 if b["filho"] == "conhecido" else 10)
    if b["filho"] == "conhecido":
        for dia in (25, 18, 9, 3):
            ep.pix(pai, filho, ep.valor(5000, 20000), ep.momento(dia, "19:00", 120), rotulo="legitimo", papel="rotina")
    simples = b["multiplo"] == 1 and b["filho"] == "conhecido"
    ep.pix(pai, filho, pai.mediana() * b["multiplo"], ep.momento(0, b["hora"], 15),
           rotulo="legitimo", papel="alvo", aceitavel_ate="approved" if simples else "facial_document")


@perfil(nome="dia_do_pagamento", tipo="legitimo",
        descricao="No dia do salario a pessoa paga varias contas seguidas, algumas para recebedores novos",
        botoes={"contas": [5, 8, 12], "ineditas": [1, 3, 5], "janela_min": [90, 45, 20]})
def dia_do_pagamento(ep, b):
    cliente = ep.cliente_comum("assalariado", faixa=(5000, 25000))
    fixas = [ep.pessoa(f"conta-fixa-{i}", pj=True, idade_conta_dias=3000) for i in range(3)]
    for recebedor in fixas:
        for dia in (60, 30):
            ep.pix(cliente, recebedor, ep.valor(8000, 40000), ep.momento(dia, "08:30", 60), rotulo="legitimo", papel="rotina")
    ineditas = min(b["ineditas"], b["contas"])
    recebedores = [ep.pessoa(f"conta-nova-{i}", pj=True, idade_conta_dias=2000) for i in range(ineditas)]
    recebedores += [ep.acaso.choice(fixas + cliente.conhecidos) for _ in range(b["contas"] - ineditas)]
    ep.acaso.shuffle(recebedores)
    inicio = ep.momento(0, "08:00")
    for recebedor in recebedores:
        ep.pix(cliente, recebedor, ep.valor(5000, 80000), inicio + timedelta(minutes=ep.acaso.randrange(b["janela_min"])),
               rotulo="legitimo", papel="alvo", aceitavel_ate="facial")


@perfil(nome="aparelho_da_familia", tipo="legitimo",
        descricao="Casal ou familia que usa o mesmo tablet para os Pix de cada um",
        botoes={"titulares": [2, 3], "intervalo_min": [60, 10, 2]})
def aparelho_da_familia(ep, b):
    tablet = ep.mundo.novo_aparelho()
    titulares = []
    for i in range(b["titulares"]):
        titular = ep.pessoa(f"titular-{i}")
        titular.aparelho = tablet
        titular.aparelhos = {tablet}
        ep.historico(titular, n=10, faixa=(3000, 15000))
        titulares.append(titular)
    inicio = ep.momento(0, "19:30")
    for i, titular in enumerate(titulares):
        ep.pix(titular, ep.acaso.choice(titular.conhecidos), titular.mediana(),
               inicio + timedelta(minutes=i * b["intervalo_min"]), rotulo="legitimo", papel="alvo", aceitavel_ate="facial")


@perfil(nome="sem_permissao_de_gps", tipo="legitimo",
        descricao="Cliente que nunca liberou a localizacao para o app do banco",
        botoes={"multiplo": [1, 4], "hora": ["comercial", "noite"]})
def sem_permissao_de_gps(ep, b):
    cliente = ep.cliente_comum("cliente", faixa=(5000, 20000), usa_gps=False)
    simples = b["multiplo"] == 1 and b["hora"] == "comercial"
    ep.pix(cliente, ep.acaso.choice(cliente.conhecidos), cliente.mediana() * b["multiplo"],
           ep.momento(0, HORAS[b["hora"]], 30), rotulo="legitimo", papel="alvo",
           aceitavel_ate="approved" if simples else "facial")


# ----------------------------------------------------------------------
# Emergencias e vida fora do Brasil
#
# O Pix nao atravessa fronteira: mandar dinheiro para fora e um Pix em reais
# para uma empresa de remessa aqui (que converte e envia), ou para a conta
# brasileira de quem esta la. E quem esta la usa o app com IP e GPS de fora,
# de dia no fuso dele, que pode ser madrugada em Brasilia.
# ----------------------------------------------------------------------

@perfil(nome="emergencia_familia_no_exterior", tipo="legitimo",
        descricao="Filho e esposa na Australia, emergencia medica: de madrugada aqui o pai manda R$ 20 mil "
                  "e depois compra o remedio numa farmacia brasileira",
        botoes={"como_envia": ["empresa_de_remessa", "conta_do_filho"], "valor": [2000000, 500000, 5000000],
                "hora": ["02:00", "23:30"], "remedio": [True, False]})
def emergencia_familia_no_exterior(ep, b):
    pai = ep.cliente_comum("pai", faixa=(5000, 30000))
    filho = ep.pessoa("filho")
    for dia in (40, 25, 12):
        ep.pix(pai, filho, ep.valor(20000, 80000), ep.momento(dia, "19:00", 120), rotulo="legitimo", papel="rotina")
    if b["como_envia"] == "empresa_de_remessa":
        destino = ep.pessoa("empresa-de-remessa", pj=True, idade_conta_dias=3000)
    else:
        # PF para PF de madrugada esbarra no limite noturno do BCB: o evento
        # marca isso sozinho, e ai rejeitar nao conta como erro da API.
        destino = filho
    inicio = ep.momento(0, b["hora"], 10)
    ep.pix(pai, destino, b["valor"], inicio, rotulo="legitimo", papel="alvo", aceitavel_ate="facial_document")
    if b["remedio"]:
        farmacia = ep.pessoa("farmacia-24h", pj=True, idade_conta_dias=2500)
        ep.pix(pai, farmacia, ep.valor(15000, 90000), inicio + timedelta(minutes=ep.acaso.randint(15, 40)),
               rotulo="legitimo", papel="alvo", aceitavel_ate="facial")


@perfil(nome="brasileiro_no_exterior", tipo="legitimo",
        descricao="Brasileiro na Australia usa o app de dia por la, que e madrugada em Brasilia, com IP que a API nao conhece",
        botoes={"dias_la": [1, 10], "valor": ["habitual", "alto"], "destino": ["conhecido", "novo"],
                "gps": ["ligado", "desligado"]})
def brasileiro_no_exterior(ep, b):
    cliente = ep.pessoa("brasileiro-no-exterior")
    # O historico em SP termina antes da viagem, senao a propria massa teria
    # uma viagem impossivel.
    ep.historico(cliente, n=14, faixa=(5000, 30000), de_dias=45, ate_dias=b["dias_la"] + 1)
    # Sydney esta 14 horas a frente de Brasilia em outubro: 01h30 aqui sao 15h30 la.
    for dia in range(b["dias_la"] - 1, 0, -1):
        ep.pix(cliente, ep.acaso.choice(cliente.conhecidos), ep.valor(3000, 15000), ep.momento(dia, "01:30", 180),
               ip_de="sydney", gps=ep.gps_em("sydney", 0.03), rotulo="legitimo", papel="rotina")
    if b["destino"] == "conhecido":
        destino = ep.acaso.choice(cliente.conhecidos)
    else:
        destino = ep.pessoa("loja-online", pj=True, idade_conta_dias=2000)
    valor = cliente.mediana() * (1 if b["valor"] == "habitual" else 8)
    gps = ep.gps_em("sydney", 0.03) if b["gps"] == "ligado" else False
    ep.pix(cliente, destino, valor, ep.momento(0, "02:30", 120), ip_de="sydney", gps=gps,
           rotulo="legitimo", papel="alvo", aceitavel_ate="facial")


@perfil(nome="emergencia_hospital_madrugada", tipo="legitimo",
        descricao="Madrugada no pronto-socorro: caucao do hospital, farmacia e corrida de volta",
        botoes={"caucao": [1500000, 4000000, 800000], "hora": ["03:00", "23:00"], "hospital": ["novo", "ja_usado"]})
def emergencia_hospital_madrugada(ep, b):
    cliente = ep.cliente_comum("acompanhante", faixa=(5000, 30000))
    hospital = ep.pessoa("hospital", pj=True, idade_conta_dias=5000)
    if b["hospital"] == "ja_usado":
        ep.pix(cliente, hospital, ep.valor(20000, 60000), ep.momento(30, "10:00", 240), rotulo="legitimo", papel="rotina")
    inicio = ep.momento(0, b["hora"], 20)
    ep.pix(cliente, hospital, b["caucao"], inicio, rotulo="legitimo", papel="alvo", aceitavel_ate="facial_document")
    farmacia = ep.pessoa("farmacia", pj=True, idade_conta_dias=2500)
    ep.pix(cliente, farmacia, ep.valor(8000, 60000), inicio + timedelta(minutes=ep.acaso.randint(30, 90)),
           rotulo="legitimo", papel="alvo", aceitavel_ate="facial")
    corrida = ep.pessoa("app-de-corrida", pj=True, idade_conta_dias=3000)
    ep.pix(cliente, corrida, ep.valor(3000, 9000), inicio + timedelta(minutes=ep.acaso.randint(100, 150)),
           rotulo="legitimo", papel="alvo", aceitavel_ate="facial")


@perfil(nome="compra_de_carro_usado", tipo="legitimo",
        descricao="Compra de carro de um particular: valor alto para uma pessoa fisica nunca paga, de dia",
        botoes={"valor": [4000000, 2000000, 8000000], "pagamento": ["sinal_e_restante", "a_vista"],
                "idade_conta_vendedor_dias": [3000, 200]})
def compra_de_carro_usado(ep, b):
    comprador = ep.cliente_comum("comprador", faixa=(10000, 50000))
    vendedor = ep.pessoa("vendedor", idade_conta_dias=b["idade_conta_vendedor_dias"])
    if b["pagamento"] == "sinal_e_restante":
        ep.pix(comprador, vendedor, b["valor"] * 0.1, ep.momento(2, "14:00", 120), rotulo="legitimo", papel="alvo",
               aceitavel_ate="facial_document")
        ep.pix(comprador, vendedor, b["valor"] * 0.9, ep.momento(0, "15:00", 60), rotulo="legitimo", papel="alvo",
               aceitavel_ate="facial_document")
    else:
        ep.pix(comprador, vendedor, b["valor"], ep.momento(0, "15:00", 60), rotulo="legitimo", papel="alvo",
               aceitavel_ate="facial_document")
