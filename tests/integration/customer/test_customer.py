from datetime import date
from uuid import uuid4

from tests.utils import PayloadGenerator, RequestGenerator
from tests.utils.db_utils import DbUtils


def birthdate_for_age(age_in_years: int) -> str:
    today = date.today()
    if today.month == 2 and today.day == 29:
        return date(today.year - age_in_years, 2, 28).isoformat()
    return date(today.year - age_in_years, today.month, today.day).isoformat()


class TestCustomerAPI:
    def setup_method(self):
        DbUtils.rollback()

    def test_ct01_create_valid_customer_pf(self):
        payload = PayloadGenerator.create_customer_payload()
        status, response = RequestGenerator.POST_customer(payload)
        
        assert status == 201
        assert "customer_key" in response
        assert response["type"] == "PF"
        assert response["name"] == payload["name"]

    def test_ct02_idempotency(self):
        payload = PayloadGenerator.create_customer_payload()
        status1, response1 = RequestGenerator.POST_customer(payload)
        assert status1 == 201
        
        status2, response2 = RequestGenerator.POST_customer(payload)
        assert status2 == 200
        assert response2["customer_key"] == response1["customer_key"]

    def test_ct03_duplicated_cpf_different_request_key(self):
        payload1 = PayloadGenerator.create_customer_payload()
        status1, _ = RequestGenerator.POST_customer(payload1)
        assert status1 == 201
        
        payload2 = PayloadGenerator.create_customer_payload(document_number=payload1["document_number"])
        status2, response2 = RequestGenerator.POST_customer(payload2)
        assert status2 == 409
        assert response2["code"] == "QIT002002"

    def test_ct04_invalid_cpf(self):
        payload1 = PayloadGenerator.create_customer_payload(document_number="12345678901")
        status1, response1 = RequestGenerator.POST_customer(payload1)
        assert status1 == 400
        assert response1["code"] == "QIT000001"
        
        payload2 = PayloadGenerator.create_customer_payload(document_number="111.222.333-44")
        status2, response2 = RequestGenerator.POST_customer(payload2)
        assert status2 == 422
        assert response2["code"] == "QIT002005"

    def test_ct05_underage_customer(self):
        payload = PayloadGenerator.create_customer_payload(birth_date=birthdate_for_age(17))
        status, response = RequestGenerator.POST_customer(payload)
        assert status == 422
        assert response["code"] == "QIT002003"

    def test_ct06_missing_required_fields(self):
        payload = PayloadGenerator.create_customer_payload()
        del payload["name"]
        status, response = RequestGenerator.POST_customer(payload)
        assert status == 400
        assert response["code"] == "QIT000001"

    def test_ct07_get_customer_success(self):
        payload = PayloadGenerator.create_customer_payload()
        status, created = RequestGenerator.POST_customer(payload)
        assert status == 201
        
        customer_key = created["customer_key"]
        status2, response = RequestGenerator.GET_customer(customer_key)
        assert status2 == 200
        assert response["customer_key"] == customer_key
        assert response["document_number"] == payload["document_number"]
        assert response["name"] == payload["name"]
        assert response["birth_date"] == payload["birth_date"]

    def test_ct08_get_customer_not_found(self):
        status, response = RequestGenerator.GET_customer(str(uuid4()))
        assert status == 404
        assert response["code"] == "QIT002001"

    def test_ct09_post_document_success(self):
        customer_payload = PayloadGenerator.create_customer_payload()
        _, created = RequestGenerator.POST_customer(customer_payload)
        customer_key = created["customer_key"]
        
        doc_payload = PayloadGenerator.create_customer_document_payload(document_type="RG", side="FRONT")
        status, response = RequestGenerator.POST_customer_document(customer_key, doc_payload)
        assert status == 201
        assert response["document_type"] == "RG"
        assert response["side"] == "FRONT"
        assert response["object_key"] == doc_payload["object_key"]

    def test_ct10_post_document_duplicate(self):
        customer_payload = PayloadGenerator.create_customer_payload()
        _, created = RequestGenerator.POST_customer(customer_payload)
        customer_key = created["customer_key"]
        
        doc_payload = PayloadGenerator.create_customer_document_payload(document_type="RG", side="FRONT")
        status1, _ = RequestGenerator.POST_customer_document(customer_key, doc_payload)
        assert status1 == 201
        
        doc_payload2 = PayloadGenerator.create_customer_document_payload(document_type="RG", side="FRONT")
        status2, response = RequestGenerator.POST_customer_document(customer_key, doc_payload2)
        assert status2 == 409
        assert response["code"] == "QIT002008"

    def test_ct11_post_document_customer_not_found(self):
        doc_payload = PayloadGenerator.create_customer_document_payload(document_type="RG", side="FRONT")
        status, response = RequestGenerator.POST_customer_document(str(uuid4()), doc_payload)
        assert status == 404
        assert response["code"] == "QIT002009"
