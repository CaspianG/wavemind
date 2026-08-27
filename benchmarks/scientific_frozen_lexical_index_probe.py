from __future__ import annotations

import json
import sys
from pathlib import Path
from statistics import quantiles
from time import perf_counter


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from benchmarks.scientific_frozen_lexical_index import FrozenLexicalIndex  # noqa: E402
from wavemind.evidence import (  # noqa: E402
    attach_artifact_integrity,
    canonical_json_bytes,
    file_sha256,
    sha256_bytes,
)
from wavemind.scientific_memory import MemoryDefinition, MemoryKind  # noqa: E402
from wavemind.scientific_reconciliation import (  # noqa: E402
    ProofCarryingStateReconciler,
)


OUTPUT = ROOT / "benchmarks" / "scientific_frozen_lexical_index_probe_results.json"
INDEX = ROOT / "benchmarks" / ".scientific_frozen_lexical_index_probe.sqlite3"
DEFINITION_COUNT = 10_000
QUERY_COUNT = 40
REPEATS = 3
SOURCES = (
    ROOT / "benchmarks" / "scientific_frozen_lexical_index.py",
    ROOT / "benchmarks" / "scientific_frozen_lexical_index_probe.py",
    ROOT / "benchmarks" / "scientific_longmemeval_v2_backend_indexed_prototype.py",
)


def _definitions() -> dict[str, MemoryDefinition]:
    definitions: dict[str, MemoryDefinition] = {}
    for index in range(DEFINITION_COUNT):
        content = " ".join(
            (
                f"document {index}",
                f"cluster {index % 97}",
                f"route {index % 43}",
                f"state {index % 29}",
                f"account {index % 211}",
                "workflow checkout delivery support update",
                " ".join(f"filler-{offset}" for offset in range(40)),
            )
        )
        provenance = [f"source-order:{index}", "memory-operation:1"]
        if index % 113 == 0:
            provenance.append("memory-tombstone:1")
        definitions[f"memory-{index:05d}"] = MemoryDefinition(
            memory_id=f"memory-{index:05d}",
            kind=MemoryKind.FACT,
            content=content,
            provenance=tuple(provenance),
            estimated_tokens=32 + (index % 9),
            estimated_latency_ms=0.1,
            safety_risk=0.0,
        )
    return definitions


def _queries() -> tuple[str, ...]:
    return tuple(
        f"Find account {index % 211} cluster {index % 97} "
        f"route {index % 43} state {index % 29} checkout update"
        for index in range(QUERY_COUNT)
    )


def _p95(values: list[float]) -> float:
    if len(values) == 1:
        return values[0]
    return float(quantiles(values, n=100, method="inclusive")[94])


def main() -> int:
    definitions = _definitions()
    queries = _queries()
    workload = {
        "definition_count": len(definitions),
        "query_count": len(queries),
        "generator": "deterministic-modular-synthetic-v1",
        "queries": list(queries),
    }
    reference = ProofCarryingStateReconciler(
        operation_aware=True,
        query_phrase_aware=True,
        target_scoped_tombstones=True,
        relevant_tombstones_first=True,
        tombstone_cutover=True,
    )
    indexed = ProofCarryingStateReconciler(
        operation_aware=True,
        query_phrase_aware=True,
        target_scoped_tombstones=True,
        relevant_tombstones_first=True,
        tombstone_cutover=True,
    )

    build_started = perf_counter()
    reference_runs: list[dict[str, float]] = []
    indexed_runs: list[dict[str, float]] = []
    exact_runs: list[bool] = []
    try:
        with FrozenLexicalIndex(INDEX, definitions) as index:
            build_seconds = perf_counter() - build_started
            index_bytes = INDEX.stat().st_size
            for _ in range(REPEATS):
                reference_durations: list[float] = []
                expected = []
                for query in queries:
                    started = perf_counter()
                    expected.append(
                        reference._select_operation_memories(
                            query,
                            definitions,
                            token_budget=8192,
                            latency_budget_ms=1000.0,
                        )
                    )
                    reference_durations.append(perf_counter() - started)
                indexed_durations: list[float] = []
                actual = []
                for query in queries:
                    started = perf_counter()
                    actual.append(
                        index.select_operation_memories(
                            indexed,
                            query,
                            definitions,
                            token_budget=8192,
                            latency_budget_ms=1000.0,
                        )
                    )
                    indexed_durations.append(perf_counter() - started)
                reference_runs.append(
                    {
                        "total_seconds": sum(reference_durations),
                        "p95_seconds": _p95(reference_durations),
                    }
                )
                indexed_runs.append(
                    {
                        "total_seconds": sum(indexed_durations),
                        "p95_seconds": _p95(indexed_durations),
                    }
                )
                exact_runs.append(actual == expected)
    finally:
        INDEX.unlink(missing_ok=True)

    exact = all(exact_runs) and len(exact_runs) == REPEATS
    indexed_p95_max = max(run["p95_seconds"] for run in indexed_runs)
    speedups = [
        reference_run["p95_seconds"] / indexed_run["p95_seconds"]
        for reference_run, indexed_run in zip(reference_runs, indexed_runs)
        if indexed_run["p95_seconds"] > 0.0
    ]
    payload = attach_artifact_integrity(
        {
            "schema": "wavemind.scientific_frozen_lexical_index_probe.v1",
            "status": "pass" if exact and indexed_p95_max <= 1.0 else "fail",
            "evidence_class": "synthetic_performance_probe_not_admission",
            "held_out_benchmark_rows_used": False,
            "sources": [
                {
                    "path": path.relative_to(ROOT).as_posix(),
                    "bytes": path.stat().st_size,
                    "sha256": file_sha256(path),
                }
                for path in SOURCES
            ],
            "workload": {
                **workload,
                "sha256": sha256_bytes(canonical_json_bytes(workload)),
            },
            "index": {
                "kind": "sqlite-integer-postings-with-disk-normalized-content",
                "build_seconds": build_seconds,
                "bytes": index_bytes,
                "retains_document_content_in_python": False,
                "retains_per_document_token_sets_in_python": False,
            },
            "reference": {
                "runs": reference_runs,
            },
            "indexed": {
                "runs": indexed_runs,
                "maximum_p95_seconds": indexed_p95_max,
                "p95_target_seconds": 1.0,
            },
            "exact_selection_equality": exact,
            "exact_selection_equality_by_run": exact_runs,
            "repeat_count": REPEATS,
            "selection_count_per_run": len(queries),
            "minimum_speedup_at_p95": min(speedups),
            "claim_boundary": (
                "This probe proves exact selector equivalence and bounded synthetic "
                "latency only. It does not alter, rerun, or rescue failed v31 held-out "
                "admission evidence."
            ),
        }
    )
    OUTPUT.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(payload, indent=2, ensure_ascii=False))
    return 0 if payload["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
