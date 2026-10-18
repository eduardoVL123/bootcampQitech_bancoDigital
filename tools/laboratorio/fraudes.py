"""Tipologias de golpe, com os botoes que um golpista adaptado mexe.

contido_por e a decisao minima que de fato segura o golpe, e e o ponto que
mais engana quem mede antifraude so por "detectou ou nao":
  facial: o golpista nao tem o rosto da vitima (conta tomada de outro
    aparelho), entao pedir a selfie basta;
  rejected: quem aperta o botao e a propria vitima, enganada e muitas vezes
    ao telefone com o golpista (falsa central, falso parente, mao fantasma),
    ou e o dono da conta laranja. Ela passa na selfie. So bloquear segura.

Os textos de defesa resumem o que bancos e o BCB descrevem publicamente;
a fonte de cada tipologia esta no campo fonte.
"""

from datetime import timedelta

from laboratorio.catalogo import perfil
from laboratorio.mundo import pix_utils

FONTE_BCB_APARELHO = "https://bpmoney.com.br/negocios/pix-tera-novas-regras-de-seguranca-a-partir-de-1o-de-novembro-confira"
FONTE_BCB_NOITE = "https://www.legisweb.com.br/legislacao/?id=484165"
FONTE_LARANJA = "https://www.serasaexperian.com.br/conteudos/prevencao-a-fraude/entenda-como-o-pix-impulsiona-a-abertura-de-contas-laranjas"
FONTE_MED = "https://dock.tech/fluid/blog/banking/med-2-0/"


def _mula(ep, tipo: str, apelido: str = "mula"):
    """conta_nova: aberta ha dias. conta_antiga_alugada: conta de anos emprestada. pj_antiga: empresa de fachada."""
    if tipo == "conta_nova":
        return ep.pessoa(apelido, idade_conta_dias=ep.acaso.randint(3, 6))
    mula = ep.pessoa(apelido, pj=tipo == "pj_antiga", idade_conta_dias=ep.acaso.randint(700, 3000))
    ep.historico(mula, n=8, faixa=(2000, 9000))
    return mula


def _local(ep, vitima, modo: str) -> dict:
    longe = "recife" if vitima.cidade != "recife" else "sp"
    if modo == "outra_cidade":
        return {"ip_de": longe, "gps": ep.gps_em(longe, 0.03)}
    if modo == "ip_longe_gps_falso":
        return {"ip_de": longe, "gps": ep.gps_em(vitima.casa)}
    return {"ip_de": vitima.cidade, "gps": ep.gps_em(vitima.casa)}  # VPN na cidade da vitima e GPS falso


@perfil(nome="conta_tomada", tipo="fraude", contido_por="facial",
        descricao="Golpista com a senha da vitima (vazamento, SIM swap) entra de outro aparelho e esvazia a conta",
        botoes={"valor": [10, 3, 1], "fatias": [1, 3, 8],
                "localizacao": ["outra_cidade", "ip_longe_gps_falso", "mesma_cidade"],
                "aparelho": ["novo", "aquecido_3_dias", "aquecido_10_dias"],
                "destino": ["conta_nova", "conta_antiga_alugada"], "hora": ["03:10", "15:00"]},
        sinais=("aparelho nunca usado pela vitima", "localizacao ou IP fora do habitual", "valor fora do perfil",
                "destino inedito", "rajada de Pix em minutos"),
        defesa="Amarrar o aparelho a conta: aparelho novo so passa de R$ 200 por Pix e R$ 1.000 por dia depois de "
               "cadastro com biometria (Res. BCB 403/2024). Aparelho 'aquecido' com Pix pequenos continua novo.",
        ausente_no_contrato=("data da ultima troca de chip (API de SIM swap das operadoras)",
                             "emulador ou root no aparelho"),
        fonte=FONTE_BCB_APARELHO)
def conta_tomada(ep, b):
    vitima = ep.cliente_comum("vitima")
    aparelho = ep.mundo.novo_aparelho()
    local = _local(ep, vitima, b["localizacao"])
    dias_aquecendo = {"novo": 0, "aquecido_3_dias": 3, "aquecido_10_dias": 10}[b["aparelho"]]
    for dia in range(dias_aquecendo, 0, -1):
        ep.pix(vitima, ep.acaso.choice(vitima.conhecidos), ep.valor(1000, 5000), ep.momento(dia, "12:00", 300),
               aparelho=aparelho, rotulo="neutro", papel="preparo", golpista=True, **local)
    mula = _mula(ep, b["destino"])
    fatia = vitima.mediana() * b["valor"]
    for quando in ep.sequencia(ep.momento(0, b["hora"], 20), b["fatias"], 2, 9):
        ep.pix(vitima, mula, fatia, quando, aparelho=aparelho, rotulo="fraude", papel="alvo", **local)


@perfil(nome="mao_fantasma", tipo="fraude", contido_por="rejected",
        descricao="App de acesso remoto no celular da propria vitima: o Pix sai do aparelho e do lugar de sempre",
        botoes={"pix": [1, 3, 6], "valor_total": [20, 6, 2], "intervalo_min": [2, 10, 40],
                "destino": ["conta_nova", "conta_antiga_alugada"], "destinos_distintos": [False, True],
                "hora": ["15:00", "21:40"]},
        sinais=("valor total muito acima do perfil", "destinos ineditos", "sequencia rapida de Pix"),
        defesa="Aparelho e GPS sao os de sempre, entao so o comportamento denuncia. Bancos detectam app de acesso "
               "remoto e chamada em curso no proprio app; sem isso, segurar valor alto para recebedor inedito.",
        ausente_no_contrato=("app de acesso remoto ativo (AnyDesk, TeamViewer)", "chamada telefonica em curso",
                             "ritmo de toque e digitacao"),
        fonte="https://www.santander.com.br/blog/golpe-da-mao-fantasma")
def mao_fantasma(ep, b):
    vitima = ep.cliente_comum("vitima")
    mulas = [_mula(ep, b["destino"], f"mula-{i}") for i in range(b["pix"] if b["destinos_distintos"] else 1)]
    parcela = vitima.mediana() * b["valor_total"] / b["pix"]
    for i, quando in enumerate(ep.sequencia(ep.momento(0, b["hora"], 30), b["pix"], 1, b["intervalo_min"])):
        ep.pix(vitima, mulas[i % len(mulas)], parcela, quando, rotulo="fraude", papel="alvo")


@perfil(nome="falsa_central", tipo="fraude", contido_por="rejected",
        descricao="Falso funcionario do banco convence a vitima a mandar o saldo para uma 'conta segura'",
        botoes={"valor": [30, 10, 4], "parcelas": [1, 2, 4], "destino": ["conta_nova", "conta_antiga_alugada", "pj_antiga"],
                "hora": ["14:00", "20:30"]},
        sinais=("valor muito acima do perfil", "recebedor inedito", "parcelas seguidas para o mesmo recebedor"),
        defesa="A vitima autentica tudo. Segurar o Pix (bloqueio cautelar, que o MED 2.0 preve) e confirmar por "
               "outro canal quando o valor foge do perfil e o recebedor e inedito.",
        ausente_no_contrato=("chamada telefonica em curso", "nome do recebedor mostrado ao cliente"),
        fonte=FONTE_MED)
def falsa_central(ep, b):
    vitima = ep.cliente_comum("vitima")
    conta_segura = _mula(ep, b["destino"], "conta-segura")
    parcela = vitima.mediana() * b["valor"] / b["parcelas"]
    for quando in ep.sequencia(ep.momento(0, b["hora"], 30), b["parcelas"], 3, 15):
        ep.pix(vitima, conta_segura, parcela, quando, rotulo="fraude", papel="alvo")


@perfil(nome="falso_parente", tipo="fraude", contido_por="rejected",
        descricao="'Mae, troquei de numero': a vitima paga a conta que o falso filho indicou",
        botoes={"valor": [8, 3, 1.5], "destino": ["conta_nova", "conta_antiga_alugada"], "segundo_pedido": [True, False],
                "outras_vitimas": [6, 0, 2]},
        sinais=("recebedor inedito pessoa fisica", "valor acima do habitual", "recebedor recebendo de varias "
                "pessoas sem relacao entre si no mesmo dia"),
        defesa="Do lado de quem paga, o sinal e fraco. Do lado de quem recebe, e forte: a mesma conta recebe de "
               "muitos pagadores sem vinculo. Cruzar os dois lados e o que pega este golpe.",
        ausente_no_contrato=("vinculo entre pagador e recebedor fora do Pix (contatos, sobrenome)",),
        fonte="https://tecnoblog.net/noticias/golpe-via-whatsapp-usa-dados-vazados-e-pede-dinheiro-a-parentes-da-vitima/")
def falso_parente(ep, b):
    mula = _mula(ep, b["destino"], "falso-filho")
    vitimas = [ep.cliente_comum(f"vitima-{i}") for i in range(1 + b["outras_vitimas"])]
    for vitima in vitimas:
        quando = ep.momento(0, "09:00", 600)
        ep.pix(vitima, mula, vitima.mediana() * b["valor"], quando, rotulo="fraude", papel="alvo")
        if b["segundo_pedido"]:
            ep.pix(vitima, mula, vitima.mediana() * b["valor"] * 1.5, quando + timedelta(minutes=ep.acaso.randint(40, 90)),
                   rotulo="fraude", papel="alvo")


@perfil(nome="qr_code_adulterado", tipo="fraude", contido_por="rejected",
        descricao="Malware troca o QR Code da loja virtual: o cliente paga o valor certo para a conta errada",
        botoes={"vitimas": [20, 8, 3], "janela_horas": [2, 12, 48], "recebedor": ["pf_nova", "pf_antiga", "pj_antiga"]},
        sinais=("valor tipico de compra", "recebedor inedito", "o mesmo recebedor recebendo de muitos compradores"),
        defesa="Para o pagador o Pix e identico a uma compra. So o recebedor denuncia: uma conta que de repente "
               "recebe de dezenas de pagadores novos com valores de compra. Ver fan-in por recebedor.",
        ausente_no_contrato=("forma de iniciacao (QR Code, copia e cola, chave)", "recebedor que o QR deveria ter"),
        fonte="https://ohoje.com/2026/09/08/novo-golpe-troca-qr-code-do-pix-e-ja-atinge-90-sites-no-brasil/")
def qr_code_adulterado(ep, b):
    tipo = {"pf_nova": "conta_nova", "pf_antiga": "conta_antiga_alugada", "pj_antiga": "pj_antiga"}[b["recebedor"]]
    recebedor = _mula(ep, tipo, "recebedor-falso")
    fim = ep.momento(0, "20:00")
    for i in range(b["vitimas"]):
        comprador = ep.cliente_comum(f"comprador-{i}", n=8)
        quando = fim - timedelta(minutes=ep.acaso.randrange(b["janela_horas"] * 60))
        ep.pix(comprador, recebedor, ep.valor(4000, 60000), quando, rotulo="fraude", papel="alvo")


@perfil(nome="sequestro_relampago", tipo="fraude", contido_por="rejected",
        descricao="Vitima rendida faz Pix em sequencia de noite, do proprio celular, longe de casa",
        botoes={"pix": [4, 2, 1], "valor_cada": [200000, 100000, 90000], "pede_aumento": [True, False],
                "local": ["bairro_distante", "casa"], "hora": ["23:30", "21:10", "03:00"]},
        sinais=("noite", "varios Pix para recebedores ineditos", "pedido de aumento de limite na hora",
                "GPS longe dos lugares habituais"),
        defesa="Limite noturno de R$ 1.000 entre pessoas fisicas (IN BCB 512/2024, na redacao da IN BCB 669/2025) e carencia "
               "para aumento de limite pedido pelo app. O golpe adaptado faz Pix abaixo do teto para varias contas.",
        ausente_no_contrato=("tempo de sessao e hesitacao na tela",),
        fonte=FONTE_BCB_NOITE)
def sequestro_relampago(ep, b):
    vitima = ep.cliente_comum("vitima")
    gps = ep.gps_em(vitima.casa, 0.15) if b["local"] == "bairro_distante" else None
    inicio = ep.momento(0, b["hora"], 15)
    if b["pede_aumento"]:
        ep.limite(vitima, 2000000, inicio - timedelta(minutes=5))
    for quando in ep.sequencia(inicio, b["pix"], 4, 8):
        ep.pix(vitima, _mula(ep, "conta_nova"), b["valor_cada"], quando, gps=gps, rotulo="fraude", papel="alvo")


@perfil(nome="conta_laranja", tipo="fraude", contido_por="rejected",
        descricao="Varias vitimas de golpes diferentes pagam a mesma conta laranja",
        botoes={"vitimas": [12, 6, 3], "janela_horas": [1, 6, 48], "idade_conta_dias": [2, 90, 1500],
                "valores": ["iguais", "variados"]},
        sinais=("muitos pagadores distintos sem relacao", "conta recebedora nova ou sem esse habito"),
        defesa="Conta antiga nao e conta limpa: aluguel de conta antiga e tendencia citada por Serasa e Quod. "
               "Olhar a mudanca de comportamento do recebedor, nao so a idade da conta.",
        ausente_no_contrato=("marcacao de fraude do DICT para o recebedor",),
        fonte=FONTE_LARANJA)
def conta_laranja(ep, b):
    laranja = ep.pessoa("laranja", idade_conta_dias=b["idade_conta_dias"])
    if b["idade_conta_dias"] > 60:
        ep.historico(laranja, n=6, faixa=(2000, 8000))
    valor_fixo = ep.valor(30000, 150000, 5000)
    fim = ep.momento(0, "18:00")
    for i in range(b["vitimas"]):
        vitima = ep.cliente_comum(f"vitima-{i}", n=8)
        valor = valor_fixo if b["valores"] == "iguais" else ep.valor(20000, 200000)
        ep.pix(vitima, laranja, valor, fim - timedelta(minutes=ep.acaso.randrange(b["janela_horas"] * 60)),
               rotulo="fraude", papel="alvo")


@perfil(nome="repasse_cascata", tipo="fraude", contido_por="rejected",
        descricao="A laranja recebe de vitimas e repassa quase tudo em minutos, em camadas",
        botoes={"fracao": [95, 80, 60], "atraso_min": [5, 60, 360], "camadas": [1, 2, 3], "divisao": [1, 3],
                "idade_contas_dias": [5, 400], "aparelho_mula": ["novo", "habitual"]},
        sinais=("saida logo depois da entrada", "saida quase igual a soma das entradas", "recebedor inedito"),
        defesa="Repasse rapido e o que o MED 2.0 rastreia em camadas. Segurar a saida da laranja e o que permite "
               "devolver o dinheiro a vitima.",
        fonte=FONTE_MED)
def repasse_cascata(ep, b):
    def conta(apelido):
        nova = ep.pessoa(apelido, idade_conta_dias=b["idade_contas_dias"])
        if b["idade_contas_dias"] > 60:
            ep.historico(nova, n=5, faixa=(2000, 8000))
        return nova

    camada = [conta("laranja-1")]
    entrada = 0
    quando = ep.momento(0, "13:00", 60)
    for i in range(3):
        valor = ep.valor(60000, 150000)
        ep.pix(ep.cliente_comum(f"vitima-{i}", n=8), camada[0], valor, quando + timedelta(minutes=i * 10),
               rotulo="fraude", papel="alvo")
        entrada += valor
    quando += timedelta(minutes=20)
    for nivel in range(b["camadas"]):
        quando += timedelta(minutes=b["atraso_min"])
        proxima = [conta(f"laranja-{nivel + 2}-{j}") for j in range(b["divisao"])]
        saida = entrada * b["fracao"] / 100
        for origem in camada:
            aparelho = ep.mundo.novo_aparelho() if b["aparelho_mula"] == "novo" else None
            for destino in proxima:
                ep.pix(origem, destino, saida / len(camada) / len(proxima), quando, aparelho=aparelho,
                       rotulo="fraude", papel="alvo")
        camada, entrada = proxima, saida


@perfil(nome="sondagem_de_limite", tipo="fraude", contido_por="facial",
        descricao="Depois de um Pix barrado, o golpista tenta valores menores ate um passar",
        botoes={"degraus": [3, 5, 2], "fator": [0.5, 0.33, 0.85], "intervalo_min": [2, 10, 40],
                "aparelho": ["novo", "habitual"], "primeiro": [40, 15]},
        sinais=("tentativas em queda logo apos um bloqueio", "mesmo recebedor"),
        defesa="Lembrar da tentativa barrada: a proxima do mesmo par, menor e em minutos, e mais suspeita, nao menos.",
        fonte=FONTE_BCB_APARELHO)
def sondagem_de_limite(ep, b):
    vitima = ep.cliente_comum("vitima")
    mula = _mula(ep, "conta_nova")
    novo = b["aparelho"] == "novo"
    aparelho = ep.mundo.novo_aparelho() if novo else None
    valor = vitima.mediana() * b["primeiro"]
    for quando in ep.sequencia(ep.momento(0, "16:00", 60), b["degraus"], b["intervalo_min"], b["intervalo_min"] + 3):
        ep.pix(vitima, mula, valor, quando, aparelho=aparelho, rotulo="fraude", papel="alvo",
               contido_por="facial" if novo else "rejected")
        valor *= b["fator"]


@perfil(nome="aumento_limite_e_saque", tipo="fraude", contido_por="facial",
        descricao="Golpista pede aumento de limite e espera a carencia passar antes de sacar",
        botoes={"espera_horas": [1, 25, 6], "saque": ["acima_do_limite_antigo", "no_limite_antigo"],
                "aparelho": ["novo", "habitual"]},
        sinais=("pedido de aumento de limite recente", "Pix logo acima do limite antigo", "destino inedito"),
        defesa="A carencia de 24h para aumento so funciona se o Pix depois dela ainda for olhado com o contexto "
               "do pedido. Quem espera 25h nao deveria passar limpo.",
        fonte=FONTE_BCB_NOITE)
def aumento_limite_e_saque(ep, b):
    vitima = ep.cliente_comum("vitima")
    limite_antigo = vitima.mediana() * 10
    ep.limite(vitima, limite_antigo, ep.momento(35, "10:00"))
    pedido = ep.momento(0, "08:00") - timedelta(hours=b["espera_horas"])
    ep.limite(vitima, limite_antigo * 10, pedido)
    novo = b["aparelho"] == "novo"
    aparelho = ep.mundo.novo_aparelho() if novo else None
    valor = limite_antigo * (1.5 if b["saque"] == "acima_do_limite_antigo" else 0.95)
    mula = _mula(ep, "conta_nova")
    for quando in ep.sequencia(ep.momento(0, "08:00", 30), 2, 3, 10):
        ep.pix(vitima, mula, valor, quando, aparelho=aparelho, rotulo="fraude", papel="alvo",
               contido_por="facial" if novo else "rejected")


@perfil(nome="lento_e_gradual", tipo="fraude", contido_por="facial",
        descricao="Conta tomada drenada aos poucos, por dias, com valores perto do habito da vitima",
        botoes={"dias_aquecendo": [0, 3, 10], "dias_drenando": [1, 4, 10], "multiplo_diario": [6, 2, 1]},
        sinais=("aparelho novo que nunca passou por cadastro", "recebedor inedito que vira 'conhecido'",
                "saida diaria acima do habito somada no periodo"),
        defesa="Somar por janela (dia, semana) e nao so por Pix. Recebedor que so existe desde o aparelho novo "
               "nao e contraparte de confianca.",
        fonte=FONTE_BCB_APARELHO)
def lento_e_gradual(ep, b):
    vitima = ep.cliente_comum("vitima")
    aparelho = ep.mundo.novo_aparelho()
    total_dias = b["dias_aquecendo"] + b["dias_drenando"]
    for dia in range(total_dias, b["dias_drenando"], -1):
        ep.pix(vitima, ep.acaso.choice(vitima.conhecidos), ep.valor(1000, 5000), ep.momento(dia - 1, "11:00", 480),
               aparelho=aparelho, rotulo="neutro", papel="preparo", golpista=True)
    mula = _mula(ep, "conta_antiga_alugada")
    for dia in range(b["dias_drenando"] - 1, -1, -1):
        ep.pix(vitima, mula, vitima.mediana() * b["multiplo_diario"], ep.momento(dia, "12:00", 420),
               aparelho=aparelho, rotulo="fraude", papel="alvo")


@perfil(nome="fazenda_de_aparelhos", tipo="fraude", contido_por="rejected",
        descricao="Um operador movimenta muitas contas laranja do mesmo aparelho ou da mesma rede",
        botoes={"contas": [6, 3, 10], "rotaciona_aparelho": [False, True], "mesmo_destino": [True, False],
                "janela_min": [10, 60, 600], "mesmo_ip": [True, False]},
        sinais=("um aparelho para muitos titulares", "um IP para muitos titulares", "destino comum"),
        defesa="Coordenacao aparece no grafo aparelho-titular-destino. Rotacionar device_id e barato para o "
               "golpista, entao o IP e o destino comum precisam pesar junto.",
        ausente_no_contrato=("impressao digital do aparelho alem do device_id (modelo, emulador)",),
        fonte=FONTE_LARANJA)
def fazenda_de_aparelhos(ep, b):
    aparelho = ep.mundo.novo_aparelho()
    ip = ep.mundo.ip("sp")
    destino_comum = _mula(ep, "conta_nova", "caixa")
    inicio = ep.momento(0, "10:00", 60)
    for i in range(b["contas"]):
        laranja = ep.cliente_comum(f"laranja-{i}", n=5)
        destino = destino_comum if b["mesmo_destino"] else _mula(ep, "conta_nova", f"caixa-{i}")
        ep.pix(laranja, destino, laranja.mediana() * 5, inicio + timedelta(minutes=ep.acaso.randrange(b["janela_min"])),
               aparelho=ep.mundo.novo_aparelho() if b["rotaciona_aparelho"] else aparelho,
               ip=ip if b["mesmo_ip"] else None, rotulo="fraude", papel="alvo")


@perfil(nome="rede_suspeita", tipo="fraude", contido_por="rejected",
        descricao="O recebedor esta a poucos saltos de uma conta com fraude ativa",
        botoes={"saltos": [1, 2, 3], "multiplo": [1, 5]},
        sinais=("recebedor ligado a fraude confirmada por transferencias recentes",),
        defesa="Propagar risco pelo grafo de transferencias com decaimento por salto. O MED 2.0 faz o mesmo "
               "rastreio para tras; a antifraude pode fazer para frente.",
        fonte=FONTE_MED)
def rede_suspeita(ep, b):
    elo = ep.pessoa("fraude-ativa", documento=pix_utils.DOC_FRAUDE_ATIVA)
    for salto in range(b["saltos"]):
        proximo = ep.pessoa(f"salto-{salto + 1}", idade_conta_dias=400)
        ep.pix(elo, proximo, ep.valor(50000, 150000), ep.momento(b["saltos"] - salto, "11:00", 120),
               rotulo="neutro", papel="preparo")
        elo = proximo
    for i in range(2):
        vitima = ep.cliente_comum(f"vitima-{i}")
        ep.pix(vitima, elo, vitima.mediana() * b["multiplo"], ep.momento(0, "15:00", 120), rotulo="fraude", papel="alvo")


@perfil(nome="recebedor_ou_aparelho_marcado", tipo="fraude", contido_por="rejected",
        descricao="Pix para documento com fraude ativa ou alerta, ou feito de aparelho em lista de observacao",
        botoes={"marca": ["doc_fraude_ativa", "device_watchlist", "doc_alerta_risco", "doc_watchlist"], "multiplo": [1, 10]},
        # Quem paga e a vitima, que passa na selfie: so o bloqueio segura. A excecao
        # e o aparelho marcado, nas maos do golpista, que a selfie ja barra.
        sinais=("reputacao externa do recebedor ou do aparelho",),
        defesa="Consultar a marcacao de fraude do BCB (DICT) e as listas internas antes de qualquer pontuacao.",
        fonte=FONTE_BCB_APARELHO)
def recebedor_ou_aparelho_marcado(ep, b):
    vitima = ep.cliente_comum("vitima")
    valor = vitima.mediana() * b["multiplo"]
    quando = ep.momento(0, "14:00", 120)
    if b["marca"] == "device_watchlist":
        ep.pix(vitima, _mula(ep, "conta_nova"), valor, quando, aparelho=pix_utils.DEVICE_WATCHLIST,
               rotulo="fraude", papel="alvo", contido_por="facial")
        return
    documento = {"doc_fraude_ativa": pix_utils.DOC_FRAUDE_ATIVA, "doc_alerta_risco": pix_utils.DOC_ALERTA_RISCO,
                 "doc_watchlist": pix_utils.DOC_WATCHLIST}[b["marca"]]
    marcado = ep.pessoa("marcado", pj=len(documento) == 14, documento=documento)
    ep.pix(vitima, marcado, valor, quando, rotulo="fraude", papel="alvo")


@perfil(nome="conta_dormente", tipo="fraude", contido_por="rejected",
        descricao="Conta parada ha meses volta a mexer de repente, tomada ou alugada",
        botoes={"meses_parada": [8, 3, 14], "aparelho": ["novo", "habitual"], "padrao": ["saida_grande", "recebe_e_repassa"]},
        sinais=("meses sem movimento", "aparelho novo", "volume incompativel com o historico antigo"),
        defesa="Historico velho nao e historico atual: o perfil precisa envelhecer, e a volta depois de meses "
               "parado merece o mesmo cuidado de conta nova.",
        fonte=FONTE_LARANJA)
def conta_dormente(ep, b):
    dono = ep.pessoa("dormente", idade_conta_dias=2500)
    parada = b["meses_parada"] * 30
    ep.historico(dono, n=10, faixa=(3000, 15000), de_dias=parada + 60, ate_dias=parada)
    novo = b["aparelho"] == "novo"
    aparelho = ep.mundo.novo_aparelho() if novo else None
    quando = ep.momento(0, "11:00", 120)
    if b["padrao"] == "saida_grande":
        ep.pix(dono, _mula(ep, "conta_nova"), dono.mediana() * 15, quando, aparelho=aparelho,
               rotulo="fraude", papel="alvo", contido_por="facial" if novo else "rejected")
        return
    entrada = 0
    for i in range(4):
        valor = ep.valor(50000, 150000)
        ep.pix(ep.cliente_comum(f"vitima-{i}", n=8), dono, valor, quando + timedelta(minutes=5 * i),
               rotulo="fraude", papel="alvo")
        entrada += valor
    ep.pix(dono, _mula(ep, "conta_nova"), entrada * 0.9, quando + timedelta(minutes=40), aparelho=aparelho,
           rotulo="fraude", papel="alvo")


@perfil(nome="golpe_escalonado", tipo="fraude", contido_por="rejected",
        descricao="Falso investimento ou golpe do amor: Pix crescentes para o mesmo recebedor ao longo de dias",
        botoes={"parcelas": [5, 3, 8], "crescimento": [3.0, 1.5, 1.1], "intervalo_dias": [1, 3, 7], "valor_inicial": [3, 1]},
        sinais=("recebedor novo que vira 'conhecido' depois do primeiro Pix", "valores crescendo em sequencia",
                "soma no periodo muito acima do perfil"),
        defesa="Confianca no recebedor precisa ser ganha com o tempo e com valores parecidos, nao com o proprio "
               "golpe. Somar a exposicao ao mesmo recebedor novo no periodo.",
        fonte="https://febrabantech.febraban.org.br/temas/seguranca/quase-4-em-cada-10-brasileiros-ja-sofreram-golpe-aponta-pesquisa-da-febraban")
def golpe_escalonado(ep, b):
    vitima = ep.cliente_comum("vitima")
    golpista = ep.pessoa("golpista", idade_conta_dias=30 + b["parcelas"] * b["intervalo_dias"])
    valor = vitima.mediana() * b["valor_inicial"]
    for i in range(b["parcelas"]):
        dia = (b["parcelas"] - 1 - i) * b["intervalo_dias"]
        ep.pix(vitima, golpista, valor, ep.momento(dia, "19:00", 120), rotulo="fraude", papel="alvo")
        valor *= b["crescimento"]
