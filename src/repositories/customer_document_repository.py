from database import Context
from models import CustomerDocument


class CustomerDocumentRepository:
    def __init__(self, context: Context) -> None:
        self.session = context.db_session

    def create(self, customer_id: int, document_data: dict) -> CustomerDocument:
        document = CustomerDocument()
        document.customer_id = customer_id
        document.document_type = document_data["document_type"]
        document.side = document_data.get("side")
        document.object_key = document_data["object_key"]
        document.content_type = document_data["content_type"]
        document.size_bytes = document_data["size_bytes"]

        self.session.add(document)
        self.session.flush()
        return document

    def get_by_customer_and_type_and_side(self, customer_id: int, document_type: str, side: str = None) -> CustomerDocument:
        query = self.session.query(CustomerDocument).filter(
            CustomerDocument.customer_id == customer_id,
            CustomerDocument.document_type == document_type
        )
        if side:
            query = query.filter(CustomerDocument.side == side)
        else:
            query = query.filter(CustomerDocument.side.is_(None))
        return query.first()
