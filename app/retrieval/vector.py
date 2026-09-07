from app.embeddings.base import EmbeddingModel
from app.models import Candidate
from app.vectorstore.base import VectorStore


class VectorRetriever:
    def __init__(
        self, store: VectorStore, embeddings: EmbeddingModel, top_k: int, threshold: float
    ):
        self.store, self.embeddings = store, embeddings
        self.top_k, self.threshold = top_k, threshold

    def retrieve(self, query: str, scope: list[str]) -> list[Candidate]:
        if not scope:
            return []
        return self.store.search(
            self.embeddings.embed_query(query), scope, self.top_k, self.threshold
        )
