from __future__ import annotations

import argparse
import sys
import tempfile
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from wavemind import WaveMind
from wavemind.encoders import HashingTextEncoder


LATENCY_NAMESPACE = "project:latency-research"
PRICING_NAMESPACE = "project:pricing-research"


def configure_stdio() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")


def build_memory(db_path: str | Path | None = None) -> WaveMind:
    return WaveMind(
        db_path=db_path,
        encoder=HashingTextEncoder(vector_dim=256),
        index_kind="numpy",
        width=32,
        height=32,
        layers=2,
        evolve_on_feed=1,
        field_weight=0.0,
        vector_weight=0.70,
        priority_weight=0.30,
        lexical_weight=0.25,
        short_query_lexical_weight=0.70,
        rerank_k=8,
    )


def seed_research_notebook(memory: WaveMind) -> int:
    memory.remember(
        "Hypothesis: latency spikes are caused by nightly index rebuilds.",
        namespace=LATENCY_NAMESPACE,
        tags=["hypothesis", "performance"],
        metadata={"source": "incident-review-2026-06", "status": "expired"},
        ttl_seconds=-1,
        priority=2.0,
    )
    memory.remember(
        "Confirmed finding: p95 latency improved after reducing rerank_k to 8.",
        namespace=LATENCY_NAMESPACE,
        tags=["finding", "performance"],
        metadata={
            "source": "benchmark-2026-07-03",
            "metric": "p95_latency",
            "before_ms": 86.1,
            "after_ms": 41.4,
        },
        priority=8.0,
    )
    memory.remember(
        "Open hypothesis: quantized vectors may reduce memory footprint but need recall checks.",
        namespace=LATENCY_NAMESPACE,
        tags=["hypothesis", "indexing"],
        metadata={"source": "roadmap-notes", "status": "open"},
        ttl_seconds=14 * 24 * 3600,
        priority=3.0,
    )
    memory.remember(
        "Decision: keep WaveMind as a top-k reranker instead of full-scan field scoring.",
        namespace=LATENCY_NAMESPACE,
        tags=["decision", "architecture"],
        metadata={"source": "architecture-review", "owner": "memory-core"},
        priority=5.0,
    )
    memory.remember(
        "Action item: rerun service-mode Qdrant and persisted FAISS latency profiles.",
        namespace=LATENCY_NAMESPACE,
        tags=["action", "benchmark"],
        metadata={"source": "benchmark-plan", "due": "next-run"},
        priority=4.0,
    )
    memory.remember(
        "Confirmed finding: pricing conversion lift came from annual discount copy.",
        namespace=PRICING_NAMESPACE,
        tags=["finding", "pricing"],
        metadata={"source": "pricing-review"},
        priority=6.0,
    )
    return memory.purge_expired()


def run_research_checks(memory: WaveMind) -> dict[str, object]:
    purged = seed_research_notebook(memory)
    finding_hits = memory.query(
        "what improved p95 latency?",
        namespace=LATENCY_NAMESPACE,
        tags=["finding", "performance"],
        top_k=2,
    )
    expired_hypothesis_hits = memory.query(
        "nightly index rebuild hypothesis",
        namespace=LATENCY_NAMESPACE,
        tags=["hypothesis"],
        top_k=3,
    )
    brief_hits = memory.query(
        "latency research brief decision action benchmark",
        namespace=LATENCY_NAMESPACE,
        top_k=4,
    )
    pricing_hits = memory.query(
        "pricing conversion lift",
        namespace=PRICING_NAMESPACE,
        top_k=1,
    )
    latency_cross_check = memory.query(
        "pricing conversion lift",
        namespace=LATENCY_NAMESPACE,
        top_k=3,
    )
    return {
        "purged": purged,
        "finding_hits": finding_hits,
        "expired_hypothesis_hits": expired_hypothesis_hits,
        "brief_hits": brief_hits,
        "pricing_hits": pricing_hits,
        "latency_cross_check": latency_cross_check,
        "stats": memory.stats(namespace=LATENCY_NAMESPACE),
    }


def print_results(results: dict[str, object]) -> None:
    print("WaveMind research notebook memory demo")
    print()
    print(f"[purge] expired hypotheses removed: {results['purged']}")

    finding_hits = results["finding_hits"]
    print()
    print('Query latency project: "what improved p95 latency?"')
    for index, hit in enumerate(finding_hits, start=1):
        source = hit.metadata.get("source", "-")
        print(f'-> Result {index} ({hit.score:.2f}) source={source}: "{hit.text}"')
    if finding_hits and finding_hits[0].metadata.get("source") == "benchmark-2026-07-03":
        print("[ok] confirmed finding is recalled with source metadata")

    expired_hits = results["expired_hypothesis_hits"]
    print()
    print('Query latency project: "nightly index rebuild hypothesis"')
    if all("nightly index rebuilds" not in hit.text for hit in expired_hits):
        print("[ok] expired hypothesis is not recalled")
    for index, hit in enumerate(expired_hits, start=1):
        tags = ",".join(hit.tags)
        print(f'-> Result {index} ({hit.score:.2f}) [{tags}]: "{hit.text}"')

    brief_hits = results["brief_hits"]
    print()
    print('Query latency project: "latency research brief decision action benchmark"')
    for index, hit in enumerate(brief_hits, start=1):
        tags = ",".join(hit.tags)
        source = hit.metadata.get("source", "-")
        print(f'-> Result {index} ({hit.score:.2f}) [{tags}] source={source}: "{hit.text}"')

    pricing_hits = results["pricing_hits"]
    latency_cross_check = results["latency_cross_check"]
    print()
    print('Query pricing project: "pricing conversion lift"')
    for index, hit in enumerate(pricing_hits, start=1):
        print(f'-> Result {index} ({hit.score:.2f}): "{hit.text}"')
    if pricing_hits and all("pricing conversion" not in hit.text for hit in latency_cross_check):
        print("[ok] project namespaces keep analyst notes isolated")

    stats = results["stats"]
    print()
    print(
        "[ok] "
        f"latency active={stats['active_memories']} "
        f"expired={stats['expired_memories']} "
        f"audit_events={stats['audit_events']} "
        f"index_healthy={stats['index_healthy']}"
    )


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run an offline research notebook / analyst memory demo."
    )
    parser.add_argument(
        "--db",
        type=Path,
        help="Optional SQLite path. Defaults to a temporary database.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    configure_stdio()
    args = parse_args(argv)
    if args.db is not None:
        args.db.parent.mkdir(parents=True, exist_ok=True)
        with build_memory(args.db) as memory:
            results = run_research_checks(memory)
            print_results(results)
        print()
        print(f"[store] SQLite database: {args.db}")
        return 0

    with tempfile.TemporaryDirectory() as tmp:
        db_path = Path(tmp) / "research-notebook.sqlite3"
        with build_memory(db_path) as memory:
            results = run_research_checks(memory)
            print_results(results)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
