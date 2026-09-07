import argparse
import json
import statistics
import tempfile
from pathlib import Path

from app.auth.policies import can_read
from app.config import Settings
from app.service import QueryService
from scripts.demo import IDENTITIES, SCENARIOS


def benchmark(service: QueryService, offline: bool = False) -> dict:
    recalls, reciprocals, retrieval_times, rerank_times = [], [], [], []
    violations = total = 0
    rows = []
    for identity, query, relevant in SCENARIOS:
        principal = IDENTITIES[identity]
        candidates, metrics = service.retriever.retrieve(query, principal)
        ranked = list(dict.fromkeys(c.chunk.document_id for c in candidates))
        # Check every candidate, not merely deduplicated resources.
        for candidate in candidates:
            doc = service.resolver.catalog.get(candidate.chunk.document_id)
            violations += int(doc is None or not can_read(principal, doc.id, doc.metadata))
        total += len(candidates)
        recall = len(set(ranked) & relevant) / len(relevant) if relevant else None
        rr = next((1 / (i + 1) for i, doc in enumerate(ranked) if doc in relevant), 0.0)
        if relevant:
            recalls.append(recall)
            reciprocals.append(rr)
        retrieval_times.append(metrics["retrieval_latency_ms"])
        rerank_times.append(metrics["reranking_latency_ms"])
        rows.append(
            dict(
                identity=identity,
                retrieved=ranked,
                recall_at_k=recall,
                reciprocal_rank=rr if relevant else None,
            )
        )
    report = dict(
        mode="offline_test_doubles" if offline else "milvus_neo4j_fastembed",
        k=service.retriever.top_k,
        recall_at_k=statistics.mean(recalls),
        mrr=statistics.mean(reciprocals),
        authorization_violation_rate=violations / max(total, 1),
        candidates_evaluated=total,
        mean_retrieval_latency_ms=statistics.mean(retrieval_times),
        mean_reranking_latency_ms=statistics.mean(rerank_times),
        scenarios=rows,
    )
    if violations:
        raise AssertionError(json.dumps(report))
    return report


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--offline", action="store_true", help="Test doubles; not a semantic benchmark"
    )
    args = parser.parse_args()
    if args.offline:
        from tests.fakes import offline_service

        with tempfile.TemporaryDirectory() as directory:
            report = benchmark(offline_service(Path(directory)), offline=True)
    else:
        from app.container import build_service

        service = build_service(Settings())
        if len(service.resolver.catalog.list()) < 9:
            raise SystemExit("Seed demo data first; benchmark requires the shared catalog")
        report = benchmark(service)
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
