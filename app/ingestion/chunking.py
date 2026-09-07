import hashlib
import json

from app.models import Chunk, Document


def version_document(document: Document) -> Document:
    payload = json.dumps(document.model_dump(exclude={"version"}), sort_keys=True)
    return document.model_copy(update={"version": hashlib.sha256(payload.encode()).hexdigest()})


def chunk_document(document: Document, size: int = 1200, overlap: int = 150) -> list[Chunk]:
    if not 0 <= overlap < size:
        raise ValueError("Require 0 <= overlap < chunk size")
    key = f"{document.id}:{document.version}"
    chunks = []
    for offset in range(0, len(document.text), size - overlap):
        text = document.text[offset : offset + size]
        digest = hashlib.sha256(f"{key}:{offset}:{text}".encode()).hexdigest()
        chunks.append(
            Chunk(
                id=digest,
                document_id=document.id,
                resource_key=key,
                text=text,
                metadata=document.metadata,
            )
        )
    return chunks
