from typing import Protocol

from app.graph.models import Entity, KnowledgeEdge, KnowledgeGraphFragment
from app.models import Document


class KnowledgeExtractor(Protocol):
    def extract(self, document: Document) -> KnowledgeGraphFragment: ...


class StructuredKnowledgeExtractor:
    """Optional author-curated lines: @entity id|Kind|Name; @edge src|TYPE|dst."""

    def extract(self, document: Document) -> KnowledgeGraphFragment:
        entities: dict[str, Entity] = {}
        edges = []
        for line in document.text.splitlines():
            if line.startswith("@entity "):
                identifier, kind, name = line[8:].split("|", 2)
                entities[identifier] = Entity.model_validate(
                    dict(id=identifier, kind=kind, name=name)
                )
            elif line.startswith("@edge "):
                source, kind, target = line[6:].split("|", 2)
                edges.append(
                    KnowledgeEdge.model_validate(dict(source=source, kind=kind, target=target))
                )
        if any(e.source not in entities or e.target not in entities for e in edges):
            raise ValueError("Knowledge edge references an undeclared entity")
        return KnowledgeGraphFragment(entities=list(entities.values()), edges=edges)
