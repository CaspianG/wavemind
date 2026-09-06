from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from statistics import quantiles
from time import perf_counter
from typing import Any, Mapping, Sequence


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from benchmarks.scientific_frozen_lexical_index import FrozenLexicalIndex  # noqa: E402
from wavemind.evidence import (  # noqa: E402
    attach_artifact_integrity,
    canonical_json_bytes,
    file_sha256,
    sha256_bytes,
    validate_artifact_integrity,
)
from wavemind.scientific_memory import MemoryDefinition, MemoryKind  # noqa: E402
from wavemind.scientific_reconciliation import (  # noqa: E402
    ProofCarryingStateReconciler,
    ReconciliationSelection,
)


PROTOCOL = ROOT / "benchmarks" / "scientific_performance_protocol_v32.json"
RUNNER = ROOT / "benchmarks" / "scientific_performance_v32.py"
OUTPUTS = {
    "development": ROOT
    / "benchmarks"
    / "scientific_performance_v32_development_results.json",
    "validation": ROOT
    / "benchmarks"
    / "scientific_performance_v32_validation_results.json",
}
CANDIDATE_PATHS = (
    "benchmarks/scientific_frozen_lexical_index.py",
    "benchmarks/scientific_longmemeval_v2_backend_indexed_prototype.py",
)


def _load_protocol() -> dict[str, Any]:
    payload = json.loads(PROTOCOL.read_text(encoding="utf-8"))
    content = dict(payload)
    expected = str(content.pop("protocol_digest"))
    actual = sha256_bytes(canonical_json_bytes(content))
    if actual != expected:
        raise RuntimeError("v32 protocol digest mismatch")
    return payload


def _git_blob(source_sha: str, path: str) -> bytes:
    return subprocess.check_output(
        ["git", "show", f"{source_sha}:{path}"],
        cwd=ROOT,
    )


def _verify_candidate_source(protocol: Mapping[str, Any]) -> list[dict[str, Any]]:
    source_sha = str(protocol["candidate"]["source_sha"])
    records = []
    for relative in CANDIDATE_PATHS:
        path = ROOT / relative
        current = path.read_bytes()
        frozen = _git_blob(source_sha, relative)
        if current != frozen:
            raise RuntimeError(f"v32 candidate source changed: {relative}")
        records.append(
            {
                "path": relative,
                "bytes": len(current),
                "sha256": sha256_bytes(current),
                "source_sha": source_sha,
            }
        )
    return records


def _validate_stage_order(stage: str) -> None:
    if stage != "validation":
        return
    development_path = OUTPUTS["development"]
    if not development_path.is_file():
        raise RuntimeError("v32 validation requires completed development evidence")
    development = json.loads(development_path.read_text(encoding="utf-8"))
    errors = validate_artifact_integrity(development)
    if errors:
        raise RuntimeError(f"invalid v32 development integrity: {errors}")
    if development.get("status") != "passed_development_v32":
        raise RuntimeError("v32 development did not pass; validation remains unopened")


def _definitions(config: Mapping[str, Any]) -> dict[str, MemoryDefinition]:
    count = int(config["definition_count"])
    cluster_modulus = int(config["cluster_modulus"])
    route_modulus = int(config["route_modulus"])
    state_modulus = int(config["state_modulus"])
    account_modulus = int(config["account_modulus"])
    filler_count = int(config["filler_token_count"])
    tombstone_period = int(config["tombstone_period"])
    definitions: dict[str, MemoryDefinition] = {}
    for index in range(count):
        content = " ".join(
            (
                f"document {index}",
                f"cluster {index % cluster_modulus}",
                f"route {index % route_modulus}",
                f"state {index % state_modulus}",
                f"account {index % account_modulus}",
                "workflow checkout delivery support update",
                " ".join(f"filler-{offset}" for offset in range(filler_count)),
            )
        )
        provenance = [f"source-order:{index}", "memory-operation:1"]
        if index % tombstone_period == 0:
            provenance.append("memory-tombstone:1")
        memory_id = f"memory-{index:06d}"
        definitions[memory_id] = MemoryDefinition(
            memory_id=memory_id,
            kind=MemoryKind.FACT,
            content=content,
            provenance=tuple(provenance),
            estimated_tokens=32 + (index % 9),
            estimated_latency_ms=0.1,
            safety_risk=0.0,
        )
    return definitions


def _queries(config: Mapping[str, Any]) -> tuple[str, ...]:
    start = int(config["query_start"])
    count = int(config["query_count"])
    cluster_modulus = int(config["cluster_modulus"])
    route_modulus = int(config["route_modulus"])
    state_modulus = int(config["state_modulus"])
    account_modulus = int(config["account_modulus"])
    return tuple(
        f"Find account {index % account_modulus} cluster {index % cluster_modulus} "
        f"route {index % route_modulus} state {index % state_modulus} "
        "checkout update"
        for index in range(start, start + count)
    )


def _p95(values: Sequence[float]) -> float:
    if not values:
        raise RuntimeError("cannot compute p95 over empty v32 durations")
    if len(values) == 1:
        return float(values[0])
    return float(quantiles(values, n=100, method="inclusive")[94])


def _selection_digest(selection: ReconciliationSelection) -> str:
    return sha256_bytes(
        canonical_json_bytes(
            {
                "memory_ids": list(selection.memory_ids),
                "relevance": dict(selection.relevance),
                "reason": selection.reason,
            }
        )
    )


def _selector() -> ProofCarryingStateReconciler:
    return ProofCarryingStateReconciler(
        operation_aware=True,
        query_phrase_aware=True,
        target_scoped_tombstones=True,
        relevant_tombstones_first=True,
        tombstone_cutover=True,
    )


def _run_stage(stage: str, protocol: Mapping[str, Any]) -> dict[str, Any]:
    config = protocol["workloads"][stage]
    execution = protocol["frozen_execution"]
    gates = protocol["frozen_gates"]
    definitions = _definitions(config)
    queries = _queries(config)
    workload_contract = {
        "stage": stage,
        **dict(config),
        "queries": list(queries),
    }
    reference = _selector()
    indexed = _selector()
    index_path = ROOT / "benchmarks" / f".scientific-performance-v32-{stage}.sqlite3"
    build_started = perf_counter()
    raw_rows: list[dict[str, Any]] = []
    repeat_summaries: list[dict[str, Any]] = []
    try:
        with FrozenLexicalIndex(index_path, definitions) as index:
            build_seconds = perf_counter() - build_started
            index_bytes = index_path.stat().st_size
            retains_document_content = hasattr(index, "_normalized_contents_by_memory")
            retains_document_token_sets = hasattr(index, "_tokens_by_memory")
            for repeat in range(1, int(execution["repeats"]) + 1):
                reference_selections: list[ReconciliationSelection] = []
                reference_durations: list[float] = []
                for query in queries:
                    started = perf_counter()
                    reference_selections.append(
                        reference._select_operation_memories(
                            query,
                            definitions,
                            token_budget=int(execution["token_budget"]),
                            latency_budget_ms=float(execution["latency_budget_ms"]),
                        )
                    )
                    reference_durations.append(perf_counter() - started)
                indexed_selections: list[ReconciliationSelection] = []
                indexed_durations: list[float] = []
                for query in queries:
                    started = perf_counter()
                    indexed_selections.append(
                        index.select_operation_memories(
                            indexed,
                            query,
                            definitions,
                            token_budget=int(execution["token_budget"]),
                            latency_budget_ms=float(execution["latency_budget_ms"]),
                        )
                    )
                    indexed_durations.append(perf_counter() - started)
                equality = [
                    candidate == baseline
                    for baseline, candidate in zip(
                        reference_selections,
                        indexed_selections,
                    )
                ]
                for query_index, query in enumerate(queries):
                    raw_rows.append(
                        {
                            "repeat": repeat,
                            "query_index": query_index,
                            "query_sha256": sha256_bytes(query.encode("utf-8")),
                            "reference_seconds": reference_durations[query_index],
                            "indexed_seconds": indexed_durations[query_index],
                            "reference_selection_sha256": _selection_digest(
                                reference_selections[query_index]
                            ),
                            "indexed_selection_sha256": _selection_digest(
                                indexed_selections[query_index]
                            ),
                            "exact_equal": equality[query_index],
                        }
                    )
                reference_p95 = _p95(reference_durations)
                indexed_p95 = _p95(indexed_durations)
                repeat_summaries.append(
                    {
                        "repeat": repeat,
                        "reference_total_seconds": sum(reference_durations),
                        "reference_p95_seconds": reference_p95,
                        "indexed_total_seconds": sum(indexed_durations),
                        "indexed_p95_seconds": indexed_p95,
                        "p95_speedup": reference_p95 / indexed_p95,
                        "exact_selection_equality": all(equality),
                    }
                )
    finally:
        index_path.unlink(missing_ok=True)

    gate_checks = {
        "required_repeats": len(repeat_summaries) == int(gates["required_repeats"]),
        "exact_selection_equality_every_query_every_repeat": all(
            row["exact_equal"] for row in raw_rows
        ),
        "indexed_p95_seconds_maximum_every_repeat": all(
            row["indexed_p95_seconds"]
            <= float(gates["indexed_p95_seconds_maximum_every_repeat"])
            for row in repeat_summaries
        ),
        "p95_speedup_minimum_every_repeat": all(
            row["p95_speedup"] >= float(gates["p95_speedup_minimum_every_repeat"])
            for row in repeat_summaries
        ),
        "build_seconds_maximum": build_seconds
        <= float(gates["build_seconds_maximum"]),
        "index_bytes_per_definition_maximum": index_bytes / len(definitions)
        <= float(gates["index_bytes_per_definition_maximum"]),
        "retains_document_content_in_python": retains_document_content
        is bool(gates["retains_document_content_in_python"]),
        "retains_per_document_token_sets_in_python": retains_document_token_sets
        is bool(gates["retains_per_document_token_sets_in_python"]),
    }
    passed = all(gate_checks.values())
    return {
        "stage": stage,
        "status": f"passed_{stage}_v32" if passed else f"failed_{stage}_v32",
        "workload": {
            **workload_contract,
            "sha256": sha256_bytes(canonical_json_bytes(workload_contract)),
        },
        "build": {
            "seconds": build_seconds,
            "index_bytes": index_bytes,
            "index_bytes_per_definition": index_bytes / len(definitions),
            "retains_document_content_in_python": retains_document_content,
            "retains_per_document_token_sets_in_python": (
                retains_document_token_sets
            ),
        },
        "repeat_summaries": repeat_summaries,
        "raw_rows": raw_rows,
        "gate_checks": gate_checks,
        "gate_pass": passed,
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--stage", choices=tuple(OUTPUTS), required=True)
    args = parser.parse_args(argv)
    stage = str(args.stage)
    output = OUTPUTS[stage]
    if output.exists():
        raise RuntimeError(f"v32 stage outcome already exists: {output}")
    protocol = _load_protocol()
    _validate_stage_order(stage)
    source_records = _verify_candidate_source(protocol)
    stage_result = _run_stage(stage, protocol)
    payload = attach_artifact_integrity(
        {
            "schema": "wavemind.scientific_performance_outcome.v32",
            "candidate_id": protocol["candidate"]["id"],
            "candidate_source_sha": protocol["candidate"]["source_sha"],
            "protocol_digest": protocol["protocol_digest"],
            "protocol": {
                "path": PROTOCOL.relative_to(ROOT).as_posix(),
                "bytes": PROTOCOL.stat().st_size,
                "sha256": file_sha256(PROTOCOL),
            },
            "runner": {
                "path": RUNNER.relative_to(ROOT).as_posix(),
                "bytes": RUNNER.stat().st_size,
                "sha256": file_sha256(RUNNER),
            },
            "candidate_sources": source_records,
            "held_out_benchmark_rows_used": False,
            **stage_result,
            "claim_boundary": protocol["claim_boundary"],
        }
    )
    temporary = output.with_suffix(output.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    temporary.replace(output)
    print(json.dumps(payload, indent=2, ensure_ascii=False))
    return 0 if payload["gate_pass"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
