from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Any, Sequence


CANDIDATE_SOURCE_SHA = "7fb57b96b0d213c24fb9d3262df2ca575c82944d"
PROTOCOL_DIGEST = "19c5cd37874863b9a0b4db4003f699e5c5d0979fbdf8e32b44c9c17b7d1d4144"
MODEL = "mistral:7b"
MODEL_DIGEST = "f974a74358d62a017b37c6f424fcdf2744ca02926c4f952513ddf474b2fa5091"
GATE_UNIT_IDS = (
    "Accurate_Retrieval:0014:21075069be9ce036",
    "Accurate_Retrieval:0015:13f7b62d03ae1368",
    "Accurate_Retrieval:0016:3ef36797263fea91",
    "Accurate_Retrieval:0018:49264170c654189c",
    "Accurate_Retrieval:0020:df9c9f3f789da3e2",
)


def _require_exact_clean(path: Path) -> None:
    sha = subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=path, text=True, encoding="utf-8"
    ).strip()
    status = subprocess.check_output(
        ["git", "status", "--porcelain=v1"],
        cwd=path,
        text=True,
        encoding="utf-8",
    ).strip()
    if sha != CANDIDATE_SOURCE_SHA or status:
        raise RuntimeError("v8 development requires its clean exact candidate checkout")


def _write_jsonl(path: Path, rows: Sequence[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "".join(
            json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n"
            for row in rows
        ),
        encoding="utf-8",
    )


def run(args: argparse.Namespace) -> dict[str, Any]:
    candidate_root = args.candidate_repository.resolve()
    _require_exact_clean(candidate_root)
    sys.path.insert(0, str(candidate_root))
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

    manifest = json.loads(args.split_manifest.read_text(encoding="utf-8"))
    if validate_artifact_integrity(manifest):
        raise RuntimeError("MemoryAgentBench split manifest integrity failed")
    selected = [
        unit for unit in manifest["units"] if unit.get("unit_id") in GATE_UNIT_IDS
    ]
    if {unit["unit_id"] for unit in selected} != set(GATE_UNIT_IDS):
        raise RuntimeError("frozen v8 development unit is missing")
    if any(unit.get("split") != "development" for unit in selected):
        raise RuntimeError("v8 gate attempted to open a non-development unit")
    if any(unit.get("family") != "Accurate_Retrieval" for unit in selected):
        raise RuntimeError("v8 gate attempted an unregistered metric family")
    fingerprints = {str(unit["context_sha256"]) for unit in selected}
    if len(fingerprints) != len(GATE_UNIT_IDS):
        raise RuntimeError("v8 MAB gate clusters are not independent")

    units = load_development_units(
        dataset_root=args.dataset_root,
        split_manifest=manifest,
        family="Accurate_Retrieval",
        unit_ids=GATE_UNIT_IDS,
    )
    rows, summary = run_scientific_candidate_development(
        official_repository=args.official_repository,
        units=units,
        caller=NativeOllamaCaller(args.ollama_endpoint, context_window=32768),
        model=MODEL,
        scratch_dir=args.scratch_dir,
        max_queries_per_context=1,
        token_budget=8192,
        source_sha=CANDIDATE_SOURCE_SHA,
        candidate_mode=(
            ScientificCandidateMode.PHRASE_ALIGNED_QUERY_SLICED_RECONCILER
        ),
    )
    _write_jsonl(args.raw_output, rows)
    effects = [float(row["paired_effect"]) for row in rows]
    interval = paired_cluster_bootstrap(
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
    promoted = sorted(summary["promoted_memory_ids"])
    production_cases = int(summary["production_case_count"])
    passed = (
        len(rows) == len(GATE_UNIT_IDS)
        and interval["ci_lower"] > 0.0
        and coverage >= 0.8
        and interval["mean_difference"] >= 0.0
        and production_cases == 0
        and not promoted
    )
    artifact = attach_artifact_integrity(
        {
            "schema": "wavemind.memoryagentbench_development.v8",
            "phase": "bounded-development",
            "run_number": args.run_number,
            "status": "pass" if passed else "failed_development_gate",
            "candidate_id": "phrase-aligned-query-sliced-reconciler-v8",
            "candidate_source_sha": CANDIDATE_SOURCE_SHA,
            "protocol_digest": PROTOCOL_DIGEST,
            "model": {"id": MODEL, "digest": MODEL_DIGEST, "context_window": 32768},
            "source_split": "development",
            "metric_family": "Accurate_Retrieval",
            "primary_metric": "substring_exact_match",
            "unit_ids": list(GATE_UNIT_IDS),
            "context_sha256": sorted(fingerprints),
            "case_count": len(rows),
            "cluster_count": interval["cluster_count"],
            "paired_effect": {
                "values": effects,
                "positive_count": sum(value > 0.0 for value in effects),
                "zero_count": sum(value == 0.0 for value in effects),
                "negative_count": sum(value < 0.0 for value in effects),
            },
            "paired_cluster_bootstrap": interval,
            "intervention_coverage": coverage,
            "production_case_count": production_cases,
            "promoted_memory_ids": promoted,
            "false_verified_promotions": 0,
            "raw_output": {
                "path": str(args.raw_output.resolve()),
                "bytes": args.raw_output.stat().st_size,
                "sha256": file_sha256(args.raw_output),
            },
            "final_split_touched": False,
            "validation_split_touched": False,
            "claim_boundary": "Development evidence only; not validation or admission.",
        }
    )
    args.artifact.parent.mkdir(parents=True, exist_ok=True)
    args.artifact.write_text(
        json.dumps(artifact, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return artifact


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--candidate-repository", type=Path, required=True)
    parser.add_argument("--official-repository", type=Path, required=True)
    parser.add_argument("--dataset-root", type=Path, required=True)
    parser.add_argument("--split-manifest", type=Path, required=True)
    parser.add_argument("--scratch-dir", type=Path, required=True)
    parser.add_argument("--raw-output", type=Path, required=True)
    parser.add_argument("--artifact", type=Path, required=True)
    parser.add_argument("--run-number", type=int, choices=(1, 2, 3), required=True)
    parser.add_argument("--ollama-endpoint", default="http://127.0.0.1:11435")
    return parser.parse_args(argv)


def main() -> int:
    artifact = run(parse_args())
    print(
        json.dumps(
            {
                "status": artifact["status"],
                "run_number": artifact["run_number"],
                "case_count": artifact["case_count"],
                "paired_cluster_bootstrap": artifact["paired_cluster_bootstrap"],
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
