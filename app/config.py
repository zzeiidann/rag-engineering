from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")
    catalog_path: str = "var/catalog.db"
    milvus_uri: str = "http://localhost:19530"
    milvus_collection: str = "authorized_chunks"
    neo4j_uri: str = "bolt://localhost:7687"
    neo4j_user: str = "neo4j"
    neo4j_password: str = "local-graph-password"
    embedding_model: str = "BAAI/bge-small-en-v1.5"
    embedding_dimensions: int = 384
    llm_api_key: str = ""
    llm_base_url: str = "https://api.mistral.ai/v1"
    llm_model: str = "mistral-small-latest"
    # JSON mapping of opaque bearer tokens to trusted Principal objects.
    auth_tokens_json: str = "{}"
    debug_retrieval: bool = False
    vector_top_k: int = Field(20, ge=1, le=100)
    graph_top_k: int = Field(20, ge=1, le=100)
    context_top_k: int = Field(5, ge=1, le=20)
    similarity_threshold: float = Field(0.35, ge=-1, le=1)
    alpha: float = Field(0.65, ge=0)
    beta: float = Field(0.25, ge=0)
    gamma: float = Field(0.10, ge=0)

    @model_validator(mode="after")
    def valid_weights(self) -> "Settings":
        if self.alpha + self.beta + self.gamma == 0:
            raise ValueError("At least one scoring weight must be positive")
        return self
