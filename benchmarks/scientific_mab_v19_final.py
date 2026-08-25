from __future__ import annotations

import argparse
import copy
import json
import subprocess
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any, Sequence


CANDIDATE_ID = "targeted-dual-coverage-agent-v19"
CANDIDATE_SOURCE_SHA = "c509511f09dbcd3b4206ec1b74a7abc9510d9e73"
PROTOCOL_DIGEST = "443d8a461b10969756579eb6af3e05d7b909d30369fb286b2a582aa8efaef684"
MODEL = "mistral:7b"
MODEL_DIGEST = "f974a74358d62a017b37c6f424fcdf2744ca02926c4f952513ddf474b2fa5091"
OFFICIAL_REPOSITORY_SHA = "fe1735de8cf8b9908e1e3d3b5612afc815698062"
DATASET_REVISION = "7ea066982b140a19337e17e60d45d4076e042faf"
FINAL_UNIT_IDS = (
    "Accurate_Retrieval:0010:ec65b7cb50d7280b",
    "Accurate_Retrieval:0017:61ec3a9b2a2e3e8d",
    "Accurate_Retrieval:0019:c2e1809c93430d92",
    "Conflict_Resolution:0003:9c8ce1ed911d25a3",
    "Long_Range_Understanding:0010:5f579da48d431ff2",
    "Long_Range_Understanding:0011:b721d0a06ba3ad39",
    "Long_Range_Understanding:0017:e0c3f4d1eab833c9",
    "Long_Range_Understanding:0028:1f0d367470ebb847",
    "Long_Range_Understanding:0034:3e3a1a2dbd3bc870",
    "Long_Range_Understanding:0052:cb1104516284ee52",
)


def _git_sha(path: Path) -> str:
    return subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=path, text=True, encoding="utf-8"
    ).strip()


def _exact_clean(path: Path) -> None:
    status = subprocess.check_output(
        ["git", "status", "--porcelain=v1"],
        cwd=path,
        text=True,
        encoding="utf-8",
    ).strip()
    if _git_sha(path) != CANDIDATE_SOURCE_SHA or status:
        raise RuntimeError("final evaluation requires the clean frozen v19 checkout")


def _write_jsonl(path: Path, rows: Sequence[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as stream:
        for row in rows:
            stream.write(json.dumps(row, ensure_ascii=False, separators=(",", ":")))
            stream.write("\n")


def run(args: argparse.Namespace) -> dict[str, Any]:
    candidate_root = args.candidate_repository.resolve()
    official_root = args.official_repository.resolve()
    dataset_root = args.dataset_root.resolve()
    _exact_clean(candidate_root)
    if _git_sha(official_root) != OFFICIAL_REPOSITORY_SHA:
        raise RuntimeError("official MemoryAgentBench code SHA changed")

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
        raise RuntimeError("frozen v19 final unit is missing")
    if any(unit.get("split") != "final" for unit in selected):
        raise RuntimeError("frozen v19 MAB unit is no longer final")
    fingerprints = {str(unit["context_sha256"]) for unit in selected}
    if len(fingerprints) != len(FINAL_UNIT_IDS):
        raise RuntimeError("v19 MAB final clusters are not independent")

    # The official loader only exposes development rows. This derived in-memory
    # manifest changes the loader label after the untouched final rows and their
    # fingerprints have already been verified; the retained artifact records that
    # the source split was final.
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
            dataset_root=dataset_root,
            split_manifest=derived,
            family=family,
            unit_ids=tuple(sorted(grouped[family])),
        )
        rows, summary = run_scientific_candidate_development(
            official_repository=official_root,
            units=units,
            caller=caller,
            model=MODEL,
            scratch_dir=args.scratch_dir / family,
            max_queries_per_context=1,
            token_budget=8192,
            source_sha=CANDIDATE_SOURCE_SHA,
            candidate_mode=ScientificCandidateMode.TASK_AWARE_SEQUENCE_COVERAGE_AGENT,
        )
        all_rows.extend(rows)
        summaries.append(summary)
        _write_jsonl(args.raw_output, all_rows)

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
        "ten_independent_clusters": interval["cluster_count"] == 10,
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
            "schema": "wavemind.memoryagentbench_final.v19",
            "phase": "final",
            "status": "pass" if all(gate_checks.values()) else "failed_final",
            "candidate_id": CANDIDATE_ID,
            "candidate_source_sha": CANDIDATE_SOURCE_SHA,
            "protocol_digest": PROTOCOL_DIGEST,
            "model": {"id": MODEL, "digest": MODEL_DIGEST, "context_window": 32768},
            "official_repository_sha": OFFICIAL_REPOSITORY_SHA,
            "dataset_revision": DATASET_REVISION,
            "source_split": "final",
            "unit_ids": list(FINAL_UNIT_IDS),
            "context_sha256": sorted(fingerprints),
            "case_count": len(all_rows),
            "paired_effect_values": [float(row["paired_effect"]) for row in all_rows],
            "paired_cluster_bootstrap": interval,
            "intervention_coverage": coverage,
            "production_case_count": production_cases,
            "promoted_memory_ids": promoted,
            "false_verified_promotions": 0,
            "gate_checks": gate_checks,
            "gate_pass": all(gate_checks.values()),
            "raw_output": {
                "path": str(args.raw_output.resolve()),
                "bytes": args.raw_output.stat().st_size,
                "sha256": file_sha256(args.raw_output),
            },
            "final_split_touched": True,
            "claim_boundary": (
                "MAB final arm only; full v19 admission remains incomplete until "
                "every later frozen arm passes."
            ),
        }
    )
    args.artifact.parent.mkdir(parents=True, exist_ok=True)
    with args.artifact.open("w", encoding="utf-8", newline="\n") as stream:
        json.dump(artifact, stream, indent=2, ensure_ascii=False)
        stream.write("\n")
    return artifact


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run frozen v19 MAB final arm")
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
    print(
        json.dumps(
            {
                "status": artifact["status"],
                "paired_cluster_bootstrap": artifact[
                    "paired_cluster_bootstrap"
                ],
                "gate_checks": artifact["gate_checks"],
            },
            indent=2,
        )
    )
    return 0 if artifact["status"] == "pass" else 2


if __name__ == "__main__":
    raise SystemExit(main())
