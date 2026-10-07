from uuid import uuid4

from tests.utils.random_generator import RandomGenerator


class PayloadGenerator:
    @staticmethod
    def create_sample_entity_payload(
        hello: str = None,
        name: str = None,
        email: str = None,
        document_number: str = None,
        birthdate: str = None,
    ) -> dict:
        """Um cadastro valido, com qualquer campo trocado a pedido.

        Sem argumento nenhum o payload sai aleatorio no que precisa ser
        unico (e-mail e CPF), pra que dois cadastros seguidos nao batam
        na regra de duplicidade. Quem testa FILTRO precisa do contrario
        disso: um valor conhecido, pra poder procurar por ele depois.
        """
        if hello is None:
            hello = "world"

        if name is None:
            name = "Maria da Silva"

        if email is None:
            email = f"maria.silva.{uuid4()}@exemplo.com.br"

        if document_number is None:
            document_number = RandomGenerator.generate_cpf()

        if birthdate is None:
            birthdate = "1990-05-17"

        payload = {
            "hello": hello,
            "name": name,
            "email": email,
            "document_number": document_number,
            "birthdate": birthdate,
        }
        return payload

    @staticmethod
    def create_new_status_payload(new_status: str = None) -> dict:
        payload = {"status": new_status}
        return payload

    @staticmethod
    def create_customer_payload(
        request_key: str = None,
        type_: str = "PF",
        name: str = "Eduardo Silva",
        document_number: str = None,
        birth_date: str = "1990-01-01",
    ) -> dict:
        if request_key is None:
            request_key = str(uuid4())
        if document_number is None:
            document_number = RandomGenerator.generate_cpf()
        
        return {
            "request_key": request_key,
            "type": type_,
            "name": name,
            "document_number": document_number,
            "birth_date": birth_date,
        }

    @staticmethod
    def create_customer_document_payload(
        document_type: str = "RG",
        side: str = "FRONT",
        object_key: str = None,
        content_type: str = "image/jpeg",
        size_bytes: int = 1048576,
    ) -> dict:
        if object_key is None:
            object_key = f"documents/{uuid4()}.jpg"

        return {
            "document_type": document_type,
            "side": side,
            "object_key": object_key,
            "content_type": content_type,
            "size_bytes": size_bytes,
        }
