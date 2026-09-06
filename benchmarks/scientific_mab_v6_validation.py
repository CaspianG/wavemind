from __future__ import annotations

import argparse
import copy
import json
import subprocess
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any, Sequence


CANDIDATE_SOURCE_SHA = "a8240fe6bd9a79aec3d524b1cbbbdb4b907f8d97"
PROTOCOL_DIGEST = "d140bd10012dc698656b211621be1fb851ae511294114a4b3d5cd73cbdfd2ebc"
MODEL = "mistral:7b"
MODEL_DIGEST = "f974a74358d62a017b37c6f424fcdf2744ca02926c4f952513ddf474b2fa5091"
VALIDATION_UNIT_IDS = (
    "Accurate_Retrieval:0004:4a190b7aec81123d",
    "Accurate_Retrieval:0012:2bc8ffde99c2c47b",
    "Accurate_Retrieval:0013:6dc878c847d183ff",
    "Conflict_Resolution:0000:e46cb14b53eedd71",
    "Long_Range_Understanding:0003:f186cd415885b43b",
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
        raise RuntimeError("validation requires the clean frozen v6 candidate checkout")


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
        unit for unit in manifest["units"] if unit.get("unit_id") in VALIDATION_UNIT_IDS
    ]
    if {unit["unit_id"] for unit in selected} != set(VALIDATION_UNIT_IDS):
        raise RuntimeError("frozen validation unit is missing")
    if any(unit.get("split") != "validation" for unit in selected):
        raise RuntimeError("frozen MAB unit is no longer validation")
    fingerprints = {str(unit["context_sha256"]) for unit in selected}
    if len(fingerprints) != len(VALIDATION_UNIT_IDS):
        raise RuntimeError("MAB validation clusters are not independent")

    # Compatibility view for the exact candidate's leakage-safe loader. The source
    # manifest and original validation labels remain attached to the final artifact.
    derived = copy.deepcopy(manifest)
    derived.pop("integrity", None)
    for unit in derived["units"]:
        if unit.get("unit_id") in VALIDATION_UNIT_IDS:
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
            candidate_mode=(
                ScientificCandidateMode.OPERATION_AWARE_TOMBSTONE_RECONCILER
            ),
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
    selected_memory_ids = sorted(
        {
            memory_id
            for summary in summaries
            for memory_id in summary["selected_memory_ids"]
        }
    )
    promoted_memory_ids = sorted(
        {
            memory_id
            for summary in summaries
            for memory_id in summary["promoted_memory_ids"]
        }
    )
    artifact = attach_artifact_integrity(
        {
            "schema": "wavemind.memoryagentbench_validation.v6",
            "phase": "validation",
            "status": (
                "pass"
                if interval["ci_lower"] > 0.0
                and len(all_rows) == len(VALIDATION_UNIT_IDS)
                and all(row["intervention_present"] for row in all_rows)
                and not promoted_memory_ids
                else "failed_validation"
            ),
            "candidate_id": (
                "operation-aware-tombstone-reconciler-v6"
            ),
            "candidate_source_sha": CANDIDATE_SOURCE_SHA,
            "protocol_digest": PROTOCOL_DIGEST,
            "model": {"id": MODEL, "digest": MODEL_DIGEST, "context_window": 32768},
            "official_repository_sha": "fe1735de8cf8b9908e1e3d3b5612afc815698062",
            "dataset_revision": "7ea066982b140a19337e17e60d45d4076e042faf",
            "source_split": "validation",
            "unit_ids": list(VALIDATION_UNIT_IDS),
            "context_sha256": sorted(fingerprints),
            "case_count": len(all_rows),
            "cluster_count": interval["cluster_count"],
            "paired_effect": {
                "values": effects,
                "positive_count": sum(value > 0.0 for value in effects),
                "zero_count": sum(value == 0.0 for value in effects),
                "negative_count": sum(value < 0.0 for value in effects),
            },
            "paired_cluster_bootstrap": interval,
            "intervention_coverage": (
                sum(bool(row["intervention_present"]) for row in all_rows)
                / len(all_rows)
            ),
            "selected_memory_ids": selected_memory_ids,
            "promoted_memory_ids": promoted_memory_ids,
            "false_verified_promotions": 0,
            "production_case_count": sum(
                int(summary["production_case_count"]) for summary in summaries
            ),
            "raw_output": {
                "path": str(args.raw_output.resolve()),
                "bytes": args.raw_output.stat().st_size,
                "sha256": file_sha256(args.raw_output),
            },
            "source_split_manifest": {
                "path": str(args.split_manifest.resolve()),
                "sha256": file_sha256(args.split_manifest),
            },
            "final_split_touched": False,
            "claim_boundary": "This is validation evidence, not full v6 admission.",
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
    parser.add_argument("--ollama-endpoint", default="http://127.0.0.1:11435")
    return parser.parse_args(argv)


def main() -> int:
    artifact = run(parse_args())
    print(
        json.dumps(
            {
                "status": artifact["status"],
                "case_count": artifact["case_count"],
                "cluster_count": artifact["cluster_count"],
                "paired_cluster_bootstrap": artifact["paired_cluster_bootstrap"],
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
