from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

Role = Literal["guest", "client", "internal"]


class Principal(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    user_id: str = Field(min_length=1, max_length=128)
    role: Role
    client_id: str | None = None
    department: str | None = None
    permissions: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def valid_identity(self) -> "Principal":
        if self.role == "client" and not self.client_id:
            raise ValueError("Client identity requires client_id")
        if self.role != "client" and self.client_id:
            raise ValueError("Only clients have client_id")
        if self.role != "internal" and (self.department or self.permissions):
            raise ValueError("Only internal identities may carry employee permissions")
        return self


class ResourceMetadata(BaseModel):
    model_config = ConfigDict(extra="forbid")
    visibility: Literal["public", "client", "internal"]
    owner_client_id: str | None = None
    allowed_roles: list[Role] = Field(default_factory=list)
    allowed_departments: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def valid_owner(self) -> "ResourceMetadata":
        if self.visibility == "client" and not self.owner_client_id:
            raise ValueError("Client resources require owner_client_id")
        if self.visibility != "client" and self.owner_client_id:
            raise ValueError("Only client resources have owners")
        return self
