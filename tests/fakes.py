"""Deterministic test doubles; never selected by the production dependency container."""

import hashlib
import math
from pathlib import Path
from typing import Any

from app.auth.models import Principal
from app.auth.resolver import AuthorizationResolver
from app.catalog import Catalog
from app.graph.models import KnowledgeGraphFragment
from app.ingestion.extractor import StructuredKnowledgeExtractor
from app.ingestion.pipeline import IngestionPipeline
from app.models import Candidate, Chunk, ContextItem, Document
from app.retrieval.graph import GraphRetriever
from app.retrieval.hybrid import HybridRetriever
from app.retrieval.reranker import ScoreFusionReranker
from app.retrieval.text import terms
from app.retrieval.vector import VectorRetriever
from app.service import QueryService
from scripts.demo import documents


class HashEmbeddings:
    """Lexical hashing for fast offline security tests, not semantic quality measurement."""

    def embed_query(self, text: str) -> list[float]:
        vector = [0.0] * 256
        for token in terms(text):
            index = int(hashlib.sha256(token.encode()).hexdigest(), 16) % len(vector)
            vector[index] += 1
        norm = math.sqrt(sum(v * v for v in vector)) or 1
        return [v / norm for v in vector]

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [self.embed_query(text) for text in texts]


class MemoryVectors:
    def __init__(self) -> None:
        self.rows: dict[str, tuple[Chunk, list[float]]] = {}
        self.last_scope: list[str] = []

    def replace(self, document_id: str, chunks: list[Chunk], embeddings: list[list[float]]) -> None:
        self.rows = {k: v for k, v in self.rows.items() if v[0].document_id != document_id}
        self.rows.update({c.id: (c, e) for c, e in zip(chunks, embeddings, strict=True)})

    def search(
        self, embedding: list[float], scope: list[str], top_k: int, threshold: float
    ) -> list[Candidate]:
        self.last_scope = scope
        candidates = [
            Candidate(chunk=c, vector_score=sum(a * b for a, b in zip(embedding, e, strict=True)))
            for c, e in self.rows.values()
            if c.resource_key in scope
        ]
        return sorted(
            [c for c in candidates if c.vector_score >= threshold], key=lambda c: -c.vector_score
        )[:top_k]


class MemoryGraph:
    def __init__(self) -> None:
        self.rows: dict[str, tuple[list[Chunk], KnowledgeGraphFragment]] = {}
        self.last_scope: list[str] = []

    def replace(
        self, document: Document, chunks: list[Chunk], fragment: KnowledgeGraphFragment
    ) -> None:
        self.rows = {k: v for k, v in self.rows.items() if not k.startswith(document.id + ":")}
        self.rows[f"{document.id}:{document.version}"] = (chunks, fragment)

    def get_allowed_resources(self, principal: Principal, scope: list[str]) -> list[str]:
        return [key for key in scope if key in self.rows]

    def expand_context(self, query: str, scope: list[str], top_k: int) -> list[Candidate]:
        self.last_scope = scope
        candidates = []
        for key, (chunks, fragment) in self.rows.items():
            if key in scope and any(terms(query) & terms(e.name) for e in fragment.entities):
                candidates.extend(Candidate(chunk=c, graph_score=1) for c in chunks)
        return candidates[:top_k]

    def get_related_entities(self, entity_id: str, scope: list[str]) -> list[dict[str, Any]]:
        return [
            e.model_dump()
            for key, (_, fragment) in self.rows.items()
            if key in scope
            for e in fragment.entities
            if e.id == entity_id
        ]


class RecordingLLM:
    def __init__(self) -> None:
        self.contexts: list[list[ContextItem]] = []

    def generate(self, query: str, context: list[ContextItem]) -> str:
        self.contexts.append(context)
        return "\n".join(f"[{c.source_id}] {c.text}" for c in context)


def offline_service(path: Path) -> QueryService:
    catalog = Catalog(str(path / "catalog.db"))
    embeddings, vectors, graph = HashEmbeddings(), MemoryVectors(), MemoryGraph()
    resolver = AuthorizationResolver(catalog)
    pipeline = IngestionPipeline(
        catalog, embeddings, vectors, graph, StructuredKnowledgeExtractor()
    )
    for document in documents():
        pipeline.stage(document)
        pipeline.index(document.id)
    retriever = HybridRetriever(
        resolver,
        VectorRetriever(vectors, embeddings, 20, 0.1),
        GraphRetriever(graph, 20),
        ScoreFusionReranker(0.65, 0.25, 0.1),
        5,
    )
    return QueryService(resolver, retriever, RecordingLLM(), pipeline, debug=True)
