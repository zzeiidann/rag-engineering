import json
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from app.api.routes import router
from app.auth.models import Principal
from app.config import Settings
from app.service import QueryService


def create_app(
    settings: Settings | None = None, query_service: QueryService | None = None
) -> FastAPI:
    config = settings or Settings()

    @asynccontextmanager
    async def lifespan(api: FastAPI) -> AsyncIterator[None]:
        logging.basicConfig(level=logging.INFO, format="%(message)s")
        # HTTP client logs may contain sensitive URLs; keep them quiet.
        logging.getLogger("httpx").setLevel(logging.WARNING)
        if query_service is None:
            from app.container import build_service

            api.state.service = build_service(config)
        else:
            api.state.service = query_service
        api.state.identities = {
            token: Principal.model_validate(identity)
            for token, identity in json.loads(config.auth_tokens_json).items()
        }
        if any(not token for token in api.state.identities):
            raise ValueError("Authentication tokens must not be empty")
        yield
        graph = api.state.service.ingestion.graph
        if hasattr(graph, "driver"):
            graph.driver.close()
        vectors = api.state.service.ingestion.vectors
        if hasattr(vectors, "client"):
            vectors.client.close()

    api = FastAPI(title="Authorization-Aware Hybrid Graph RAG", lifespan=lifespan)
    api.include_router(router)

    @api.exception_handler(RequestValidationError)
    async def validation_error(request: Request, exc: RequestValidationError) -> JSONResponse:
        # FastAPI's default validation response can echo submitted tokens and document text.
        return JSONResponse(status_code=422, content={"error": "invalid_request"})

    @api.exception_handler(Exception)
    async def dependency_error(request: Request, exc: Exception) -> JSONResponse:
        logging.getLogger("rag.audit").error(
            json.dumps({"event": "request_failed", "error_type": type(exc).__name__})
        )
        return JSONResponse(status_code=503, content={"error": "service_unavailable"})

    return api


app = create_app()
