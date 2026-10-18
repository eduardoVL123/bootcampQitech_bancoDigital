# Ataques ao motor da antifraud-api

`tests/antifraud_api/test_ataques.py` faz o papel de quem quer burlar o motor. Cada teste parte de um cliente com rotina de verdade (um Pix por dia, de R$ 150 a R$ 250, para 3 destinos de sempre) e aplica as mutações que um golpista aplicaria para não acender nenhuma regra: o intervalo entre os Pix, o valor logo abaixo do corte, a conta que recebe, o aparelho, o canal.

**Foram escritos em 18/10/2026 sem rodar**, enquanto o motor estava em mudança. A expectativa é que vários fiquem vermelhos, e é para isso que existem: cada vermelho é uma porta aberta, com o cenário pronto para reproduzir. Por isso só rodam com uma chave, que nenhum CI liga:

```bash
RUN_ATAQUES=true pytest -v tests/antifraud_api/test_ataques.py
```

Sem a chave, os 15 casos aparecem como pulados.

## O que cada teste exige

O mínimo que uma defesa razoável daria: **que o ataque inteiro não passe sem nenhum atrito** (pelo menos um Pix do ataque com 2FA ou recusa). A exceção é a conta segura, em que quem aperta o botão é a própria vítima, enganada, e ela passa na facial: ali o teste exige `rejected`.

Dois testes têm **controle**: o mesmo cenário sem a mutação, que o motor já pega. Assim, se o ataque passar e o controle não, a diferença é exatamente a mutação.

## O catálogo

A coluna "por onde tenta passar" é a hipótese tirada do código das regras, ainda não confirmada rodando.

| # | Teste | Tática | Mutação | Por onde tenta passar |
|---|---|---|---|---|
| 1 | `test_dreno_abaixo_de_todos_os_cortes_no_aparelho_da_vitima_nao_passa_inteiro` | mão fantasma: golpista no celular da vítima por acesso remoto | 10 Pix de R$ 650, um a cada 31 min, cada um para uma laranja antiga | `PERFIL` ignora diferença menor que R$ 500; `VELOCITY` olha 30 min; `CONTRAPARTE_INEDITA` começa em R$ 1.000; aparelho, IP e GPS são os de sempre |
| 2 | `test_valor_subindo_aos_poucos_para_o_mesmo_destino_trava_antes_de_10_vezes_a_mediana` | escada ("sapo fervendo") | um Pix por dia para a mesma conta, 40% maior que o anterior, sem confirmar nenhum 2FA | o histórico do par e a mediana andam junto com o valor |
| 3 | `test_conta_parada_ha_90_dias_volta_devagar_abaixo_da_rajada_e_do_perfil` | conta dormente que volta | 2 Pix por hora de R$ 650 depois de 90 dias parada | `CONTA_REATIVADA` pede 3 em 1 h ou mais de R$ 5.000; o histórico saiu da janela de 90 dias do `PERFIL` |
| 4 | `test_gps_forjado_no_lugar_de_sempre_com_ip_de_outra_regiao_nao_passa` | conta tomada com GPS forjado | aparelho novo, GPS no ponto de sempre, IP de Recife, R$ 3.000 | só sobra o IP contra o GPS (`GEO_IP_DIVERGENTE`) e o aparelho novo |
| 5 | `test_aparelho_novo_com_pix_de_199_nao_drena_o_dia_de_quem_nunca_manda_gps` | aparelho novo abaixo da regra do BC | 5 Pix de R$ 199 de aparelho novo, IP de rede privada, sem GPS, em quem nunca manda GPS | `APARELHO_NAO_CADASTRADO` deixa até R$ 200 por Pix e R$ 1.000 por dia; `GEO_AUSENTE` respeita o hábito; IP privado não tem lugar |
| 6 | `test_pessoa_fisica_que_sempre_usa_o_app_aparecendo_pela_api_com_aparelho_novo_nao_passa` | credencial roubada usada por outro canal | pessoa física que sempre usou o app aparece pela `api`, de aparelho novo, sem GPS, R$ 650 | pela `api`, `GEO_AUSENTE` vale 0 e `APARELHO_NAO_CADASTRADO` não se aplica; a troca de canal não é sinal |
| 7 | `test_aparelho_cadastrado_por_um_codigo_confirmado_nao_libera_valor_fora_do_perfil` | engenharia social: "confirme o código" | a vítima confirma o 2FA do primeiro Pix do aparelho do golpista; depois vem R$ 4.000 | o aparelho confirmado passa a contar como cadastrado |
| 8 | `test_rajada_de_9_pix_em_4_minutos_nao_passa_inteira[ataque_tres_contas_do_mesmo_cpf]` | dividir entre contas | 9 Pix em 4 min, divididos em 3 contas do mesmo CPF, mesmo aparelho e IP | `VELOCITY` conta por conta, não por titular. Controle: as 9 numa conta só |
| 9 | `test_laranja_antiga_que_recebe_4_vitimas_por_hora_o_dia_todo` | conta laranja alugada ou comprada, antiga | 24 vítimas em 6 horas, 4 por hora, R$ 900 cada | `CONTA_LARANJA` pontua com 5 na hora; na janela de 24 h, a conta antiga leva só +20 ou +30 |
| 10 | `test_fazenda_de_contas_cada_uma_com_aparelho_e_ip_proprios_para_conta_nova` | fazenda de contas | 8 contas, cada uma com aparelho e IP próprios, R$ 180 para uma conta de 3 dias, 4 por hora | `COORDENACAO_ENTRE_CONTAS` precisa do mesmo aparelho; R$ 180 fica abaixo do teto da conta nova |
| 11 | `test_falso_parente_pede_valor_do_perfil_para_conta_aberta_ha_3_horas` | falso parente | R$ 700, dentro do hábito, para conta aberta há 3 horas | só o `DESTINO_NOVO` (+30) pesa |
| 12 | `test_conta_segura_no_proprio_cpf_em_outro_banco_e_rejeitada` | falsa central, "conta segura" | R$ 8.000 para conta nova no CPF da vítima, em outro banco, sem marcação | a `MESMA_TITULARIDADE` desconta 10; sem marcação no mock, nada bloqueia, e a vítima passa na facial |
| 13 | `test_pix_noturno_de_1900_para_quem_nao_e_loja_estabelecida[ataque_pj_de_31_dias]` | MEI de fachada que espera envelhecer | R$ 1.900 às 23h10 para PJ com conta de 31 dias | `NOTURNO` para PJ vale só com conta de menos de 30 dias. Controle: o mesmo Pix para pessoa física |

## Fora destes testes, de propósito

- **Entrada malformada e invariantes** (datas extremas, IPv6, valores no limite do schema, score e eixos coerentes) já estão nos testes do Eduardo: `test_falhas_datas.py`, `test_falhas_entradas.py` e `test_invariantes.py`, na `main`.
- **QR Code adulterado e falsa central para conta laranja antiga:** com o contrato atual, o Pix da vítima é igual a um Pix legítimo. O laboratório (`tools/laboratorio_antifraude.py`) mede quanto disso escapa.
- **Emulador, root, chamada em curso, app de acesso remoto aberto:** são sinais do aparelho, que o contrato não carrega.

## Fontes da pesquisa

As táticas são as que o mercado e os bancos descrevem do lado de quem defende:

- Conta laranja: cerca de 70% são alugadas com consciência do titular, o resto é aberto com dado roubado. [Serasa Experian](https://www.serasaexperian.com.br/sala-de-imprensa/pmes/mais-de-16-milhao-de-brasileiros-podem-ser-consumidores-laranjas-revela-estudo-inedito-da-serasa-experian/)
- Contas de passagem em cascata, emuladores e simulação biométrica: [Finsiders, contas laranja](https://finsidersbrasil.com.br/opinioes-e-artigos-fintechs/contas-laranjas-como-as-instituicoes-financeiras-podem-se-proteger/)
- Mão fantasma com ferramenta legítima de acesso remoto: [Paraíba Business](https://paraibabusiness.com.br/novo-golpe-do-pix-usa-acesso-remoto-para-controlar-celular-e-limpar-conta-da-vitima-veja-como-se-proteger/)
- Sinais de conta laranja no monitoramento: muitos pagadores entrando, muitos destinos saindo, valores logo abaixo do limite, conta parada que volta. [Didit, mule account detection](https://didit.me/blog/mule-account-detection/) e [Flagright, tipologias](https://www.flagright.com/insight/money-laundering-typologies)
- Por que a fraude com a vítima no comando passa pelos controles de transação: [Experian, APP fraud](https://www.experian.com/blogs/insights/authorized-push-payment-fraud)
