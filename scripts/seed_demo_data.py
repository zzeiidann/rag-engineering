"""Seed through the authenticated API, without sending demo text to an LLM."""

import argparse
import os

import httpx

from scripts.demo import documents


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--api-url", default="http://localhost:8000")
    args = parser.parse_args()
    token = os.environ.get("INGEST_TOKEN")
    if not token:
        raise SystemExit("Set INGEST_TOKEN to a configured documents:write bearer token")
    with httpx.Client(
        base_url=args.api_url, headers={"Authorization": f"Bearer {token}"}, timeout=120
    ) as client:
        for document in documents():
            response = client.post(
                "/documents",
                data={
                    "document_id": document.id,
                    "title": document.title,
                    "metadata": document.metadata.model_dump_json(),
                },
                files={"file": (f"{document.id}.md", document.text.encode(), "text/markdown")},
            )
            response.raise_for_status()
            response = client.post("/documents/index", json={"document_id": document.id})
            response.raise_for_status()
            print(f"Indexed {document.id}")


if __name__ == "__main__":
    main()
