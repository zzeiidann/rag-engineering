import json

from pymilvus import DataType, MilvusClient

from app.models import Candidate, Chunk


class MilvusVectorStore:
    def __init__(self, uri: str, collection: str, dimensions: int):
        self.client = MilvusClient(uri=uri, timeout=30)
        self.collection = collection
        if not self.client.has_collection(collection):
            schema = self.client.create_schema(auto_id=False, enable_dynamic_field=False)
            for name, length in [("id", 64), ("document_id", 100), ("resource_key", 180)]:
                schema.add_field(name, DataType.VARCHAR, max_length=length, is_primary=name == "id")
            schema.add_field("text", DataType.VARCHAR, max_length=16384)
            schema.add_field("metadata", DataType.JSON)
            schema.add_field("vector", DataType.FLOAT_VECTOR, dim=dimensions)
            indexes = self.client.prepare_index_params()
            indexes.add_index("vector", index_type="AUTOINDEX", metric_type="COSINE")
            self.client.create_collection(
                collection, schema=schema, index_params=indexes, consistency_level="Strong"
            )

    def replace(self, document_id: str, chunks: list[Chunk], embeddings: list[list[float]]) -> None:
        self.client.delete(self.collection, filter=f"document_id == {json.dumps(document_id)}")
        rows = [
            dict(
                id=c.id,
                document_id=c.document_id,
                resource_key=c.resource_key,
                text=c.text,
                metadata=c.metadata.model_dump(),
                vector=e,
            )
            for c, e in zip(chunks, embeddings, strict=True)
        ]
        if rows:
            self.client.upsert(self.collection, rows)
        # Milvus seals growing segments asynchronously. Calling flush for every
        # document hits the server's strict flush rate limiter during ingestion;
        # strong-consistency searches still observe completed upserts.

    def search(
        self, embedding: list[float], scope: list[str], top_k: int, threshold: float
    ) -> list[Candidate]:
        if not scope:
            return []
        # Filter is executed inside Milvus before ANN ranking. Never query an empty scope.
        results = self.client.search(
            self.collection,
            data=[embedding],
            filter=f"resource_key in {json.dumps(scope)}",
            limit=top_k,
            output_fields=["id", "document_id", "resource_key", "text", "metadata"],
            search_params={"metric_type": "COSINE", "params": {}},
            consistency_level="Strong",
        )
        return [
            Candidate(
                chunk=Chunk.model_validate(hit["entity"]), vector_score=float(hit["distance"])
            )
            for hit in results[0]
            if float(hit["distance"]) >= threshold
        ]
