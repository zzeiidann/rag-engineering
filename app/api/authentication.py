import secrets

from fastapi import HTTPException, Request

from app.auth.models import Principal


def authenticate(request: Request) -> Principal:
    header = request.headers.get("Authorization")
    if header is None:
        return Principal(user_id="anonymous", role="guest")
    scheme, _, token = header.partition(" ")
    if scheme.lower() != "bearer" or not token:
        raise HTTPException(401, "Invalid authentication")
    for expected, principal in request.app.state.identities.items():
        if secrets.compare_digest(token.encode(), expected.encode()):
            return principal
    raise HTTPException(401, "Invalid authentication")


def require_ingest(principal: Principal) -> None:
    if principal.role != "internal" or "documents:write" not in principal.permissions:
        raise HTTPException(403, "Document ingestion permission required")
