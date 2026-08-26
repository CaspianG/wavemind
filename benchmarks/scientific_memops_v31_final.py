from __future__ import annotations

import argparse
import copy
import importlib.util
import json
import subprocess
import sys
from pathlib import Path
from typing import Any, Sequence


ROOT = Path(__file__).resolve().parents[1]
CANDIDATE_ID = "operation-routed-target-state-agent-v31"
CANDIDATE_SOURCE_SHA = "2a55c83ef3d3e4a3c5d9dff4418258eacb378127"
PROTOCOL_DIGEST = "bc1f895bdf8bd30027bcc17f1c3a375099c8ee442681382c56ba57fa7580793b"
OFFICIAL_UPSTREAM_SHA = "312af65e2c7b6d1b70f062ffa8b4cde32aaf6f35"
FINAL_SUBJECTS = ("B23", "C11", "D20", "E08", "E11")
FAMILY = "memops_longitudinal_operation"


def _git_sha(path: Path) -> str:
    return subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=path, text=True, encoding="utf-8"
    ).strip()


def _load_candidate_base(candidate_root: Path):
    path = candidate_root / "benchmarks" / "scientific_memops_v31_development.py"
    spec = importlib.util.spec_from_file_location(
        "wavemind_scientific_memops_v31_final_base", path
    )
    if spec is None or spec.loader is None:
        raise RuntimeError("unable to load isolated v31 MemOps final runner")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _validate_final_inputs(
    *,
    split_manifest_path: Path,
    adjacent_input_dir: Path,
    longitudinal_input_dir: Path,
) -> int:
    from wavemind.evidence import validate_artifact_integrity

    manifest = json.loads(split_manifest_path.read_text(encoding="utf-8"))
    errors = validate_artifact_integrity(manifest)
    if errors:
        raise RuntimeError(f"MemOps split manifest integrity failed: {errors}")
    selected = [
        row
        for row in manifest["units"]
        if row.get("dataset") == "memops" and row.get("subject_id") in FINAL_SUBJECTS
    ]
    if {str(row["subject_id"]) for row in selected} != set(FINAL_SUBJECTS):
        raise RuntimeError("frozen MemOps final subject is missing from split manifest")
    if any(row.get("split") != "final" for row in selected):
        raise RuntimeError("frozen MemOps subject is no longer final")
    expected_names = {f"{row['unit_id']}.json" for row in selected}
    adjacent_names = {path.name for path in adjacent_input_dir.glob("*.json")}
    longitudinal_names = {path.name for path in longitudinal_input_dir.glob("*.json")}
    if adjacent_names != expected_names or longitudinal_names != expected_names:
        raise RuntimeError("MemOps final input files differ from frozen subject units")
    return len(selected)


def _derived_protocol(
    protocol: dict[str, Any], output: Path, expected_case_count: int
) -> Path:
    derived = copy.deepcopy(protocol)
    derived["frozen_development_gate"] = {
        "families": {
            FAMILY: {
                "subjects": list(FINAL_SUBJECTS),
                "evaluation_setting": "longitudinal_operation",
                "expected_case_count": expected_case_count,
            }
        },
        "required_reproducible_runs": 1,
        "required_independent_families": 1,
        "minimum_independent_clusters_per_family": 5,
        "paired_cluster_bootstrap_ci_lower_strictly_greater_than": 0.0,
        "minimum_intervention_coverage": 0.8,
        "all_family_means_non_negative": True,
        "false_verified_promotions_maximum": 0,
        "production_case_count_maximum": 0,
        "raw_per_case_evidence_required": True,
        "stop_on_first_failed_required_run": True,
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(derived, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    return output


def run(args: argparse.Namespace) -> dict[str, Any]:
    candidate_root = args.candidate_repository.resolve()
    upstream_root = args.upstream_root.resolve()
    if args.upstream_sha != OFFICIAL_UPSTREAM_SHA:
        raise RuntimeError("MemOps upstream SHA argument changed")
    if _git_sha(upstream_root) != OFFICIAL_UPSTREAM_SHA:
        raise RuntimeError("official MemOps checkout SHA changed")
    protocol_path = candidate_root / "benchmarks" / "scientific_memory_protocol_v31.json"
    protocol = json.loads(protocol_path.read_text(encoding="utf-8"))
    if protocol["protocol_digest"] != PROTOCOL_DIGEST:
        raise RuntimeError("v31 protocol digest changed")
    if tuple(protocol["frozen_admission"]["memops_final_subjects"]) != FINAL_SUBJECTS:
        raise RuntimeError("v31 final subject set changed")

    for root in (candidate_root,):
        value = str(root)
        if value in sys.path:
            sys.path.remove(value)
        sys.path.insert(0, value)
    expected_case_count = _validate_final_inputs(
        split_manifest_path=args.split_manifest,
        adjacent_input_dir=args.adjacent_input_dir,
        longitudinal_input_dir=args.longitudinal_input_dir,
    )
    base = _load_candidate_base(candidate_root)
    from wavemind.evidence import (
        attach_artifact_integrity,
        file_sha256,
        validate_artifact_integrity,
    )
    from wavemind.scientific_runtime import ScientificCandidateMode

    derived_protocol = _derived_protocol(
        protocol,
        args.output_dir / "derived_final_protocol.json",
        expected_case_count,
    )
    configured = base.runner
    configured.PROTOCOL_PATH = derived_protocol
    configured.CANDIDATE_MODE = ScientificCandidateMode.TARGET_STATE_CUTOVER_AGENT
    configured.CANDIDATE_MODE_BY_OPERATION = {
        "TrajectoryOps": ScientificCandidateMode.TARGET_SCOPED_OPERATION_AGENT,
    }
    configured.CANDIDATE_ID_OVERRIDE = CANDIDATE_ID
    configured.ARTIFACT_SCHEMA = "wavemind.scientific_memops_v31_final_intermediate.v1"
    configured.CLUSTER_GATE_KEY = "minimum_independent_clusters_per_family"
    configured.CI_GATE_KEY = "paired_cluster_bootstrap_ci_lower_strictly_greater_than"
    configured.QUESTION_SELECTION = "operation-adaptive-v7"
    configured.TRAJECTORY_SEQUENCE_COVERAGE = False
    configured.TRAJECTORY_OPERATION_ONLY_SEQUENCE_COVERAGE = False
    configured.UPDATE_SEQUENCE_COVERAGE = False
    configured.OPERATION_TRACE_SEQUENCE_COVERAGE = True
    configured.OPERATION_TRACE_OPERATION_ONLY_SEQUENCE_COVERAGE = True
    configured.CANDIDATE_DISAMBIGUATION_QUERY_OPTIONS = True
    configured.CANDIDATE_DISAMBIGUATION_SEQUENCE_COVERAGE = False
    configured.CANDIDATE_DISAMBIGUATION_OPERATION_ONLY_SEQUENCE_COVERAGE = False
    configured.ARTIFACT_PHASE = "final"
    configured.DIAGNOSTIC_ONLY = False
    status = base.main(
        [
            "--upstream-root",
            str(upstream_root),
            "--upstream-sha",
            OFFICIAL_UPSTREAM_SHA,
            "--adjacent-input-dir",
            str(args.adjacent_input_dir),
            "--longitudinal-input-dir",
            str(args.longitudinal_input_dir),
            "--family",
            FAMILY,
            "--run-number",
            "1",
            "--expected-source-sha",
            CANDIDATE_SOURCE_SHA,
            "--output-dir",
            str(args.output_dir),
            "--artifact",
            str(args.artifact),
            "--ollama-endpoint",
            args.ollama_endpoint,
        ]
    )
    intermediate = json.loads(args.artifact.read_text(encoding="utf-8"))
    if validate_artifact_integrity(intermediate):
        raise RuntimeError("intermediate MemOps final artifact integrity failed")
    raw_path = Path(intermediate["raw_output"]["path"])
    if file_sha256(raw_path) != intermediate["raw_output"]["sha256"]:
        raise RuntimeError("MemOps final raw evidence hash mismatch")
    intermediate.pop("integrity", None)
    intermediate.update(
        {
            "schema": "wavemind.scientific_memops_v31_final.v1",
            "phase": "final",
            "admission_eligible": True,
            "status": "pass" if intermediate["gate_pass"] else "failed_final",
            "source_split": "final",
            "final_split_touched": True,
            "claim_boundary": (
                "MemOps final arm only; full v31 admission remains incomplete until "
                "every later frozen arm passes."
            ),
        }
    )
    artifact = attach_artifact_integrity(intermediate)
    args.artifact.write_text(
        json.dumps(artifact, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    if status not in (0, 2):
        raise RuntimeError(f"unexpected intermediate exit status: {status}")
    return artifact


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run frozen v31 MemOps final arm")
    parser.add_argument("--candidate-repository", type=Path, required=True)
    parser.add_argument("--upstream-root", type=Path, required=True)
    parser.add_argument("--upstream-sha", required=True)
    parser.add_argument("--split-manifest", type=Path, required=True)
    parser.add_argument("--adjacent-input-dir", type=Path, required=True)
    parser.add_argument("--longitudinal-input-dir", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--artifact", type=Path, required=True)
    parser.add_argument("--ollama-endpoint", default="http://127.0.0.1:11435")
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    artifact = run(parse_args(argv))
    print(
        json.dumps(
            {
                "status": artifact["status"],
                "statistics": artifact["statistics"],
                "gate_checks": artifact["gate_checks"],
            },
            indent=2,
        )
    )
    return 0 if artifact["gate_pass"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
