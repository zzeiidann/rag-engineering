from app.auth.models import Principal, ResourceMetadata


def can_read(principal: Principal, resource_id: str, meta: ResourceMetadata) -> bool:
    """Deny by default; permissions originate only from trusted authentication."""
    if meta.allowed_roles and principal.role not in meta.allowed_roles:
        return False
    if meta.visibility == "public":
        return True
    if meta.visibility == "client":
        if principal.role == "client":
            return principal.client_id == meta.owner_client_id
        return principal.role == "internal" and (
            f"client:read:{meta.owner_client_id}" in principal.permissions
            or f"resource:read:{resource_id}" in principal.permissions
        )
    if principal.role != "internal":
        return False
    return (
        principal.department in meta.allowed_departments
        or f"resource:read:{resource_id}" in principal.permissions
        or "internal:read:all" in principal.permissions
    )
