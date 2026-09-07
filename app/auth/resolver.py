from app.auth.models import Principal
from app.auth.policies import can_read
from app.catalog import Catalog
from app.ingestion.chunking import chunk_document
from app.models import Chunk


class AuthorizationResolver:
    def __init__(self, catalog: Catalog):
        self.catalog = catalog

    def allowed_scope(self, principal: Principal) -> list[str]:
        return [
            f"{d.id}:{d.version}"
            for d in self.catalog.list()
            if can_read(principal, d.id, d.metadata)
        ]

    def validate_chunk(self, principal: Principal, chunk: Chunk) -> bool:
        # Do not trust authorization attributes returned by a search backend.
        doc = self.catalog.get(chunk.document_id)
        return bool(
            doc
            and chunk.resource_key == f"{doc.id}:{doc.version}"
            and can_read(principal, doc.id, doc.metadata)
            and any(c.id == chunk.id and c.text == chunk.text for c in chunk_document(doc))
        )
