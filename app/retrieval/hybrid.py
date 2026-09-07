from time import perf_counter

from app.auth.models import Principal
from app.auth.resolver import AuthorizationResolver
from app.models import Candidate
from app.retrieval.graph import GraphRetriever
from app.retrieval.reranker import Reranker
from app.retrieval.vector import VectorRetriever


class HybridRetriever:
    def __init__(
        self,
        resolver: AuthorizationResolver,
        vector: VectorRetriever,
        graph: GraphRetriever,
        reranker: Reranker,
        top_k: int,
    ):
        self.resolver, self.vector, self.graph = resolver, vector, graph
        self.reranker, self.top_k = reranker, top_k

    def retrieve(self, query: str, principal: Principal) -> tuple[list[Candidate], dict]:
        start = perf_counter()
        scope = self.resolver.allowed_scope(principal)
        vector = self.vector.retrieve(query, scope)
        graph = self.graph.retrieve(query, principal, scope)
        merged: dict[str, Candidate] = {}
        denied = 0
        for candidate in vector + graph:
            if not self.resolver.validate_chunk(principal, candidate.chunk):
                denied += 1
                continue
            key = candidate.chunk.id
            if key in merged:
                merged[key].vector_score = max(merged[key].vector_score, candidate.vector_score)
                merged[key].graph_score = max(merged[key].graph_score, candidate.graph_score)
            else:
                merged[key] = candidate.model_copy(deep=True)
        rerank_start = perf_counter()
        ranked = self.reranker.rerank(query, list(merged.values()), self.top_k)
        end = perf_counter()
        return ranked, dict(
            vector_candidates=len(vector),
            graph_candidates=len(graph),
            reranked_candidates=len(ranked),
            authorization_filtered=denied,
            retrieval_latency_ms=(rerank_start - start) * 1000,
            reranking_latency_ms=(end - rerank_start) * 1000,
        )
