from models import Customer


class CustomerDTO:
    @staticmethod
    def created_response(customer: Customer) -> dict:
        return {
            "customer_key": customer.customer_key.strip(),
            "type": customer.customer_type.enumerator,
            "name": customer.name,
            "created_at": customer.created_at.isoformat() if customer.created_at else None,
        }

    @staticmethod
    def full_response(customer: Customer) -> dict:
        return {
            "customer_key": customer.customer_key.strip(),
            "type": customer.customer_type.enumerator,
            "name": customer.name,
            "document_number": customer.document_number,
            "birth_date": customer.birth_date.isoformat() if customer.birth_date else None,
            "created_at": customer.created_at.isoformat() if customer.created_at else None,
        }
