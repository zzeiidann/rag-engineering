# Local verification

Verified on 2026-09-07 with Python 3.11.14 and the committed dependency lockfile.

| Check | Result |
|---|---|
| Pytest | 33 passed, 1 live-database test skipped |
| Ruff lint | Passed |
| Ruff formatting | Passed |
| Mypy | Passed, 38 source files |
| Application imports | All 37 discovered submodules imported |
| Docker Compose configuration | Passed with standalone Docker Compose 2.40.3 |
| Offline benchmark | Recall@5 1.0, MRR 1.0, authorization violation rate 0.0 |
| Real BGE embedding smoke test | Document and query embeddings both have 384 dimensions |
| Real BGE ingestion with in-memory stores | All 9 demo documents indexed; authorization violation rate 0.0 |
| Recording LLM context checks | Guest, Client A and sales contexts exclude private Client B and actuarial canaries |

The in-memory results are regression evidence, not live Milvus/Neo4j performance results. Real BGE embeddings were also tested with the same in-memory stores; those six synthetic scenarios achieved Recall@5 and MRR of 1.0. These small fixtures are not representative retrieval-quality benchmarks.

The local machine has a Docker CLI and standalone Compose, but no running Docker engine or Docker Desktop application. Container builds, live database integration and the live semantic benchmark could not be executed here. A separate CI database job and opt-in test are included. No actual LLM provider call was made because no API key was configured; adapter request serialization and context isolation were tested with recording/mocked clients.

Pytest reports two upstream Starlette/httpx deprecation warnings; they do not fail the suite.
