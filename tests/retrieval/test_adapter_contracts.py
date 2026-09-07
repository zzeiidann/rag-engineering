from unittest.mock import Mock

from app.auth.models import ResourceMetadata
from app.graph.neo4j_repository import Neo4jGraphRepository
from app.models import Chunk, ContextItem
from app.vectorstore.milvus import MilvusVectorStore
from scripts.demo import IDENTITIES


def test_milvus_filter_precedes_ranking_and_threshold():
    store = object.__new__(MilvusVectorStore)
    store.collection = "chunks"
    store.client = Mock()
    chunk = Chunk(
        id="abc",
        document_id="public",
        resource_key="public:v1",
        text="text",
        metadata=ResourceMetadata(visibility="public"),
    )
    store.client.search.return_value = [[{"entity": chunk.model_dump(), "distance": 0.2}]]
    assert store.search([1.0, 0.0], ["public:v1"], 5, 0.35) == []
    kwargs = store.client.search.call_args.kwargs
    assert kwargs["filter"] == 'resource_key in ["public:v1"]'
    assert kwargs["limit"] == 5
    assert kwargs["search_params"]["metric_type"] == "COSINE"
    store.client.reset_mock()
    assert store.search([1.0, 0.0], [], 5, 0.35) == []
    store.client.search.assert_not_called()


def test_graph_query_parameters_and_every_hop_scope():
    repository = object.__new__(Neo4jGraphRepository)
    repository.driver = Mock()
    repository.driver.execute_query.return_value = ([], None, [])
    repository.expand_context("pricing ' MATCH (n) DETACH DELETE n", ["public:v1"], 10)
    call = repository.driver.execute_query.call_args
    cypher = call.args[0]
    assert "all(n IN nodes(path) WHERE n.resource_key IN $scope)" in cypher
    assert "r.id IN $scope AND c.resource_key IN $scope" in cypher
    assert "DETACH DELETE" not in cypher
    assert call.kwargs["parameters_"]["scope"] == ["public:v1"]


def test_graph_cannot_widen_scope(service, monkeypatch):
    monkeypatch.setattr(
        service.ingestion.graph,
        "get_allowed_resources",
        lambda principal, scope: scope + ["actuarial_pricing:fake"],
    )
    service.retriever.retrieve("pricing", IDENTITIES["guest"])
    assert "actuarial_pricing:fake" not in service.ingestion.graph.last_scope


def test_llm_adapter_sends_grounded_context(monkeypatch):
    from app.llm.client import ChatCompletionsClient

    response = Mock()
    response.json.return_value = {"choices": [{"message": {"content": "Answer [chunk1]"}}]}
    post = Mock(return_value=response)
    monkeypatch.setattr("app.llm.client.httpx.post", post)
    client = ChatCompletionsClient("https://provider.invalid/v1", "test-key", "test-model")
    context = [ContextItem(source_id="chunk1", document_id="public", text="Public benefit")]
    assert client.generate("What benefit?", context) == "Answer [chunk1]"
    payload = post.call_args.kwargs["json"]
    assert "only from the supplied retrieved context" in payload["messages"][0]["content"]
    assert "Public benefit" in payload["messages"][1]["content"]
    assert payload["temperature"] == 0
