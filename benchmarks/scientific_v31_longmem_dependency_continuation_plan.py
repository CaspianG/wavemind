from __future__ import annotations

import importlib.metadata
import json
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from wavemind.evidence import (
    attach_artifact_integrity,
    file_sha256,
    validate_artifact_integrity,
)


CANDIDATE_SOURCE_SHA = "2a55c83ef3d3e4a3c5d9dff4418258eacb378127"
FIXED_HARNESS_COMMIT = "303d06138fd205a36ea15473c13d0aa71fe4b150"
FIRST_CONTINUATION_PLAN_COMMIT = "30ceb43dfb241843c67960cb9ff5f172018ca6f2"
SECOND_FAILURE_COMMIT = "15e5e42c26dcb1bcf2a1d49c16e556e57f003264"
PILLOW_VERSION = "12.3.0"
FIRST_CONTINUATION_PLAN = (
    ROOT / "benchmarks" / "scientific_v31_longmem_continuation_plan.json"
)
SECOND_FAILURE = (
    ROOT / "benchmarks" / "scientific_v31_longmem_infrastructure_failure_2.json"
)
MARKER = (
    ROOT
    / "benchmarks"
    / "scientific_longmemeval_v31_final"
    / "full_run_marker.json"
)
DIST_INFO = (
    ROOT.parents[1]
    / "scientific-env"
    / "Lib"
    / "site-packages"
    / f"pillow-{PILLOW_VERSION}.dist-info"
)
HARNESS_WORKTREE = ROOT.parent / "wavemind-scientific-v31-longmem-continuation-exact"
CANDIDATE_WORKTREE = ROOT.parent / "wavemind-scientific-v31-official-exact"
OUTPUT = (
    ROOT / "benchmarks" / "scientific_v31_longmem_dependency_continuation_plan.json"
)


def _record(path: Path) -> dict[str, object]:
    return {
        "path": path.relative_to(ROOT).as_posix(),
        "bytes": path.stat().st_size,
        "sha256": file_sha256(path),
    }


def _environment_record(path: Path) -> dict[str, object]:
    return {
        "environment_relative_path": path.relative_to(
            ROOT.parents[1] / "scientific-env"
        ).as_posix(),
        "bytes": path.stat().st_size,
        "sha256": file_sha256(path),
    }


def _git(*args: str, cwd: Path) -> str:
    return subprocess.check_output(["git", *args], cwd=cwd, text=True).strip()


def main() -> int:
    first_plan = json.loads(FIRST_CONTINUATION_PLAN.read_text(encoding="utf-8"))
    failure = json.loads(SECOND_FAILURE.read_text(encoding="utf-8"))
    marker = json.loads(MARKER.read_text(encoding="utf-8"))
    for label, payload in (("continuation plan", first_plan), ("failure", failure)):
        errors = validate_artifact_integrity(payload)
        if errors:
            raise RuntimeError(f"invalid {label} integrity: {errors}")
    if failure["observed_state"]["outcome_scores_opened"] is not False:
        raise RuntimeError("LongMem outcomes were opened before dependency planning")
    if marker.get("logical_full_run_count") != 1 or marker.get("status") == "completed":
        raise RuntimeError("dependency continuation is not in the incomplete run")
    distribution = importlib.metadata.distribution("pillow")
    if distribution.version != PILLOW_VERSION:
        raise RuntimeError("resolved Pillow version changed")
    if _git("rev-parse", "HEAD", cwd=HARNESS_WORKTREE) != FIXED_HARNESS_COMMIT:
        raise RuntimeError("harness worktree commit changed")
    if _git("status", "--porcelain", cwd=HARNESS_WORKTREE):
        raise RuntimeError("harness worktree is dirty")
    if _git("rev-parse", "HEAD", cwd=CANDIDATE_WORKTREE) != CANDIDATE_SOURCE_SHA:
        raise RuntimeError("candidate worktree commit changed")
    if _git("status", "--porcelain", cwd=CANDIDATE_WORKTREE):
        raise RuntimeError("candidate worktree is dirty")

    payload = attach_artifact_integrity(
        {
            "schema": "wavemind.scientific_v31_longmem_dependency_continuation.v1",
            "status": "preregistered_dependency_continuation_before_outcome",
            "preregistered_at": "2026-08-26",
            "logical_run": "longmemeval_v2_small_full_v31",
            "logical_full_run_count": 1,
            "candidate_source_sha": CANDIDATE_SOURCE_SHA,
            "fixed_harness_commit": FIXED_HARNESS_COMMIT,
            "prior_continuation_plan": {
                **_record(FIRST_CONTINUATION_PLAN),
                "commit": FIRST_CONTINUATION_PLAN_COMMIT,
                "payload_sha256": first_plan["integrity"]["payload_sha256"],
            },
            "second_infrastructure_failure": {
                **_record(SECOND_FAILURE),
                "commit": SECOND_FAILURE_COMMIT,
                "payload_sha256": failure["integrity"]["payload_sha256"],
                "outcome_scores_opened": False,
                "scientific_gate_evaluated": False,
            },
            "environment_change": {
                "package": "pillow",
                "resolved_version": PILLOW_VERSION,
                "official_dependency_declared": True,
                "installed_package_count": 1,
                "import_name": "PIL",
                "import_verified": True,
                "distribution_files": [
                    _environment_record(DIST_INFO / name)
                    for name in ("METADATA", "WHEEL", "RECORD")
                ],
                "candidate_files_changed": 0,
                "harness_files_changed": 0,
            },
            "semantic_invariants": first_plan["semantic_invariants"],
            "continuation_execution": {
                "same_output_root_required": (
                    "benchmarks/scientific_longmemeval_v31_final"
                ),
                "same_marker_required": True,
                "logical_full_run_count_must_remain": 1,
                "second_partial_must_be_retained": True,
                "restart_first_incomplete_arm": "candidate_web_small",
                "fixed_harness_commit_required": FIXED_HARNESS_COMMIT,
                "candidate_source_sha_required": CANDIDATE_SOURCE_SHA,
                "fresh_scientific_run_forbidden": True,
            },
            "decision_rule": (
                "Continuation may resume only after Pillow 12.3.0 import succeeds, "
                "from the unchanged fixed harness and candidate worktrees, inside "
                "the existing logical full run."
            ),
            "claim_boundary": (
                "Installing a missing official dependency is not a benchmark outcome "
                "and authorizes no pass or revolutionary claim."
            ),
        }
    )
    OUTPUT.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    print(json.dumps(payload, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
