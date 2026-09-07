import secrets

import httpx
from fastapi import HTTPException, Request

from app.auth.models import Principal


def authenticate(request: Request) -> Principal:
    header = request.headers.get("Authorization")
    if header is None:
        return Principal(user_id="anonymous", role="guest")
    scheme, _, token = header.partition(" ")
    if scheme.lower() != "bearer" or not token:
        raise HTTPException(401, "Invalid authentication")
    if request.app.state.auth_service_url:
        try:
            response = httpx.post(
                f"{request.app.state.auth_service_url}/api/introspect",
                headers={
                    "Authorization": f"Bearer {token}",
                    "X-Auth-Service-Secret": request.app.state.auth_service_secret,
                },
                timeout=request.app.state.auth_service_timeout_seconds,
            )
        except httpx.HTTPError as exc:
            raise HTTPException(503, "Authentication service unavailable") from exc
        if response.status_code == 401:
            raise HTTPException(401, "Invalid authentication")
        if response.status_code != 200:
            raise HTTPException(503, "Authentication service unavailable")
        try:
            payload = response.json()
            if not payload.get("active"):
                raise HTTPException(401, "Invalid authentication")
            return Principal.model_validate(payload["principal"])
        except (KeyError, ValueError, TypeError) as exc:
            raise HTTPException(503, "Invalid authentication service response") from exc
    for expected, principal in request.app.state.identities.items():
        if secrets.compare_digest(token.encode(), expected.encode()):
            return principal
    raise HTTPException(401, "Invalid authentication")


def require_ingest(principal: Principal) -> None:
    if principal.role != "internal" or "documents:write" not in principal.permissions:
        raise HTTPException(403, "Document ingestion permission required")
