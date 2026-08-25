from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any, Sequence


CANDIDATE_SOURCE_SHA = "a8240fe6bd9a79aec3d524b1cbbbdb4b907f8d97"
MEMOPS_SOURCE_SHA = "312af65e2c7b6d1b70f062ffa8b4cde32aaf6f35"
PROTOCOL_DIGEST = "d140bd10012dc698656b211621be1fb851ae511294114a4b3d5cd73cbdfd2ebc"
MODEL_DIGEST = "f974a74358d62a017b37c6f424fcdf2744ca02926c4f952513ddf474b2fa5091"
VALIDATION_SUBJECTS = ("A01", "A02", "A29", "A32", "A33")
V6_MODE = "operation-aware-tombstone-reconciler-v6"
V5_MODE = "atomic-batch-hierarchical-proof-state-reconciler-v5"


def _git_sha(path: Path) -> str:
    return subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=path, text=True, encoding="utf-8"
    ).strip()


def _require_exact_clean(path: Path, sha: str, label: str) -> None:
    status = subprocess.check_output(
        ["git", "status", "--porcelain=v1"],
        cwd=path,
        text=True,
        encoding="utf-8",
    ).strip()
    if _git_sha(path) != sha or status:
        raise RuntimeError(f"{label} must be clean at {sha}")


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def _link_inputs(source: Path, destination: Path) -> tuple[str, ...]:
    destination.mkdir(parents=True, exist_ok=True)
    selected = sorted(
        path
        for subject in VALIDATION_SUBJECTS
        for path in source.glob(f"{subject}_*.json")
    )
    names = tuple(path.name for path in selected)
    for path in selected:
        target = destination / path.name
        if target.exists():
            if os.path.samefile(path, target):
                continue
            raise RuntimeError(f"validation input collision: {target}")
        os.link(path, target)
    return names


def _run_arm(
    *,
    args: argparse.Namespace,
    mode: str,
    adjacent_dir: Path,
    longitudinal_dir: Path,
) -> tuple[Path, Path]:
    arm_dir = args.output_root / mode
    raw_path = arm_dir / "raw_pairs.jsonl"
    artifact = arm_dir / "artifact.json"
    if raw_path.is_file() and artifact.is_file():
        return raw_path, artifact
    arm_dir.mkdir(parents=True, exist_ok=True)
    command = [
        sys.executable,
        str(args.candidate_repository / "benchmarks" / "scientific_memops_candidate_dev.py"),
        "--upstream-root",
        str(args.memops_repository),
        "--upstream-sha",
        MEMOPS_SOURCE_SHA,
        "--adjacent-input-dir",
        str(adjacent_dir),
        "--longitudinal-input-dir",
        str(longitudinal_dir),
        "--output-dir",
        str(arm_dir),
        "--artifact",
        str(artifact),
        "--protocol-digest",
        PROTOCOL_DIGEST,
        "--model-digest",
        MODEL_DIGEST,
        "--ollama-endpoint",
        args.ollama_endpoint,
        "--context-window",
        "32768",
        "--max-cases",
        "0",
        "--max-subjects",
        "0",
        "--max-cases-per-subject",
        "1",
        "--candidate-mode",
        mode,
        "--token-budget",
        "8192",
        "--top-k-context",
        "10",
    ]
    with (arm_dir / "runner.log").open("a", encoding="utf-8") as log:
        subprocess.run(
            command,
            cwd=args.candidate_repository,
            stdout=log,
            stderr=subprocess.STDOUT,
            text=True,
            check=True,
        )
    return raw_path, artifact


def run(args: argparse.Namespace) -> dict[str, Any]:
    args.candidate_repository = args.candidate_repository.resolve()
    args.memops_repository = args.memops_repository.resolve()
    args.output_root = args.output_root.resolve()
    _require_exact_clean(
        args.candidate_repository, CANDIDATE_SOURCE_SHA, "v6 candidate"
    )
    _require_exact_clean(args.memops_repository, MEMOPS_SOURCE_SHA, "MemOps upstream")
    sys.path.insert(0, str(args.candidate_repository))
    from wavemind.evidence import (
        attach_artifact_integrity,
        file_sha256,
        validate_artifact_integrity,
    )
    from wavemind.evaluation_statistics import paired_cluster_bootstrap

    split_manifest = json.loads(args.split_manifest.read_text(encoding="utf-8"))
    if validate_artifact_integrity(split_manifest):
        raise RuntimeError("evaluation split manifest integrity failed")
    selected_units = [
        unit
        for unit in split_manifest["units"]
        if unit.get("dataset") == "memops"
        and str(unit.get("subject_id")) in VALIDATION_SUBJECTS
    ]
    if {str(unit.get("subject_id")) for unit in selected_units} != set(
        VALIDATION_SUBJECTS
    ):
        raise RuntimeError("frozen MemOps validation subject is missing")
    if any(unit.get("split") != "validation" for unit in selected_units):
        raise RuntimeError("frozen MemOps subject is no longer validation")

    args.output_root.mkdir(parents=True, exist_ok=True)
    marker = args.output_root / "validation_marker.json"
    if not marker.exists():
        marker.write_text(
            json.dumps(
                {
                    "schema": "wavemind.memops_validation_marker.v6",
                    "candidate_source_sha": CANDIDATE_SOURCE_SHA,
                    "subjects": list(VALIDATION_SUBJECTS),
                    "arms": [V6_MODE, V5_MODE, "no-memory"],
                },
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
    source_root = args.memops_repository / "generated_result"
    adjacent_dir = args.output_root / "inputs" / "adjacent"
    longitudinal_dir = args.output_root / "inputs" / "longitudinal"
    adjacent_names = _link_inputs(
        source_root / "2-evidence_conversation", adjacent_dir
    )
    longitudinal_names = _link_inputs(
        source_root / "4-inject_evidence_with_distractors", longitudinal_dir
    )
    if adjacent_names != longitudinal_names or len(adjacent_names) != 23:
        raise RuntimeError("frozen MemOps operation-file matrix changed")

    v6_raw, v6_artifact_path = _run_arm(
        args=args,
        mode=V6_MODE,
        adjacent_dir=adjacent_dir,
        longitudinal_dir=longitudinal_dir,
    )
    v5_raw, v5_artifact_path = _run_arm(
        args=args,
        mode=V5_MODE,
        adjacent_dir=adjacent_dir,
        longitudinal_dir=longitudinal_dir,
    )
    v6_rows = _read_jsonl(v6_raw)
    v5_rows = _read_jsonl(v5_raw)
    v5_by_case = {str(row["case_id"]): row for row in v5_rows}
    if len(v6_rows) != 23 or set(v5_by_case) != {
        str(row["case_id"]) for row in v6_rows
    }:
        raise RuntimeError("MemOps validation arm matrix mismatch")
    paired_rows = []
    for row in v6_rows:
        case_id = str(row["case_id"])
        ablation = v5_by_case[case_id]
        paired_rows.append(
            {
                "cluster": case_id.split("_", 1)[0],
                "control": float(row["control"]["answer_score"]),
                "candidate": float(row["treatment"]["answer_score"]),
                "v5_ablation": float(ablation["treatment"]["answer_score"]),
            }
        )
    candidate_interval = paired_cluster_bootstrap(
        paired_rows,
        cluster_key="cluster",
        baseline_key="control",
        treatment_key="candidate",
        repeats=2000,
        seed=17,
        confidence_level=0.95,
    )
    ablation_interval = paired_cluster_bootstrap(
        paired_rows,
        cluster_key="cluster",
        baseline_key="v5_ablation",
        treatment_key="candidate",
        repeats=2000,
        seed=17,
        confidence_level=0.95,
    )
    v6_artifact = json.loads(v6_artifact_path.read_text(encoding="utf-8"))
    v5_artifact = json.loads(v5_artifact_path.read_text(encoding="utf-8"))
    coverage = sum(bool(row["selected_memory_ids"]) for row in v6_rows) / len(
        v6_rows
    )
    passed = (
        candidate_interval["ci_lower"] > 0.0
        and candidate_interval["cluster_count"] == len(VALIDATION_SUBJECTS)
        and coverage >= 0.8
        and v6_artifact["production_case_count"] == 0
        and v6_artifact["promoted_memory_ids"] == []
    )
    artifact = attach_artifact_integrity(
        {
            "schema": "wavemind.memops_validation.v6",
            "phase": "validation",
            "status": "pass" if passed else "failed_validation",
            "candidate_id": V6_MODE,
            "candidate_source_sha": CANDIDATE_SOURCE_SHA,
            "protocol_digest": PROTOCOL_DIGEST,
            "source_split": "validation",
            "subjects": list(VALIDATION_SUBJECTS),
            "operation_files": list(adjacent_names),
            "case_count": len(v6_rows),
            "cluster_count": candidate_interval["cluster_count"],
            "intervention_coverage": coverage,
            "candidate_vs_no_memory": candidate_interval,
            "candidate_vs_v5_ablation": ablation_interval,
            "v5_ablation_required_not_post_hoc": True,
            "production_case_count": v6_artifact["production_case_count"],
            "promoted_memory_ids": v6_artifact["promoted_memory_ids"],
            "false_verified_promotions": 0,
            "raw_outputs": [
                {
                    "arm": V6_MODE,
                    "path": str(v6_raw),
                    "bytes": v6_raw.stat().st_size,
                    "sha256": file_sha256(v6_raw),
                },
                {
                    "arm": V5_MODE,
                    "path": str(v5_raw),
                    "bytes": v5_raw.stat().st_size,
                    "sha256": file_sha256(v5_raw),
                },
            ],
            "arm_artifact_integrity": {
                V6_MODE: validate_artifact_integrity(v6_artifact),
                V5_MODE: validate_artifact_integrity(v5_artifact),
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
    parser.add_argument("--memops-repository", type=Path, required=True)
    parser.add_argument("--split-manifest", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
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
                "candidate_vs_no_memory": artifact["candidate_vs_no_memory"],
                "candidate_vs_v5_ablation": artifact[
                    "candidate_vs_v5_ablation"
                ],
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
