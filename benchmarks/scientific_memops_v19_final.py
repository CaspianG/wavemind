from __future__ import annotations

import argparse
import copy
import importlib.util
import json
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


CANDIDATE_ID = "targeted-dual-coverage-agent-v19"
CANDIDATE_SOURCE_SHA = "c509511f09dbcd3b4206ec1b74a7abc9510d9e73"
PROTOCOL_DIGEST = "443d8a461b10969756579eb6af3e05d7b909d30369fb286b2a582aa8efaef684"
FINAL_SUBJECTS = ("A05", "A11", "A20", "B03", "B04")
FAMILY = "memops_longitudinal_operation"


def _subject_id(path: Path) -> str:
    return path.stem.split("_", 1)[0]


def _load_base(candidate_root: Path):
    path = candidate_root / "benchmarks" / "scientific_memops_v10_development.py"
    spec = importlib.util.spec_from_file_location(
        "wavemind_scientific_memops_v19_final_base", path
    )
    if spec is None or spec.loader is None:
        raise RuntimeError("unable to load isolated v19 MemOps final runner")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _validate_final_inputs(
    *,
    split_manifest_path: Path,
    adjacent_input_dir: Path,
    longitudinal_input_dir: Path,
) -> None:
    manifest = json.loads(split_manifest_path.read_text(encoding="utf-8"))
    errors = validate_artifact_integrity(manifest)
    if errors:
        raise RuntimeError(f"MemOps split manifest integrity failed: {errors}")
    selected = [
        row
        for row in manifest["units"]
        if row.get("dataset") == "memops"
        and row.get("subject_id") in FINAL_SUBJECTS
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


def _derived_protocol(protocol: dict[str, Any], output: Path) -> Path:
    derived = copy.deepcopy(protocol)
    derived["frozen_development_gate"] = {
        "families": {
            FAMILY: {
                "subjects": list(FINAL_SUBJECTS),
                "evaluation_setting": "longitudinal_operation",
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
    protocol_path = candidate_root / "benchmarks" / "scientific_memory_protocol_v19.json"
    protocol = json.loads(protocol_path.read_text(encoding="utf-8"))
    if protocol["protocol_digest"] != PROTOCOL_DIGEST:
        raise RuntimeError("v19 protocol digest changed")
    if tuple(protocol["frozen_admission"]["memops_final_subjects"]) != FINAL_SUBJECTS:
        raise RuntimeError("v19 final subject set changed")
    _validate_final_inputs(
        split_manifest_path=args.split_manifest,
        adjacent_input_dir=args.adjacent_input_dir,
        longitudinal_input_dir=args.longitudinal_input_dir,
    )

    base = _load_base(candidate_root)
    from wavemind.scientific_runtime import ScientificCandidateMode

    derived_protocol = _derived_protocol(
        protocol, args.output_dir / "derived_final_protocol.json"
    )
    base.PROTOCOL_PATH = derived_protocol
    base.CANDIDATE_MODE = ScientificCandidateMode.TARGET_SCOPED_OPERATION_AGENT
    base.CANDIDATE_ID_OVERRIDE = CANDIDATE_ID
    base.ARTIFACT_SCHEMA = "wavemind.scientific_memops_v19_final_intermediate.v1"
    base.CLUSTER_GATE_KEY = "minimum_independent_clusters_per_family"
    base.CI_GATE_KEY = "paired_cluster_bootstrap_ci_lower_strictly_greater_than"
    base.QUESTION_SELECTION = "state-verification-v4"
    base.TRAJECTORY_SEQUENCE_COVERAGE = True
    base.TRAJECTORY_OPERATION_ONLY_SEQUENCE_COVERAGE = True
    base.UPDATE_SEQUENCE_COVERAGE = False
    base.ARTIFACT_PHASE = "final"
    base.DIAGNOSTIC_ONLY = False
    status = base.main(
        [
            "--upstream-root",
            str(args.upstream_root),
            "--upstream-sha",
            args.upstream_sha,
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
            "schema": "wavemind.scientific_memops_v19_final.v1",
            "phase": "final",
            "admission_eligible": True,
            "status": "pass" if intermediate["gate_pass"] else "failed_final",
            "source_split": "final",
            "final_split_touched": True,
            "claim_boundary": (
                "MemOps final arm only; full v19 admission remains incomplete until "
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
    parser = argparse.ArgumentParser(description="Run frozen v19 MemOps final arm")
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


def main() -> int:
    artifact = run(parse_args())
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
