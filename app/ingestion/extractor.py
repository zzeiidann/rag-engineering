import re
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
        if document.source_metadata and document.source_metadata.source_type == "web":
            entities["web_page"] = Entity.model_validate(
                dict(id="web_page", kind="WebPage", name=document.title)
            )
            path: list[str] = []
            for line in document.text.splitlines():
                match = re.match(r"^(#{1,6})\s+(.+?)\s*$", line)
                if not match:
                    continue
                level, title = len(match.group(1)), match.group(2)
                path[level - 1 :] = [title]
                identifier = (
                    f"section_{len([key for key in entities if key.startswith('section_')])}"
                )
                entities[identifier] = Entity.model_validate(
                    dict(id=identifier, kind="Topic", name=" / ".join(path))
                )
                edges.append(
                    KnowledgeEdge.model_validate(
                        dict(source="web_page", kind="DESCRIBES", target=identifier)
                    )
                )
                if len([key for key in entities if key.startswith("section_")]) >= 32:
                    break
        return KnowledgeGraphFragment(entities=list(entities.values()), edges=edges)
