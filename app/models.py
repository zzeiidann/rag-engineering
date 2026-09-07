from pydantic import BaseModel, Field

from app.auth.models import ResourceMetadata


class Document(BaseModel):
    id: str = Field(pattern=r"^[a-zA-Z0-9_-]{1,100}$")
    title: str = Field(min_length=1, max_length=200)
    text: str = Field(min_length=1, max_length=2_000_000)
    metadata: ResourceMetadata
    version: str = ""


class Chunk(BaseModel):
    id: str
    document_id: str
    resource_key: str
    text: str
    metadata: ResourceMetadata


class Candidate(BaseModel):
    chunk: Chunk
    vector_score: float = 0
    graph_score: float = 0
    reranker_score: float = 0
    score: float = 0


class ContextItem(BaseModel):
    source_id: str
    document_id: str
    text: str
