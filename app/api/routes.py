from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile

from app.api.authentication import authenticate, require_ingest
from app.api.schemas import IndexRequest, QueryRequest
from app.auth.models import Principal, ResourceMetadata
from app.ingestion.loaders import load_document
from app.models import Document
from app.service import QueryService

router = APIRouter()
Identity = Annotated[Principal, Depends(authenticate)]


def service(request: Request) -> QueryService:
    return request.app.state.service


@router.post("/query")
def query(body: QueryRequest, principal: Identity, request: Request) -> dict:
    if body.principal is not None and body.principal != principal:
        raise HTTPException(403, "Request principal does not match authenticated identity")
    return service(request).query(body.query, principal)


@router.post("/documents", status_code=201)
def upload_document(
    request: Request,
    principal: Identity,
    file: Annotated[UploadFile, File()],
    document_id: Annotated[str, Form()],
    title: Annotated[str, Form()],
    metadata: Annotated[str, Form()],
) -> dict:
    require_ingest(principal)
    content = file.file.read(5_000_001)
    if len(content) > 5_000_000:
        raise HTTPException(413, "Maximum document size is 5 MB")
    try:
        document = Document(
            id=document_id,
            title=title,
            text=load_document(file.filename or "", content),
            metadata=ResourceMetadata.model_validate_json(metadata),
        )
        with service(request).lock:
            staged = service(request).ingestion.stage(document)
        return dict(document_id=staged.id, version=staged.version, status="staged")
    except (ValueError, UnicodeError) as exc:
        raise HTTPException(422, "Invalid document or authorization metadata") from exc


@router.post("/documents/index")
def index_document(body: IndexRequest, principal: Identity, request: Request) -> dict:
    require_ingest(principal)
    try:
        with service(request).lock:
            doc = service(request).ingestion.index(body.document_id)
        return dict(document_id=doc.id, version=doc.version, status="indexed")
    except KeyError as exc:
        raise HTTPException(404, "Document not found") from exc


@router.get("/documents")
def list_documents(principal: Identity, request: Request) -> list[dict]:
    app_service = service(request)
    with app_service.lock:
        scope = set(app_service.resolver.allowed_scope(principal))
        return [
            dict(document_id=d.id, title=d.title, version=d.version)
            for d in app_service.resolver.catalog.list()
            if f"{d.id}:{d.version}" in scope
        ]


@router.get("/graph/entities/{entity_id}")
def entity(entity_id: str, principal: Identity, request: Request) -> list[dict]:
    app_service = service(request)
    with app_service.lock:
        scope = app_service.resolver.allowed_scope(principal)
        entities = app_service.ingestion.graph.get_related_entities(entity_id, scope)
    if not entities:
        raise HTTPException(404, "Entity not found")
    return entities


@router.get("/health")
def health(request: Request) -> dict:
    app_service = service(request)
    try:
        app_service.resolver.catalog.list()
        # Check both backing databases on each readiness probe.
        graph = app_service.ingestion.graph
        graph.get_allowed_resources(Principal(user_id="health", role="guest"), [])
        vectors = app_service.ingestion.vectors
        if hasattr(vectors, "client") and hasattr(vectors, "collection"):
            vectors.client.has_collection(vectors.collection)
        return {"status": "ok"}
    except Exception as exc:
        raise HTTPException(503, "Dependency unavailable") from exc
