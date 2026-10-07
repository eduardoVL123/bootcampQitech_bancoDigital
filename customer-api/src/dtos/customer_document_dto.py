from models import CustomerDocument


class CustomerDocumentDTO:
    @staticmethod
    def created_response(document: CustomerDocument) -> dict:
        return {
            "document_type": document.document_type,
            "side": document.side,
            "object_key": document.object_key,
            "content_type": document.content_type,
            "size_bytes": document.size_bytes,
            "created_at": document.created_at.isoformat() if document.created_at else None,
        }
