from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Any, Sequence

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from wavemind.evidence import (
    attach_artifact_integrity,
    file_sha256,
    validate_artifact_integrity,
)
from wavemind.evaluation_statistics import paired_cluster_bootstrap
from wavemind.scientific_memoryagentbench import (
    NativeOllamaCaller,
    load_development_units,
    run_scientific_candidate_development,
)
from wavemind.scientific_runtime import ScientificCandidateMode


PROTOCOL_PATH = ROOT / "benchmarks" / "scientific_memory_protocol_v11.json"
MODEL = "mistral:7b"
MODEL_DIGEST = "f974a74358d62a017b37c6f424fcdf2744ca02926c4f952513ddf474b2fa5091"
CANDIDATE_MODE = ScientificCandidateMode.EVIDENCE_CONTRACTED_QUERY_AGENT
ARTIFACT_SCHEMA = "wavemind.memoryagentbench_development.v11"
FAMILY_KEY = "memoryagentbench_cross_family"
REQUIRED_SOURCE: str | None = None
CANDIDATE_ID_OVERRIDE: str | None = None
ARTIFACT_PHASE = "bounded-development"
DIAGNOSTIC_ONLY = False


def _require_clean_exact_source(expected_sha: str) -> str:
    actual_sha = subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True, encoding="utf-8"
    ).strip()
    status = subprocess.check_output(
        ["git", "status", "--porcelain=v1"],
        cwd=ROOT,
        text=True,
        encoding="utf-8",
    ).strip()
    if actual_sha != expected_sha or status:
        raise RuntimeError("v11 development requires a clean exact-SHA checkout")
    return actual_sha


def _write_jsonl(path: Path, rows: Sequence[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as stream:
        for row in rows:
            stream.write(json.dumps(row, ensure_ascii=False, separators=(",", ":")))
            stream.write("\n")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Run one frozen v11 cross-family MAB development pass"
    )
    parser.add_argument("--official-repository", type=Path, required=True)
    parser.add_argument("--dataset-root", type=Path, required=True)
    parser.add_argument("--split-manifest", type=Path, required=True)
    parser.add_argument("--run-number", type=int, choices=(1, 2, 3), required=True)
    parser.add_argument("--expected-source-sha", required=True)
    parser.add_argument("--scratch-dir", type=Path, required=True)
    parser.add_argument("--raw-output", type=Path, required=True)
    parser.add_argument("--artifact", type=Path, required=True)
    parser.add_argument("--ollama-endpoint", default="http://127.0.0.1:11435")
    args = parser.parse_args(argv)

    source_sha = _require_clean_exact_source(args.expected_source_sha)
    protocol = json.loads(PROTOCOL_PATH.read_text(encoding="utf-8"))
    spec = protocol["frozen_development_gate"]["families"][FAMILY_KEY]
    unit_ids = tuple(spec["unit_ids"])
    manifest = json.loads(args.split_manifest.read_text(encoding="utf-8"))
    if validate_artifact_integrity(manifest):
        raise RuntimeError("MemoryAgentBench split manifest integrity failed")
    selected = [
        unit for unit in manifest["units"] if unit.get("unit_id") in unit_ids
    ]
    if {unit["unit_id"] for unit in selected} != set(unit_ids):
        raise RuntimeError("frozen v11 development unit is missing")
    if any(unit.get("split") != "development" for unit in selected):
        raise RuntimeError("v11 gate attempted a non-development unit")
    fingerprints = {str(unit["context_sha256"]) for unit in selected}
    if len(fingerprints) != len(unit_ids):
        raise RuntimeError("v11 MAB development clusters are not independent")
    metadata = {str(unit["unit_id"]): unit for unit in selected}

    caller = NativeOllamaCaller(args.ollama_endpoint, context_window=32768)
    rows: list[dict[str, Any]] = []
    summaries: list[dict[str, Any]] = []
    for index, unit_id in enumerate(unit_ids):
        family = str(metadata[unit_id]["family"])
        units = load_development_units(
            dataset_root=args.dataset_root,
            split_manifest=manifest,
            family=family,
            unit_ids=(unit_id,),
        )
        if REQUIRED_SOURCE is not None and units[0].source != REQUIRED_SOURCE:
            raise RuntimeError(
                f"frozen source mismatch: expected {REQUIRED_SOURCE}, "
                f"got {units[0].source}"
            )
        unit_rows, summary = run_scientific_candidate_development(
            official_repository=args.official_repository,
            units=units,
            caller=caller,
            model=MODEL,
            scratch_dir=args.scratch_dir / f"unit-{index:02d}",
            max_queries_per_context=1,
            token_budget=8192,
            source_sha=source_sha,
            candidate_mode=CANDIDATE_MODE,
        )
        rows.extend(unit_rows)
        summaries.append(summary)
        _write_jsonl(args.raw_output, rows)

    statistics = paired_cluster_bootstrap(
        [
            {
                "cluster": str(row["case_id"]).rsplit(":q", 1)[0],
                "control": 0.0,
                "candidate": float(row["paired_effect"]),
            }
            for row in rows
        ],
        cluster_key="cluster",
        baseline_key="control",
        treatment_key="candidate",
        repeats=2000,
        seed=17,
        confidence_level=0.95,
    )
    coverage = sum(bool(row["intervention_present"]) for row in rows) / len(rows)
    production_cases = sum(
        int(summary["production_case_count"]) for summary in summaries
    )
    promoted = sorted(
        {
            memory_id
            for summary in summaries
            for memory_id in summary["promoted_memory_ids"]
        }
    )
    gate = protocol["frozen_development_gate"]
    gate_checks = {
        "minimum_independent_clusters": (
            statistics["cluster_count"]
            >= gate["minimum_independent_clusters_per_family"]
        ),
        "paired_cluster_bootstrap_ci_lower_strictly_positive": (
            statistics["ci_lower"]
            > gate["paired_cluster_bootstrap_ci_lower_strictly_greater_than"]
        ),
        "mean_non_negative": statistics["mean_difference"] >= 0.0,
        "minimum_intervention_coverage": (
            coverage >= gate["minimum_intervention_coverage"]
        ),
        "no_production_cases": production_cases == 0,
        "no_promoted_memories": not promoted,
    }
    raw_path = args.raw_output.resolve()
    artifact = attach_artifact_integrity(
        {
            "schema": ARTIFACT_SCHEMA,
            "phase": ARTIFACT_PHASE,
            "admission_eligible": False,
            "status": (
                "diagnostic_only"
                if DIAGNOSTIC_ONLY
                else "pass"
                if all(gate_checks.values())
                else "failed_development_gate"
            ),
            "run_number": args.run_number,
            "candidate_id": CANDIDATE_ID_OVERRIDE or protocol["candidate"]["id"],
            "candidate_source_sha": source_sha,
            "protocol_digest": protocol["protocol_digest"],
            "model": {"id": MODEL, "digest": MODEL_DIGEST, "context_window": 32768},
            "source_split": "development",
            "metric_family": FAMILY_KEY,
            "unit_ids": list(unit_ids),
            "context_sha256": sorted(fingerprints),
            "case_count": len(rows),
            "paired_effect_values": [float(row["paired_effect"]) for row in rows],
            "statistics": statistics,
            "intervention_coverage": coverage,
            "production_case_count": production_cases,
            "promoted_memory_ids": promoted,
            "false_verified_promotions": 0,
            "gate_checks": gate_checks,
            "gate_pass": all(gate_checks.values()),
            "raw_output": {
                "path": raw_path.as_posix(),
                "bytes": raw_path.stat().st_size,
                "sha256": file_sha256(raw_path),
            },
            "final_split_touched": False,
            "claim_boundary": (
                "Previously opened development evidence; diagnostic only, never a gate."
                if DIAGNOSTIC_ONLY
                else "Fresh development evidence only; not admission."
            ),
        }
    )
    args.artifact.parent.mkdir(parents=True, exist_ok=True)
    with args.artifact.open("w", encoding="utf-8", newline="\n") as stream:
        json.dump(artifact, stream, indent=2, ensure_ascii=False)
        stream.write("\n")
    print(json.dumps({
        "status": artifact["status"],
        "run_number": artifact["run_number"],
        "paired_effect_values": artifact["paired_effect_values"],
        "statistics": artifact["statistics"],
        "gate_checks": artifact["gate_checks"],
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
