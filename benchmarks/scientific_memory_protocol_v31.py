from __future__ import annotations

import copy
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from wavemind.evidence import canonical_json_bytes, file_sha256, sha256_bytes


BASE = ROOT / "benchmarks" / "scientific_memory_protocol_v27.json"
V27_FAILURE = ROOT / "benchmarks" / "scientific_memops_v27_longitudinal_run1_results.json"
V27_RAW = ROOT / "benchmarks" / "scientific_memops_v27_longitudinal_run1" / "raw_pairs.jsonl"
V28_DIAGNOSTIC = ROOT / "benchmarks" / "scientific_memops_v28_opened_diagnostic_results.json"
V29_DIAGNOSTIC = ROOT / "benchmarks" / "scientific_memops_v29_opened_diagnostic_results.json"
V29_RAW = ROOT / "benchmarks" / "scientific_memops_v29_opened_diagnostic" / "raw_pairs.jsonl"
OUTPUT = ROOT / "benchmarks" / "scientific_memory_protocol_v31.json"


MEMOPS_DEVELOPMENT = [
    "A01",
    "B01",
    "C01",
    "D10",
    "E01",
    "F06",
    "A02",
    "B10",
    "C04",
    "D11",
]
MEMOPS_FILE_COUNTS = {
    "A01": 4,
    "B01": 5,
    "C01": 4,
    "D10": 4,
    "E01": 4,
    "F06": 4,
    "A02": 5,
    "B10": 4,
    "C04": 4,
    "D11": 4,
}


def _row(path: Path, case_id: str) -> dict:
    for line in path.read_text(encoding="utf-8").splitlines():
        row = json.loads(line)
        if row["case_id"] == case_id:
            return row
    raise RuntimeError(f"missing opened diagnostic case: {case_id}")


def main() -> int:
    base = json.loads(BASE.read_text(encoding="utf-8"))
    v27 = json.loads(V27_FAILURE.read_text(encoding="utf-8"))
    v28 = json.loads(V28_DIAGNOSTIC.read_text(encoding="utf-8"))
    v29 = json.loads(V29_DIAGNOSTIC.read_text(encoding="utf-8"))
    d02_trajectory = _row(V27_RAW, "D02_trajectory_ops_q2")
    f17_forget = _row(V29_RAW, "F17_forget_q8")
    payload = copy.deepcopy(base)
    payload.update(
        {
            "schema": "wavemind.scientific_memory_protocol.v31",
            "protocol_id": "scientific-core-operation-routed-target-state-2026-08-26-v31",
            "status": "preregistered",
            "preregistered_at": "2026-08-26",
            "supersedes_protocol_digest": base["protocol_digest"],
            "candidate": {
                "id": "operation-routed-target-state-agent-v31",
                "memory_algorithm": (
                    "Use target-state tombstone cutover for targeted retrieval while "
                    "routing official TrajectoryOps files to the previously validated "
                    "session-level operation-only chronological coverage path. Select "
                    "questions with the frozen operation-adaptive-v7 router. MAB "
                    "remains the frozen task-aware sequence-coverage path."
                ),
                "hypothesis": (
                    "A deletion cutover removes stale pre-tombstone target state, while "
                    "operation-specific routing prevents local deletion parsing from "
                    "dropping evidence required by global trajectory reconstruction. "
                    "Ten independent manifest-selected subjects reduce the effect of "
                    "no-memory saturation without changing any statistical threshold."
                ),
                "routing_inputs": (
                    "Pinned source name, official operation_type, evaluation_type, "
                    "question_id, operation-file name, operation dialogue, candidate "
                    "options, and explicit task text only; output, gold, expected "
                    "answer, metric values, split, and case outcome are forbidden."
                ),
                "frozen_before_first_v31_outcome": True,
            },
        }
    )
    payload["frozen_parameters"].update(
        {
            "memops_question_selection": "operation-adaptive-v7",
            "memops_candidate_mode_default": "target-state-cutover-agent-v29",
            "memops_candidate_mode_by_operation": {
                "TrajectoryOps": "target-scoped-operation-agent-v16"
            },
            "memops_slice_local_operation_markers": True,
            "memops_target_state_tombstone_cutover": True,
            "memops_operation_trace_sequence_coverage": True,
            "memops_operation_trace_operation_only_sequence_coverage": True,
            "memops_candidate_disambiguation_query_options": True,
            "memops_candidate_disambiguation_sequence_coverage": False,
            "memops_candidate_disambiguation_operation_only_sequence_coverage": False,
        }
    )
    payload["development_firewall"] = {
        "allowed": (
            "Only the ten listed never-executed MAB development contexts and all 42 "
            "manifest-listed operation files of the ten listed never-opened MemOps "
            "development subjects."
        ),
        "forbidden": [
            "all MAB contexts or duplicate context_sha256 values opened through v30",
            "all MAB validation and final units",
            "all MemOps subjects opened through v30 development or diagnostics",
            "all MemOps validation and final subjects",
            "all LongMemEval-V2 examples",
        ],
    }
    memops = payload["frozen_development_gate"]["families"][
        "memops_longitudinal_operation"
    ]
    memops.update(
        {
            "subjects": MEMOPS_DEVELOPMENT,
            "selection": (
                "Prefix-round-robin first available never-opened subjects from A-F, "
                "selected from filenames and operation-file counts only, without "
                "reading source content or outcomes."
            ),
            "manifest_operation_file_counts": MEMOPS_FILE_COUNTS,
            "expected_case_count": sum(MEMOPS_FILE_COUNTS.values()),
            "question_selection": "operation-adaptive-v7",
            "required_manifest_exhaustive_files": True,
            "previously_opened": False,
        }
    )
    payload["immutable_v27_development_evidence"] = {
        "status": v27["status"],
        "outcome_path": "benchmarks/scientific_memops_v27_longitudinal_run1_results.json",
        "outcome_file_sha256": file_sha256(V27_FAILURE),
        "outcome_payload_sha256": v27["integrity"]["payload_sha256"],
        "mean_difference": v27["statistics"]["mean_difference"],
        "ci_lower": v27["statistics"]["ci_lower"],
        "failed_run_may_be_rerun": False,
        "thresholds_may_be_relaxed": False,
    }
    payload["opened_v28_v29_diagnostics"] = [
        {
            "path": "benchmarks/scientific_memops_v28_opened_diagnostic_results.json",
            "file_sha256": file_sha256(V28_DIAGNOSTIC),
            "payload_sha256": v28["integrity"]["payload_sha256"],
            "mean_difference": v28["statistics"]["mean_difference"],
            "ci_lower": v28["statistics"]["ci_lower"],
            "diagnostic_gate_pass": v28["diagnostic_gate_pass"],
            "official_gate_decision": False,
        },
        {
            "path": "benchmarks/scientific_memops_v29_opened_diagnostic_results.json",
            "file_sha256": file_sha256(V29_DIAGNOSTIC),
            "payload_sha256": v29["integrity"]["payload_sha256"],
            "mean_difference": v29["statistics"]["mean_difference"],
            "ci_lower": v29["statistics"]["ci_lower"],
            "diagnostic_gate_pass": v29["diagnostic_gate_pass"],
            "official_gate_decision": False,
        },
    ]
    payload["opened_compositional_evidence"] = {
        "official_gate_decision": False,
        "trajectory_path": "v27 target-scoped operation-only chronological coverage",
        "trajectory_case_id": d02_trajectory["case_id"],
        "trajectory_treatment_score": d02_trajectory["treatment_score"],
        "trajectory_evidence_sha256": d02_trajectory["evidence_sha256"],
        "forget_path": "v29 target-state tombstone cutover",
        "forget_case_id": f17_forget["case_id"],
        "forget_treatment_score": f17_forget["treatment_score"],
        "forget_evidence_sha256": f17_forget["evidence_sha256"],
        "fresh_confirmation_required": True,
    }
    payload["claim_boundary"] = (
        "Only full exact-SHA admission permits a bounded claim; 100%-pass, SOTA, "
        "universal, production, and revolutionary claims remain forbidden without "
        "separate evidence."
    )
    payload.pop("protocol_digest", None)
    payload["protocol_digest"] = sha256_bytes(canonical_json_bytes(payload))
    OUTPUT.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    print(json.dumps(payload, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
