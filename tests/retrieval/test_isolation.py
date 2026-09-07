import pytest

from app.models import Candidate
from scripts.demo import IDENTITIES, SCENARIOS


@pytest.mark.parametrize("identity,query,relevant", SCENARIOS)
def test_scope_and_llm_isolation(service, identity, query, relevant):
    principal = IDENTITIES[identity]
    result = service.query(query, principal)
    allowed = set(service.resolver.allowed_scope(principal))
    assert set(service.ingestion.vectors.last_scope) <= allowed
    assert set(service.ingestion.graph.last_scope) <= allowed
    for context in service.llm.contexts:
        for item in context:
            assert item.document_id in {key.split(":")[0] for key in allowed}
    if identity in {"guest", "client_a", "sales"}:
        assert "ACTUARIAL_SECRET" not in result["answer"]
        assert "B_ONLY_CANARY" not in result["answer"]
        assert "B_TRANSPLANT_SECRET" not in result["answer"]
    if identity in {"actuarial", "sales_permitted"}:
        assert "actuarial_pricing" in result["retrieved_resources"]


def test_client_b_wins_unrestricted_but_never_enters_client_a_search(service):
    query = "Platinum international transplant coverage overseas organ transplants"
    vector = service.retriever.vector
    unrestricted = vector.retrieve(
        query, [f"{d.id}:{d.version}" for d in service.resolver.catalog.list()]
    )
    assert unrestricted[0].chunk.document_id == "client_b_coverage"
    candidates, _ = service.retriever.retrieve(query, IDENTITIES["client_a"])
    assert all(not c.chunk.document_id.startswith("client_b") for c in candidates)
    assert all(not key.startswith("client_b") for key in service.ingestion.vectors.last_scope)


def test_backend_injection_rejected_before_reranker_and_llm(service, monkeypatch):
    secret = next(
        c
        for c, _ in service.ingestion.vectors.rows.values()
        if c.document_id == "actuarial_pricing"
    )
    monkeypatch.setattr(
        service.ingestion.vectors, "search", lambda *args: [Candidate(chunk=secret, vector_score=1)]
    )
    monkeypatch.setattr(service.ingestion.graph, "expand_context", lambda *args: [])
    called = []
    original = service.retriever.reranker.rerank

    def spy(query, candidates, top_k):
        called.extend(candidates)
        return original(query, candidates, top_k)

    monkeypatch.setattr(service.retriever.reranker, "rerank", spy)
    result = service.query("pricing", IDENTITIES["guest"])
    assert not called
    assert not service.llm.contexts
    assert result["sources"] == []


def test_forged_public_chunk_text_is_rejected(service, monkeypatch):
    chunk = next(
        c for c, _ in service.ingestion.vectors.rows.values() if c.document_id == "public_faq"
    )
    forged = chunk.model_copy(update={"text": "ACTUARIAL_SECRET stolen content"})
    assert not service.resolver.validate_chunk(IDENTITIES["guest"], forged)


def test_final_context_check_after_revocation(service, monkeypatch):
    original = service.retriever.retrieve

    def revoke(query, principal):
        candidates, metrics = original(query, principal)
        for candidate in candidates:
            doc = service.resolver.catalog.get(candidate.chunk.document_id)
            service.resolver.catalog.stage(doc)
        return candidates, metrics

    monkeypatch.setattr(service.retriever, "retrieve", revoke)
    assert service.query("pricing", IDENTITIES["guest"])["sources"] == []
    assert not service.llm.contexts


def test_irrelevant_vector_threshold_and_empty_scope(service):
    assert service.retriever.vector.retrieve("pricing", []) == []
    service.retriever.vector.threshold = 1.0
    assert (
        service.retriever.vector.retrieve(
            "unrelated xyz", service.resolver.allowed_scope(IDENTITIES["guest"])
        )
        == []
    )
