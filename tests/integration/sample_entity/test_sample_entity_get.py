from tests.utils import RequestGenerator


class TestSampleEntityGet:
    def test_not_found(self):
        status, response = RequestGenerator.GET_sample_entity("00000000-0000-0000-0000-000000000000")
        assert status == 404
        assert response["code"] == "QIT001001"
