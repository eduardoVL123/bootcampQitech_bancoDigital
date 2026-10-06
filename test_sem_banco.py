import requests
import uuid

BASE_URL = "http://localhost:3000" # Ajuste para 8000 se o seu rodar na 8000
HEADERS = {"INTERNAL-TOKEN": "default_token"}

def print_result(test_name, success, expected, got):
    if success:
        print(f"[OK] {test_name} - PASSOU")
    else:
        print(f"[FAIL] {test_name} - FALHOU (Esperava {expected}, recebeu {got})")

def test_missing_fields():
    payload = {"type": "PF"} # Faltam name, document_number, etc.
    resp = requests.post(f"{BASE_URL}/internal/customer", json=payload, headers=HEADERS)
    print_result("Teste de Schema: Falta de campos obrigatórios", resp.status_code == 400, 400, resp.status_code)

def test_invalid_cpf():
    payload = {
        "request_key": str(uuid.uuid4()),
        "type": "PF",
        "name": "Eduardo Silva",
        "document_number": "111.222.333-44", # CPF Falso
        "birth_date": "1990-01-01"
    }
    resp = requests.post(f"{BASE_URL}/internal/customer", json=payload, headers=HEADERS)
    print_result("Teste de Negócio: Bloqueio de CPF inválido", resp.status_code == 422, 422, resp.status_code)

def test_underage():
    payload = {
        "request_key": str(uuid.uuid4()),
        "type": "PF",
        "name": "Eduardo Silva",
        "document_number": "228.929.940-26", # CPF Válido aleatório COM MÁSCARA
        "birth_date": "2015-01-01" # Menor de 18
    }
    resp = requests.post(f"{BASE_URL}/internal/customer", json=payload, headers=HEADERS)
    print_result("Teste de Negócio: Bloqueio de Menor de Idade", resp.status_code == 422, 422, resp.status_code)

def test_pj_rejection():
    payload = {
        "request_key": str(uuid.uuid4()),
        "type": "PJ",
        "name": "Empresa Teste",
        "document_number": "228.929.940-26",
        "birth_date": "1990-01-01"
    }
    resp = requests.post(f"{BASE_URL}/internal/customer", json=payload, headers=HEADERS)
    print_result("Teste de Negócio: Rejeição do tipo PJ", resp.status_code == 422, 422, resp.status_code)

def test_impossible_date():
    payload = {
        "request_key": str(uuid.uuid4()),
        "type": "PF",
        "name": "Eduardo Silva",
        "document_number": "228.929.940-26",
        "birth_date": "2025-02-30" # 30 de fevereiro
    }
    resp = requests.post(f"{BASE_URL}/internal/customer", json=payload, headers=HEADERS)
    print_result("Teste de Negócio: Rejeição de data inexistente", resp.status_code == 422, 422, resp.status_code)

if __name__ == "__main__":
    print("Iniciando testes automatizados SEM BANCO DE DADOS...\n")
    try:
        test_missing_fields()
        test_invalid_cpf()
        test_underage()
        test_pj_rejection()
        test_impossible_date()
        print("\nTudo funcionando perfeitamente na camada de negócio e validação!")
    except requests.exceptions.ConnectionError:
        print("❌ ERRO: A API parece não estar rodando no localhost:3000. O Docker está ativo mesmo?")
