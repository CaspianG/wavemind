from __future__ import annotations

import argparse
import copy
import json
import subprocess
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any, Sequence


CANDIDATE_SOURCE_SHA = "47b68e366aab9ce07b659c61a51c81d634b3fff2"
PROTOCOL_DIGEST = "d522705fdc9d49ed97874b6ce09c6372d7189673945b894856805be625d21b50"
MODEL = "mistral:7b"
MODEL_DIGEST = "f974a74358d62a017b37c6f424fcdf2744ca02926c4f952513ddf474b2fa5091"
FINAL_UNIT_IDS = (
    "Accurate_Retrieval:0007:aea0f2d603e1c8a3",
    "Accurate_Retrieval:0009:153a2cce98f93cb3",
    "Conflict_Resolution:0001:2a44d6ad3264a775",
    "Long_Range_Understanding:0002:4fb345e28ef3ce1a",
    "Test_Time_Learning:0002:36d1c3fde8d8fb21",
)


def _exact_clean(path: Path) -> None:
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
        raise RuntimeError("final evaluation requires the clean frozen v10 checkout")


def _write_jsonl(path: Path, rows: Sequence[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as stream:
        for row in rows:
            stream.write(json.dumps(row, ensure_ascii=False, separators=(",", ":")))
            stream.write("\n")


def run(args: argparse.Namespace) -> dict[str, Any]:
    candidate_root = args.candidate_repository.resolve()
    _exact_clean(candidate_root)
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
        unit for unit in manifest["units"] if unit.get("unit_id") in FINAL_UNIT_IDS
    ]
    if {unit["unit_id"] for unit in selected} != set(FINAL_UNIT_IDS):
        raise RuntimeError("frozen final unit is missing")
    if any(unit.get("split") != "final" for unit in selected):
        raise RuntimeError("frozen MAB unit is no longer final")
    fingerprints = {str(unit["context_sha256"]) for unit in selected}
    if len(fingerprints) != len(FINAL_UNIT_IDS):
        raise RuntimeError("MAB final clusters are not independent")

    derived = copy.deepcopy(manifest)
    derived.pop("integrity", None)
    for unit in derived["units"]:
        if unit.get("unit_id") in FINAL_UNIT_IDS:
            unit["split"] = "development"
    derived = attach_artifact_integrity(derived)
    grouped: defaultdict[str, list[str]] = defaultdict(list)
    for unit in selected:
        grouped[str(unit["family"])].append(str(unit["unit_id"]))
    caller = NativeOllamaCaller(args.ollama_endpoint, context_window=32768)
    all_rows: list[dict[str, Any]] = []
    summaries: list[dict[str, Any]] = []
    for family in sorted(grouped):
        units = load_development_units(
            dataset_root=args.dataset_root,
            split_manifest=derived,
            family=family,
            unit_ids=tuple(sorted(grouped[family])),
        )
        rows, summary = run_scientific_candidate_development(
            official_repository=args.official_repository,
            units=units,
            caller=caller,
            model=MODEL,
            scratch_dir=args.scratch_dir / family,
            max_queries_per_context=1,
            token_budget=8192,
            source_sha=CANDIDATE_SOURCE_SHA,
            candidate_mode=ScientificCandidateMode.OPERATION_TRACE_STRICT_OUTPUT_AGENT,
        )
        all_rows.extend(rows)
        summaries.append(summary)
        _write_jsonl(args.raw_output, all_rows)
    effects = [float(row["paired_effect"]) for row in all_rows]
    interval = paired_cluster_bootstrap(
        [
            {
                "cluster": str(row["case_id"]).rsplit(":q", 1)[0],
                "control": 0.0,
                "candidate": float(row["paired_effect"]),
            }
            for row in all_rows
        ],
        cluster_key="cluster",
        baseline_key="control",
        treatment_key="candidate",
        repeats=2000,
        seed=17,
        confidence_level=0.95,
    )
    promoted = sorted(
        {
            memory_id
            for summary in summaries
            for memory_id in summary["promoted_memory_ids"]
        }
    )
    production_cases = sum(
        int(summary["production_case_count"]) for summary in summaries
    )
    coverage = sum(bool(row["intervention_present"]) for row in all_rows) / len(
        all_rows
    )
    gate_checks = {
        "five_independent_clusters": interval["cluster_count"] == 5,
        "paired_cluster_bootstrap_ci_lower_strictly_positive": (
            interval["ci_lower"] > 0.0
        ),
        "mean_non_negative": interval["mean_difference"] >= 0.0,
        "minimum_intervention_coverage": coverage >= 0.8,
        "no_production_cases": production_cases == 0,
        "no_promoted_memories": not promoted,
    }
    artifact = attach_artifact_integrity(
        {
            "schema": "wavemind.memoryagentbench_final.v10",
            "phase": "final",
            "status": "pass" if all(gate_checks.values()) else "failed_final",
            "candidate_id": "operation-trace-strict-output-agent-v10",
            "candidate_source_sha": CANDIDATE_SOURCE_SHA,
            "protocol_digest": PROTOCOL_DIGEST,
            "model": {"id": MODEL, "digest": MODEL_DIGEST, "context_window": 32768},
            "official_repository_sha": "fe1735de8cf8b9908e1e3d3b5612afc815698062",
            "dataset_revision": "7ea066982b140a19337e17e60d45d4076e042faf",
            "source_split": "final",
            "unit_ids": list(FINAL_UNIT_IDS),
            "context_sha256": sorted(fingerprints),
            "case_count": len(all_rows),
            "paired_effect_values": effects,
            "paired_cluster_bootstrap": interval,
            "intervention_coverage": coverage,
            "production_case_count": production_cases,
            "promoted_memory_ids": promoted,
            "false_verified_promotions": 0,
            "gate_checks": gate_checks,
            "raw_output": {
                "path": str(args.raw_output.resolve()),
                "bytes": args.raw_output.stat().st_size,
                "sha256": file_sha256(args.raw_output),
            },
            "final_split_touched": True,
            "claim_boundary": "MAB final arm only; full v10 admission remains incomplete.",
        }
    )
    args.artifact.parent.mkdir(parents=True, exist_ok=True)
    with args.artifact.open("w", encoding="utf-8", newline="\n") as stream:
        json.dump(artifact, stream, indent=2, ensure_ascii=False)
        stream.write("\n")
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
    parser.add_argument("--ollama-endpoint", default="http://127.0.0.1:11435")
    return parser.parse_args(argv)


def main() -> int:
    artifact = run(parse_args())
    print(json.dumps({
        "status": artifact["status"],
        "paired_cluster_bootstrap": artifact["paired_cluster_bootstrap"],
        "gate_checks": artifact["gate_checks"],
    }, indent=2))
    return 0 if artifact["status"] == "pass" else 2


if __name__ == "__main__":
    raise SystemExit(main())
