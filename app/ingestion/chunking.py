import hashlib
import json
import re

from app.models import Chunk, Document


def version_document(document: Document) -> Document:
    payload_data = document.model_dump(exclude={"version"})
    if document.source_metadata:
        payload_data["source_metadata"] = document.source_metadata.stable_dump()
    payload = json.dumps(payload_data, sort_keys=True)
    return document.model_copy(update={"version": hashlib.sha256(payload.encode()).hexdigest()})


def _section_chunks(text: str, size: int, overlap: int) -> list[tuple[list[str], str]]:
    """Keep Markdown sections intact where practical; split only long sections."""
    sections: list[tuple[list[str], str]] = []
    path: list[str] = []
    body: list[str] = []

    def flush() -> None:
        value = "\n".join(body).strip()
        if value:
            sections.append((path.copy(), value))
        body.clear()

    for line in text.splitlines():
        match = re.match(r"^(#{1,6})\s+(.+?)\s*$", line)
        if match:
            flush()
            level, title = len(match.group(1)), match.group(2)
            path[level - 1 :] = [title]
        else:
            body.append(line)
    flush()
    if not sections:
        sections = [([], text.strip())]

    results: list[tuple[list[str], str]] = []
    for section_path, section_text in sections:
        for offset in range(0, len(section_text), size - overlap):
            part = section_text[offset : offset + size].strip()
            if part:
                results.append((section_path, part))
    return results


def chunk_document(document: Document, size: int = 3000, overlap: int = 300) -> list[Chunk]:
    if not 0 <= overlap < size:
        raise ValueError("Require 0 <= overlap < chunk size")
    key = f"{document.id}:{document.version}"
    chunks = []
    for index, (heading_path, text) in enumerate(_section_chunks(document.text, size, overlap)):
        source_metadata = document.source_metadata
        if source_metadata:
            source_metadata = source_metadata.model_copy(update={"heading_path": heading_path})
        source_payload = source_metadata.stable_dump() if source_metadata else {}
        digest = hashlib.sha256(
            json.dumps([key, index, heading_path, text, source_payload], sort_keys=True).encode()
        ).hexdigest()
        chunks.append(
            Chunk(
                id=digest,
                document_id=document.id,
                resource_key=key,
                text=text,
                metadata=document.metadata,
                source_metadata=source_metadata,
            )
        )
    return chunks
