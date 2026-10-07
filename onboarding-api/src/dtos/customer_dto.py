from models import Customer


class CustomerDTO:
    """Monta a resposta pública do cadastro (RFC 05, GET /customer). A
    credencial, a renda e a ocupação ficam de fora."""

    @staticmethod
    def public(customer: Customer) -> dict:
        dto = {
            "customer_key": customer.customer_key,
            "type": customer.type.enumerator,
            "name": customer.name,
            "document_number": customer.document_number,
        }

        if customer.birth_date is not None:
            dto["birth_date"] = customer.birth_date.isoformat()
        else:
            dto["opening_date"] = customer.opening_date.isoformat()

        dto["created_at"] = customer.created_at.isoformat()
        return dto
