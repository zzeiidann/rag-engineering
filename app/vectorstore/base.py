from typing import Protocol

from app.models import Candidate, Chunk


class VectorStore(Protocol):
    def replace(
        self, document_id: str, chunks: list[Chunk], embeddings: list[list[float]]
    ) -> None: ...
    def search(
        self, embedding: list[float], scope: list[str], top_k: int, threshold: float
    ) -> list[Candidate]: ...
