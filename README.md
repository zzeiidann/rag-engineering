# Authorization-Aware Hybrid Graph RAG

<p align="center">
  <strong>Retrieve the most relevant knowledge a user is actually allowed to access.</strong><br />
  A production-minded, API-first RAG system for access-controlled insurance knowledge.
</p>

<p align="center">
  <img src="https://img.shields.io/badge/FastAPI-0F766E?style=for-the-badge&logo=fastapi&logoColor=white" alt="FastAPI" />
  <img src="https://img.shields.io/badge/Flask-111827?style=for-the-badge&logo=flask&logoColor=white" alt="Flask" />
  <img src="https://img.shields.io/badge/Milvus-00A1EA?style=for-the-badge&logo=milvus&logoColor=white" alt="Milvus" />
  <img src="https://img.shields.io/badge/Neo4j-4581C3?style=for-the-badge&logo=neo4j&logoColor=white" alt="Neo4j" />
  <img src="https://img.shields.io/badge/Gemini-7C3AED?style=for-the-badge&logo=googlegemini&logoColor=white" alt="Gemini" />
  <img src="https://img.shields.io/badge/Docker-2496ED?style=for-the-badge&logo=docker&logoColor=white" alt="Docker" />
</p>

> Ordinary RAG can retrieve a perfect semantic match from the wrong customer or a confidential internal document. This project makes deterministic authorization part of retrieval itself—before reranking and before an LLM sees context.

## Highlights

| Capability | Implementation |
|---|---|
| Access control | Deterministic RBAC + client ownership + department/explicit permissions |
| Search | Milvus cosine vector retrieval, thresholding, and pre-search allowed-scope filter |
| Knowledge graph | Neo4j entities, topics, knowledge edges, and separate authorization edges |
| Hybrid ranking | Configurable vector + graph + reranker score fusion |
| Generation | Provider-agnostic OpenAI-compatible interface; Gemini configured locally |
| Control plane | Flask login, admin user/department/permission management, opaque token introspection |
| UI | Compact vanilla-JS enterprise workspace with source links and safe Markdown rendering |
| Ingestion | PDF / Markdown / TXT + public sitemap crawl with stable hashes and provenance |

## Architecture


### Security invariant

```text
Principal → allowed resource scope → retrieval → final ACL check → LLM context
```

The LLM is never an authorization decision-maker and never receives an unauthorized chunk. If an ACL, catalog revision, or dependency cannot be verified, the request fails closed.

## Access model

| Identity | Public | Own client records | Other clients | Department-scoped internal knowledge |
|---|:---:|:---:|:---:|:---:|
| Guest | ✅ | ❌ | ❌ | ❌ |
| Client | ✅ | ✅ | ❌ | ❌ |
| Internal employee | ✅ | Explicit permission only | Explicit permission only | Department / explicit permission |

Authorization metadata lives with each resource, for example:

```json
{
  "visibility": "client",
  "owner_client_id": "client_a",
  "allowed_roles": ["client", "internal"]
}
```

## Quick start

```bash
cp .env.example .env
# Set LLM_API_KEY and replace local demo secrets before using non-demo data.
docker compose up -d --build
```

Open:

- Workspace: http://localhost:5001
- Access management: http://localhost:5001/admin
- FastAPI docs: http://localhost:8000/docs
- Neo4j Browser: http://localhost:7474
- Milvus health/metrics UI: http://localhost:9091/webui/

For host-side API development, start the databases then run:

```bash
uv sync --frozen
docker compose up -d milvus neo4j
uv run uvicorn app.main:app --reload --no-access-log
```

## Demo questions

### Public product knowledge

- `What insurance products and services does Sun Life offer?`
- `What digital health solutions does Sun Life offer to members?`
- `Summarize Sun Life's insurance, investments, and financial advice offerings.`

### Authorization proof with synthetic data

| Sign-in context | Question | Expected result |
|---|---|---|
| Guest | `What is the pricing methodology?` | Public content only |
| Client A | `What is my coverage limit?` | Client A + public; never Client B |
| Actuarial employee | `How is risk pricing calculated?` | Actuarial methodology allowed |
| Sales employee | Same question | Actuarial methodology excluded |

The included sample corpus contains public documents, Client A/B policies, an actuarial methodology, claims SOP, and sales playbook. All private-looking content is synthetic.

## Ingestion

```text
Document → loader → section-aware chunks → ACL/provenance → embeddings → Milvus
         → deterministic entity/topic extraction → Neo4j → active catalog revision
```

Chunk IDs include document version, heading path, position, and text. Document versions include content, ACLs, and meaningful provenance—but exclude crawl time—so modified content is re-indexed without accidental ID reuse.

### Public Sun Life crawl

The crawler respects `robots.txt`, sitemap scope, canonical URLs, and `noindex`; it removes boilerplate and retains source URL, canonical URL, heading path, language, content hash, and crawl metadata.

```bash
# Review only
uv run python -m scripts.ingest_sunlife_website --max-pages 25

# Index with an internal token that has documents:write
INGEST_TOKEN='issued-token' \
  uv run python -m scripts.ingest_sunlife_website --execute --max-pages 25
```

The default scope is `https://www.sunlife.com/en/`. Run each regional website deliberately with its own scope; do not indiscriminately merge global and regional content.

## Verification

```bash
uv run pytest -q
uv run ruff check app scripts tests
uv run ruff format --check app scripts tests
uv run mypy app
docker compose config --quiet

# Retrieval metrics: Recall@K, MRR, authorization violation rate, latency
uv run python scripts/benchmark_retrieval.py --offline
```

The security tests cover guest isolation, Client A/B isolation, department permissions, pre-retrieval scope filtering, and the assertion that unauthorized text never reaches LLM context.

## What belongs in GitHub?

✅ Commit source code, Docker Compose, schemas, migrations, sample documents, seed scripts, tests, and a deliberately curated crawl manifest.

❌ Do **not** commit live database state, Docker volumes, `var/catalog.db`, Milvus data, Neo4j data, API keys, bearer tokens, or real customer documents. Runtime catalog data is excluded by `.gitignore` and database services persist in Docker volumes locally. To share a reproducible demo, use `data/sample/` and `scripts/seed_demo_data.py` instead.

## Scope and next steps

This is a local, portfolio-grade implementation. Production deployment should add OIDC/SSO, PostgreSQL-backed identity/catalog state, encrypted secrets, distributed locking, audit retention, malware/OCR processing, backup/restore, rate limiting, and a curated retrieval evaluation set. Authorization remains deterministic regardless of which LLM provider is used.

---

Built as an independent AI engineering portfolio project. The Sun Life name and public-source references are used only to demonstrate a retrieval workflow; this is not an official Sun Life product.
