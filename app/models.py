from typing import Literal
from urllib.parse import urlsplit

from pydantic import BaseModel, Field, field_validator

from app.auth.models import ResourceMetadata


class SourceMetadata(BaseModel):
    """Public provenance, kept separately from authorization metadata."""

    source_type: Literal["upload", "web"] = "upload"
    source_url: str | None = Field(default=None, max_length=2048)
    canonical_url: str | None = Field(default=None, max_length=2048)
    language: str | None = Field(default=None, max_length=20)
    country: str | None = Field(default=None, max_length=20)
    description: str | None = Field(default=None, max_length=1000)
    heading_path: list[str] = Field(default_factory=list)
    source_last_modified: str | None = Field(default=None, max_length=64)
    crawled_at: str | None = Field(default=None, max_length=64)
    content_hash: str | None = Field(default=None, max_length=64)

    @field_validator("source_url", "canonical_url")
    @classmethod
    def source_url_is_safe(cls, value: str | None) -> str | None:
        if value is None:
            return value
        parsed = urlsplit(value)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ValueError("Source URL must be an absolute HTTP(S) URL")
        return value

    def stable_dump(self) -> dict:
        return self.model_dump(exclude={"crawled_at"})


class Document(BaseModel):
    id: str = Field(pattern=r"^[a-zA-Z0-9_-]{1,100}$")
    title: str = Field(min_length=1, max_length=200)
    text: str = Field(min_length=1, max_length=2_000_000)
    metadata: ResourceMetadata
    source_metadata: SourceMetadata | None = None
    version: str = ""


class Chunk(BaseModel):
    id: str
    document_id: str
    resource_key: str
    text: str
    metadata: ResourceMetadata
    source_metadata: SourceMetadata | None = None


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
