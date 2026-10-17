"""Laboratorio da antifraud-api: simula clientes e golpes, mede e caca burlas.

A suite fixa (tools/bancada_rfc_antifraude.py) confere o contrato com casos
conhecidos. Este pacote faz o contrario: inventa casos novos a cada rodada,
mede a API pelo resultado (o golpe foi contido? o cliente honesto foi
barrado?) e guarda no corpus cada burla e cada falso positivo encontrado.
"""
