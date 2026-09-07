import json

from app.auth.models import Principal
from app.auth.resolver import AuthorizationResolver
from app.catalog import Catalog
from app.config import Settings
from app.embeddings.base import FastEmbedModel
from app.graph.neo4j_repository import Neo4jGraphRepository
from app.ingestion.extractor import StructuredKnowledgeExtractor
from app.ingestion.pipeline import IngestionPipeline
from app.llm.client import ChatCompletionsClient
from app.retrieval.graph import GraphRetriever
from app.retrieval.hybrid import HybridRetriever
from app.retrieval.reranker import ScoreFusionReranker
from app.retrieval.vector import VectorRetriever
from app.service import QueryService
from app.vectorstore.milvus import MilvusVectorStore


def build_service(settings: Settings) -> QueryService:
    catalog = Catalog(settings.catalog_path)
    embeddings = FastEmbedModel(settings.embedding_model)
    vectors = MilvusVectorStore(
        settings.milvus_uri, settings.milvus_collection, settings.embedding_dimensions
    )
    graph = Neo4jGraphRepository(settings.neo4j_uri, settings.neo4j_user, settings.neo4j_password)
    for identity in json.loads(settings.auth_tokens_json).values():
        graph.seed_identity(Principal.model_validate(identity))
    resolver = AuthorizationResolver(catalog)
    pipeline = IngestionPipeline(
        catalog, embeddings, vectors, graph, StructuredKnowledgeExtractor()
    )
    retriever = HybridRetriever(
        resolver,
        VectorRetriever(vectors, embeddings, settings.vector_top_k, settings.similarity_threshold),
        GraphRetriever(graph, settings.graph_top_k),
        ScoreFusionReranker(settings.alpha, settings.beta, settings.gamma),
        settings.context_top_k,
    )
    llm = ChatCompletionsClient(settings.llm_base_url, settings.llm_api_key, settings.llm_model)
    return QueryService(resolver, retriever, llm, pipeline, settings.debug_retrieval)
