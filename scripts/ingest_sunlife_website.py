"""Discover, review and index public Sun Life website pages through the authenticated API."""

from __future__ import annotations

import argparse
import json
import os
from datetime import UTC, datetime
from pathlib import Path

import httpx

from app.auth.models import ResourceMetadata
from app.ingestion.web import WebsiteCrawler


def read_manifest(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}
    records = {}
    for line in path.read_text().splitlines():
        try:
            row = json.loads(line)
            if row.get("status") == "indexed":
                records[row["canonical_url"]] = row["content_hash"]
        except (KeyError, json.JSONDecodeError):
            continue
    return records


def append_manifest(path: Path, row: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as output:
        output.write(json.dumps(row, sort_keys=True) + "\n")


def index_page(client: httpx.Client, document, execute: bool) -> str:
    if not execute:
        return "reviewed"
    uploaded = client.post(
        "/documents",
        data={
            "document_id": document.id,
            "title": document.title,
            "metadata": document.metadata.model_dump_json(),
            "source_metadata": document.source_metadata.model_dump_json(),
        },
        files={"file": (f"{document.id}.md", document.text.encode(), "text/markdown")},
    )
    uploaded.raise_for_status()
    indexed = client.post("/documents/index", json={"document_id": document.id})
    indexed.raise_for_status()
    return "indexed"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seed-url", default="https://www.sunlife.com/en/")
    parser.add_argument("--sitemap-url", default="https://www.sunlife.com/en/sitemap.xml")
    parser.add_argument("--path-prefix", default="/en/")
    parser.add_argument("--country", default="global")
    parser.add_argument("--max-pages", type=int, default=25)
    parser.add_argument("--delay", type=float, default=0.5)
    parser.add_argument("--api-url", default="http://localhost:8000")
    parser.add_argument("--manifest", type=Path, default=Path("var/sunlife-crawl.jsonl"))
    parser.add_argument("--execute", action="store_true", help="Stage and index changed pages")
    parser.add_argument(
        "--force", action="store_true", help="Index even when manifest hash matches"
    )
    args = parser.parse_args()
    if args.max_pages < 1:
        raise SystemExit(
            "--max-pages must be at least 1; increase it deliberately for larger crawls"
        )
    token = os.getenv("INGEST_TOKEN")
    if args.execute and not token:
        raise SystemExit("Set INGEST_TOKEN to a documents:write bearer token before --execute")

    existing = read_manifest(args.manifest)
    crawler = WebsiteCrawler(args.seed_url, args.path_prefix, args.delay)
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    reviewed = indexed = unchanged = failed = 0
    try:
        with httpx.Client(base_url=args.api_url, headers=headers, timeout=180) as api:
            for page in crawler.crawl(args.sitemap_url, args.max_pages):
                document = page.document(args.country, ResourceMetadata(visibility="public"))
                if not args.force and existing.get(page.canonical_url) == page.content_hash:
                    unchanged += 1
                    continue
                try:
                    status = index_page(api, document, args.execute)
                except httpx.HTTPError as exc:
                    status = "failed"
                    failed += 1
                    error = type(exc).__name__
                    if isinstance(exc, httpx.HTTPStatusError):
                        error = f"{error}:{exc.response.status_code}"
                else:
                    error = None
                row = dict(
                    status=status,
                    canonical_url=page.canonical_url,
                    source_url=page.url,
                    document_id=document.id,
                    title=page.title,
                    content_hash=page.content_hash,
                    crawled_at=datetime.now(UTC).isoformat(),
                )
                if error:
                    row["error"] = error
                append_manifest(args.manifest, row)
                print(json.dumps(row, ensure_ascii=False))
                reviewed += 1
                indexed += status == "indexed"
    finally:
        crawler.close()
    print(json.dumps(dict(reviewed=reviewed, indexed=indexed, unchanged=unchanged, failed=failed)))


if __name__ == "__main__":
    main()
