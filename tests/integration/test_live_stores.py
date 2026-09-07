"""Opt in with RUN_INTEGRATION=1 after starting the Compose databases."""

import os
from uuid import uuid4

import pytest

from app.auth.models import Principal, ResourceMetadata
from app.auth.resolver import AuthorizationResolver
from app.catalog import Catalog
from app.config import Settings
from app.graph.neo4j_repository import Neo4jGraphRepository
from app.ingestion.extractor import StructuredKnowledgeExtractor
from app.ingestion.pipeline import IngestionPipeline
from app.models import Document
from app.retrieval.graph import GraphRetriever
from app.retrieval.hybrid import HybridRetriever
from app.retrieval.reranker import ScoreFusionReranker
from app.retrieval.vector import VectorRetriever
from app.service import QueryService
from app.vectorstore.milvus import MilvusVectorStore
from tests.fakes import HashEmbeddings, RecordingLLM

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(os.getenv("RUN_INTEGRATION") != "1", reason="Live databases not requested"),
]


def test_real_backends_prefilter_and_traverse(tmp_path):
    config = Settings()
    prefix = "test_" + uuid4().hex
    vectors = MilvusVectorStore(config.milvus_uri, prefix, 256)
    graph = Neo4jGraphRepository(config.neo4j_uri, config.neo4j_user, config.neo4j_password)
    catalog, embeddings = Catalog(str(tmp_path / "catalog.db")), HashEmbeddings()
    pipeline = IngestionPipeline(
        catalog, embeddings, vectors, graph, StructuredKnowledgeExtractor()
    )
    resolver = AuthorizationResolver(catalog)
    llm = RecordingLLM()
    service = QueryService(
        resolver,
        HybridRetriever(
            resolver,
            VectorRetriever(vectors, embeddings, 20, 0),
            GraphRetriever(graph, 20),
            ScoreFusionReranker(0.65, 0.25, 0.1),
            5,
        ),
        llm,
        pipeline,
    )
    ids = []
    try:
        for owner in ["a", "b"]:
            doc = Document(
                id=f"{prefix}_{owner}",
                title="Policy",
                text=f"Transplant coverage secret for {owner}\n"
                "@entity plan|Policy|Transplant coverage\n"
                "@entity benefit|Benefit|Overseas transplant\n"
                "@edge plan|COVERS|benefit",
                metadata=ResourceMetadata(visibility="client", owner_client_id=owner),
            )
            ids.append(doc.id)
            pipeline.stage(doc)
            pipeline.index(doc.id)
        principal = Principal(user_id=prefix, role="client", client_id="a")
        result = service.query("transplant coverage", principal)
        assert result["retrieved_resources"] == [f"{prefix}_a"]
        assert all("secret for b" not in c.text for ctx in llm.contexts for c in ctx)
        scope = resolver.allowed_scope(principal)
        assert graph.expand_context("transplant", scope, 10)
        assert graph.get_related_entities("plan", scope)[0]["related"]
        assert not service.query("transplant", Principal(user_id="g", role="guest"))["sources"]
    finally:
        # Delete only this test's uniquely named collection and document-owned nodes.
        vectors.client.drop_collection(prefix)
        graph.run("MATCH (n) WHERE n.document_id IN $ids DETACH DELETE n", ids=ids)
        vectors.client.close()
        graph.driver.close()
