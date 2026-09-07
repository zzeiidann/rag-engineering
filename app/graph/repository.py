from typing import Any, Protocol

from app.auth.models import Principal
from app.graph.models import KnowledgeGraphFragment
from app.models import Candidate, Chunk, Document


class GraphRepository(Protocol):
    def replace(
        self, document: Document, chunks: list[Chunk], fragment: KnowledgeGraphFragment
    ) -> None: ...
    def get_allowed_resources(self, principal: Principal, scope: list[str]) -> list[str]: ...
    def expand_context(self, query: str, scope: list[str], top_k: int) -> list[Candidate]: ...
    def get_related_entities(self, entity_id: str, scope: list[str]) -> list[dict[str, Any]]: ...
