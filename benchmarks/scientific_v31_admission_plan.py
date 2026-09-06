from __future__ import annotations

import json
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


CANDIDATE_SHA = "2a55c83ef3d3e4a3c5d9dff4418258eacb378127"
PROTOCOL = ROOT / "benchmarks" / "scientific_memory_protocol_v31.json"
DEVELOPMENT = ROOT / "benchmarks" / "scientific_v31_development_outcome.json"
MAB_SPLIT = ROOT / "benchmarks" / "memoryagentbench_split_manifest_results.json"
MEMOPS_SPLIT = ROOT / "benchmarks" / "evaluation_split_manifest_results.json"
OUTPUT = ROOT / "benchmarks" / "scientific_v31_admission_plan.json"
DEVELOPMENT_OUTCOME_COMMIT = "f76ffd0c23f608c15e232771d292b88f5cbbb904"
HARNESS_SOURCE_COMMIT = "8d5052b94dea2cdc2db020208800577e3267ab3c"
HARNESSES = (
    "benchmarks/scientific_mab_v19_final.py",
    "benchmarks/scientific_mab_v31_final.py",
    "benchmarks/scientific_memops_v31_final.py",
    "benchmarks/scientific_longmemeval_v2_backend.py",
    "benchmarks/scientific_longmemeval_v2_backend_v31.py",
    "benchmarks/scientific_longmemeval_v2_run.py",
    "benchmarks/scientific_longmemeval_v2_run_v31.py",
)


def _record(path: Path) -> dict[str, object]:
    return {
        "path": path.relative_to(ROOT).as_posix(),
        "bytes": path.stat().st_size,
        "sha256": file_sha256(path),
    }


def main() -> int:
    protocol = json.loads(PROTOCOL.read_text(encoding="utf-8"))
    development = json.loads(DEVELOPMENT.read_text(encoding="utf-8"))
    mab_split = json.loads(MAB_SPLIT.read_text(encoding="utf-8"))
    memops_split = json.loads(MEMOPS_SPLIT.read_text(encoding="utf-8"))
    for label, payload in (
        ("development outcome", development),
        ("MAB split", mab_split),
        ("MemOps split", memops_split),
    ):
        errors = validate_artifact_integrity(payload)
        if errors:
            raise RuntimeError(f"invalid {label} integrity: {errors}")
    if development["status"] != "passed_development_gate_v31":
        raise RuntimeError("v31 development gate has not passed")
    if development["candidate_source_sha"] != CANDIDATE_SHA:
        raise RuntimeError("development outcome candidate SHA mismatch")
    if development["protocol_digest"] != protocol["protocol_digest"]:
        raise RuntimeError("development outcome protocol mismatch")
    if development.get("admission_permitted_next") is not True:
        raise RuntimeError("development outcome does not permit admission")

    admission = protocol["frozen_admission"]
    mab_ids = tuple(admission["memoryagentbench_fresh_final_unit_ids"])
    mab_rows = [row for row in mab_split["units"] if row.get("unit_id") in mab_ids]
    if {str(row["unit_id"]) for row in mab_rows} != set(mab_ids):
        raise RuntimeError("frozen MAB final unit missing")
    if any(row.get("split") != "final" for row in mab_rows):
        raise RuntimeError("frozen MAB unit is not final")
    if len({str(row["context_sha256"]) for row in mab_rows}) != len(mab_ids):
        raise RuntimeError("MAB final context fingerprints are not independent")

    subjects = tuple(admission["memops_final_subjects"])
    memops_rows = [
        row
        for row in memops_split["units"]
        if row.get("dataset") == "memops" and row.get("subject_id") in subjects
    ]
    if {str(row["subject_id"]) for row in memops_rows} != set(subjects):
        raise RuntimeError("frozen MemOps final subject missing")
    if any(row.get("split") != "final" for row in memops_rows):
        raise RuntimeError("frozen MemOps subject is not final")

    payload = attach_artifact_integrity(
        {
            "schema": "wavemind.scientific_v31_admission_plan.v1",
            "status": "preregistered_before_first_v31_final_outcome",
            "preregistered_at": "2026-08-26",
            "candidate": {
                "id": "operation-routed-target-state-agent-v31",
                "source_sha": CANDIDATE_SHA,
                "checkout_policy": "clean detached exact-SHA worktree",
                "post_outcome_changes_forbidden": True,
            },
            "protocol": {
                **_record(PROTOCOL),
                "protocol_digest": protocol["protocol_digest"],
            },
            "authorization_evidence": {
                "development_gate_status": development["status"],
                "development_gate_commit": DEVELOPMENT_OUTCOME_COMMIT,
                "development_outcome": _record(DEVELOPMENT),
                "development_outcome_payload_sha256": development["integrity"][
                    "payload_sha256"
                ],
                "independent_families_passed": 2,
                "reproducible_runs_per_family_passed": 3,
                "all_six_required_runs_passed": True,
            },
            "execution_harness": {
                "source_commit": HARNESS_SOURCE_COMMIT,
                "files": [_record(ROOT / path) for path in HARNESSES],
                "infrastructure_continuation": (
                    "A crashed partial is retained and may continue only with the "
                    "identical candidate, data, prompts, model, thresholds, order, "
                    "and deterministic parameters; it is never discarded or counted "
                    "as a fresh outcome."
                ),
            },
            "official_sources": {
                "memoryagentbench": {
                    "code_sha": "fe1735de8cf8b9908e1e3d3b5612afc815698062",
                    "dataset_revision": "7ea066982b140a19337e17e60d45d4076e042faf",
                    "split_manifest": _record(MAB_SPLIT),
                    "split_manifest_payload_sha256": mab_split["integrity"][
                        "payload_sha256"
                    ],
                },
                "memops": {
                    "code_and_data_sha": "312af65e2c7b6d1b70f062ffa8b4cde32aaf6f35",
                    "split_manifest": _record(MEMOPS_SPLIT),
                    "split_manifest_payload_sha256": memops_split["integrity"][
                        "payload_sha256"
                    ],
                },
                "longmemeval_v2": {
                    "code_sha": "2cc8c540bdb87fe6761629b585e727e1c4704520",
                    "dataset_repo": "xiaowu0162/longmemeval-v2",
                    "dataset_revision": admission["longmemeval_v2_dataset_revision"],
                    "remote_revision_verified_available_at_preregistration": True,
                },
            },
            "frozen_samples": {
                "memoryagentbench": {
                    "source_split": "final",
                    "unit_ids": list(mab_ids),
                    "context_sha256": sorted(
                        str(row["context_sha256"]) for row in mab_rows
                    ),
                    "required_independent_clusters": 10,
                    "queries_per_context": 1,
                    "candidate_mode": "task-aware-sequence-coverage-agent-v11",
                },
                "memops": {
                    "source_split": "final",
                    "subjects": list(subjects),
                    "unit_ids": sorted(str(row["unit_id"]) for row in memops_rows),
                    "required_independent_subject_clusters": 5,
                    "question_selection": "operation-adaptive-v7",
                    "candidate_mode_default": "target-state-cutover-agent-v29",
                    "candidate_mode_by_operation": {
                        "TrajectoryOps": "target-scoped-operation-agent-v16"
                    },
                },
                "longmemeval_v2": {
                    "tier": admission["longmemeval_v2_tier"],
                    "question_count": admission["longmemeval_v2_question_count"],
                    "maximum_logical_full_runs": admission[
                        "maximum_longmemeval_v2_logical_full_runs"
                    ],
                },
            },
            "frozen_parameters": protocol["frozen_parameters"],
            "frozen_gates": {
                "memoryagentbench_and_memops": {
                    "paired_cluster_bootstrap_ci_lower_strictly_greater_than": 0.0,
                    "mean_non_negative": True,
                    "minimum_intervention_coverage": 0.8,
                    "false_verified_promotions_maximum": 0,
                    "production_case_count_maximum": 0,
                },
                "longmemeval_v2": {
                    "uplift_minimum": admission["longmemeval_v2_uplift_minimum"],
                    "improved_categories_minimum": admission[
                        "longmemeval_v2_improved_categories_minimum"
                    ],
                    "repeated_error_reduction_minimum": admission[
                        "repeated_error_reduction_minimum"
                    ],
                    "stale_or_contradiction_error_rate_maximum": admission[
                        "stale_or_contradiction_error_rate_maximum"
                    ],
                    "context_reduction_vs_full_context_minimum": admission[
                        "context_reduction_vs_full_context_minimum"
                    ],
                    "runtime_p95_must_be_within_frozen_budget": admission[
                        "runtime_p95_must_be_within_frozen_budget"
                    ],
                    "ablation_required_for_every_improvement": admission[
                        "ablation_required_for_every_improvement"
                    ],
                },
            },
            "stage_order": {
                "arms": [
                    "memoryagentbench_final",
                    "memops_final",
                    "longmemeval_v2_small_full",
                ],
                "stop_on_first_failure": True,
                "rationale": (
                    "Fail-fast preserves every later independent held-out arm when "
                    "an earlier necessary arm fails."
                ),
            },
            "held_out_state_at_preregistration": {
                "memoryagentbench_final_outcomes_opened": False,
                "memops_final_outcomes_opened": False,
                "longmemeval_v2_examples_downloaded": False,
                "longmemeval_v2_full_runs": 0,
            },
            "decision_rule": (
                "Full v31 admission passes only when every frozen arm passes on the "
                "exact candidate SHA with all raw evidence retained and validated. "
                "Any failed arm is immutable and stops later held-out execution."
            ),
            "claim_boundary": (
                "Preregistration is not a benchmark result. Even a single arm pass "
                "does not authorize a 100%-pass, SOTA, production, universal, or "
                "revolutionary claim."
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
