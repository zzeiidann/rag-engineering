from pydantic import BaseModel, ConfigDict, Field

from app.auth.models import Principal


class QueryRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    query: str = Field(min_length=1, max_length=4000)
    # Optional compatibility assertion, never an authentication mechanism.
    principal: Principal | None = None


class IndexRequest(BaseModel):
    document_id: str = Field(pattern=r"^[a-zA-Z0-9_-]{1,100}$")
