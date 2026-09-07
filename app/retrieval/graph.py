from app.auth.models import Principal
from app.graph.repository import GraphRepository
from app.models import Candidate


class GraphRetriever:
    def __init__(self, repository: GraphRepository, top_k: int):
        self.repository, self.top_k = repository, top_k

    def retrieve(self, query: str, principal: Principal, scope: list[str]) -> list[Candidate]:
        allowed = self.repository.get_allowed_resources(principal, scope)
        # A repository defect cannot widen the authorization resolver's scope.
        narrowed = sorted(set(allowed) & set(scope))
        return self.repository.expand_context(query, narrowed, self.top_k) if narrowed else []
