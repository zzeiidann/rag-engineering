import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from app.models import Document


class Catalog:
    """Durable authority. Staged/failed versions never become retrievable."""

    def __init__(self, path: str):
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.path = path
        with self.connect() as conn:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute(
                "CREATE TABLE IF NOT EXISTS documents "
                "(id TEXT PRIMARY KEY, payload TEXT NOT NULL, active INTEGER NOT NULL)"
            )

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self.path, timeout=30)
        try:
            with conn:
                yield conn
        finally:
            conn.close()

    def stage(self, document: Document) -> None:
        with self.connect() as conn:
            conn.execute(
                "INSERT INTO documents VALUES (?, ?, 0) "
                "ON CONFLICT(id) DO UPDATE SET payload=excluded.payload, active=0",
                (document.id, document.model_dump_json()),
            )

    def activate(self, document: Document) -> None:
        with self.connect() as conn:
            cursor = conn.execute(
                "UPDATE documents SET active=1 WHERE id=? AND payload=?",
                (document.id, document.model_dump_json()),
            )
            if cursor.rowcount != 1:
                raise RuntimeError("Document changed during indexing")

    def list(self, active_only: bool = True) -> list[Document]:
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT payload FROM documents" + (" WHERE active=1" if active_only else "")
            ).fetchall()
        return [Document.model_validate_json(row[0]) for row in rows]

    def get(self, document_id: str, active_only: bool = True) -> Document | None:
        with self.connect() as conn:
            row = conn.execute(
                "SELECT payload FROM documents WHERE id=?"
                + (" AND active=1" if active_only else ""),
                (document_id,),
            ).fetchone()
        return Document.model_validate_json(row[0]) if row else None
