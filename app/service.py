import json
import logging
from threading import RLock
from time import perf_counter
from typing import Any
from uuid import uuid4

from app.auth.models import Principal
from app.auth.resolver import AuthorizationResolver
from app.ingestion.pipeline import IngestionPipeline
from app.llm.base import LLMClient
from app.models import ContextItem
from app.retrieval.hybrid import HybridRetriever

logger = logging.getLogger("rag.audit")


class QueryService:
    def __init__(
        self,
        resolver: AuthorizationResolver,
        retriever: HybridRetriever,
        llm: LLMClient,
        ingestion: IngestionPipeline,
        debug: bool = False,
    ):
        self.resolver, self.retriever, self.llm = resolver, retriever, llm
        self.ingestion, self.debug = ingestion, debug
        # The supported deployment is one API worker; mutation and generation share a lock.
        self.lock = RLock()

    def query(self, query: str, principal: Principal) -> dict:
        query_id = str(uuid4())
        with self.lock:
            candidates, metrics = self.retriever.retrieve(query, principal)
            context = []
            for candidate in candidates:
                if self.resolver.validate_chunk(principal, candidate.chunk):
                    context.append(
                        ContextItem(
                            source_id=candidate.chunk.id,
                            document_id=candidate.chunk.document_id,
                            text=candidate.chunk.text,
                        )
                    )
                else:
                    metrics["authorization_filtered"] += 1
            start = perf_counter()
            answer = (
                self.llm.generate(query, context)
                if context
                else "I don't have relevant information available to answer that question."
            )
            metrics["llm_latency_ms"] = (perf_counter() - start) * 1000
            logger.info(
                json.dumps(
                    dict(
                        event="query_completed",
                        query_id=query_id,
                        principal_role=principal.role,
                        **metrics,
                    )
                )
            )
            result: dict[str, Any] = dict(
                query_id=query_id,
                answer=answer,
                sources=[dict(source_id=c.source_id, document_id=c.document_id) for c in context],
                retrieved_resources=sorted({c.document_id for c in context}),
            )
            if self.debug and "retrieval:debug" in principal.permissions:
                result["retrieval_debug"] = metrics
            return result
