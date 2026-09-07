from app.catalog import Catalog
from app.embeddings.base import EmbeddingModel
from app.graph.repository import GraphRepository
from app.ingestion.chunking import chunk_document, version_document
from app.ingestion.extractor import KnowledgeExtractor
from app.models import Document
from app.vectorstore.base import VectorStore


class IngestionPipeline:
    def __init__(
        self,
        catalog: Catalog,
        embeddings: EmbeddingModel,
        vectors: VectorStore,
        graph: GraphRepository,
        extractor: KnowledgeExtractor,
    ):
        self.catalog, self.embeddings, self.vectors = catalog, embeddings, vectors
        self.graph, self.extractor = graph, extractor

    def stage(self, document: Document) -> Document:
        document = version_document(document)
        self.extractor.extract(document)  # Validate before withdrawing existing version.
        self.catalog.stage(document)
        return document

    def index(self, document_id: str) -> Document:
        document = self.catalog.get(document_id, active_only=False)
        if document is None:
            raise KeyError(document_id)
        # Failed writes remain inactive and are safely retryable.
        self.catalog.stage(document)
        chunks = chunk_document(document)
        fragment = self.extractor.extract(document)
        embeddings = self.embeddings.embed_documents([chunk.text for chunk in chunks])
        self.vectors.replace(document.id, chunks, embeddings)
        self.graph.replace(document, chunks, fragment)
        self.catalog.activate(document)
        return document
