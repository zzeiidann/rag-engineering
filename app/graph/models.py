from typing import Literal

from pydantic import BaseModel, Field


class Entity(BaseModel):
    id: str = Field(pattern=r"^[a-zA-Z0-9_-]+$")
    kind: Literal[
        "Product",
        "Benefit",
        "Exclusion",
        "CoverageLimit",
        "PricingMethod",
        "Policy",
        "Contract",
        "Procedure",
        "InternalResource",
        "WebPage",
        "Topic",
    ]
    name: str = Field(min_length=1, max_length=300)


class KnowledgeEdge(BaseModel):
    source: str
    target: str
    kind: Literal[
        "COVERS", "EXCLUDES", "HAS_LIMIT", "RELATED_TO", "DESCRIBES", "REFERENCES", "PRICED_BY"
    ]


class KnowledgeGraphFragment(BaseModel):
    entities: list[Entity] = Field(default_factory=list)
    edges: list[KnowledgeEdge] = Field(default_factory=list)
