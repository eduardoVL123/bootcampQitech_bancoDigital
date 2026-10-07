from tests.utils.requisition import BaseConnectorResponse
from tests.utils.payload_generator import PayloadGenerator
from tests.utils.request_generator import RequestGenerator


class ObjectGenerator:
    @staticmethod
    def create_sample_entity(hello: str = None) -> BaseConnectorResponse:

        sample_entity_payload = PayloadGenerator.create_sample_entity_payload(hello=hello)

        status, response = RequestGenerator.POST_sample_entity(sample_entity_payload)
        assert status == 201

        return response

    @staticmethod
    def update_sample_entity(sample_entity_key, new_status: str = None) -> BaseConnectorResponse:

        sample_entity_payload = PayloadGenerator.create_new_status_payload(new_status)

        status, response = RequestGenerator.PUT_sample_entity(sample_entity_key, sample_entity_payload)
        assert status == 202

        return response
