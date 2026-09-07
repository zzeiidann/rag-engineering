from typing import Protocol

from app.models import Candidate
from app.retrieval.text import terms


class Reranker(Protocol):
    def rerank(self, query: str, candidates: list[Candidate], top_k: int) -> list[Candidate]: ...


class ScoreFusionReranker:
    """CPU-only fallback; lexical overlap supplements vector and graph relevance."""

    def __init__(self, alpha: float, beta: float, gamma: float):
        self.alpha, self.beta, self.gamma = alpha, beta, gamma

    def rerank(self, query: str, candidates: list[Candidate], top_k: int) -> list[Candidate]:
        tokens = terms(query)
        for candidate in candidates:
            candidate.reranker_score = len(tokens & terms(candidate.chunk.text)) / max(
                1, len(tokens)
            )
            candidate.score = (
                self.alpha * candidate.vector_score
                + self.beta * candidate.graph_score
                + self.gamma * candidate.reranker_score
            )
        return sorted(candidates, key=lambda c: (-c.score, c.chunk.id))[:top_k]
