from __future__ import annotations

import copy
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from wavemind.evidence import canonical_json_bytes, file_sha256, sha256_bytes


BASE = ROOT / "benchmarks" / "scientific_memory_protocol_v25.json"
V25_FAILURE = ROOT / "benchmarks" / "scientific_memops_v25_longitudinal_run1_results.json"
V26_DIAGNOSTIC = ROOT / "benchmarks" / "scientific_memops_v26_opened_diagnostic_results.json"
OUTPUT = ROOT / "benchmarks" / "scientific_memory_protocol_v27.json"


MEMOPS_DEVELOPMENT = ["A04", "C03", "D02", "E13", "F17"]
MEMOPS_FILE_COUNTS = {"A04": 4, "C03": 4, "D02": 4, "E13": 4, "F17": 5}


def main() -> int:
    base = json.loads(BASE.read_text(encoding="utf-8"))
    failure = json.loads(V25_FAILURE.read_text(encoding="utf-8"))
    diagnostic = json.loads(V26_DIAGNOSTIC.read_text(encoding="utf-8"))
    payload = copy.deepcopy(base)
    payload.update(
        {
            "schema": "wavemind.scientific_memory_protocol.v27",
            "protocol_id": "scientific-core-operation-adaptive-memory-2026-08-26-v27",
            "status": "preregistered",
            "preregistered_at": "2026-08-26",
            "supersedes_protocol_digest": base["protocol_digest"],
            "candidate": {
                "id": "operation-adaptive-memory-agent-v27",
                "memory_algorithm": (
                    "Route official MemOps probes using operation_type only: Update "
                    "to OperationApplication with target-scoped retrieval; TrajectoryOps "
                    "to OperationTrace with operation-only chronological coverage; "
                    "Forget, Reflect, and Remember to CandidateDisambiguation with "
                    "query-option-grounded target-scoped retrieval. MAB remains the "
                    "frozen v19/v14 task-aware path."
                ),
                "hypothesis": (
                    "No-memory score saturation is operation-dependent. A gold-blind "
                    "operation router should preserve perfect treatment accuracy while "
                    "exposing causal memory dependence across enough subject clusters "
                    "to yield a strictly positive lower confidence bound."
                ),
                "routing_inputs": (
                    "Pinned source name, official operation_type, evaluation_type, "
                    "question_id, operation-file name, operation dialogue, candidate "
                    "options, and explicit task text only; output, gold, expected "
                    "answer, metric values, split, and case outcome are forbidden."
                ),
                "frozen_before_first_v27_outcome": True,
            },
        }
    )
    payload["frozen_parameters"].update(
        {
            "memops_question_selection": "operation-adaptive-v7",
            "memops_trajectory_sequence_coverage": False,
            "memops_trajectory_operation_only_sequence_coverage": False,
            "memops_update_sequence_coverage": False,
            "memops_operation_trace_sequence_coverage": True,
            "memops_operation_trace_operation_only_sequence_coverage": True,
            "memops_candidate_disambiguation_query_options": True,
            "memops_candidate_disambiguation_sequence_coverage": False,
            "memops_candidate_disambiguation_operation_only_sequence_coverage": False,
        }
    )
    payload["development_firewall"] = {
        "allowed": (
            "Only the ten listed never-executed MAB development contexts and the "
            "manifest-exhaustive files of five listed never-opened MemOps development "
            "subjects."
        ),
        "forbidden": [
            "all MAB contexts or duplicate context_sha256 values opened through v26",
            "all MAB validation and final units",
            "all MemOps subjects opened through v26 development or diagnostics",
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
                "Prefix-stratified first available never-opened development subject "
                "from A, C, D, E, and F groups, selected without reading source content."
            ),
            "manifest_operation_file_counts": MEMOPS_FILE_COUNTS,
            "expected_case_count": sum(MEMOPS_FILE_COUNTS.values()),
            "question_selection": "operation-adaptive-v7",
            "required_manifest_exhaustive_files": True,
            "previously_opened": False,
        }
    )
    payload["immutable_v25_development_evidence"] = {
        "status": failure["status"],
        "outcome_path": "benchmarks/scientific_memops_v25_longitudinal_run1_results.json",
        "outcome_file_sha256": file_sha256(V25_FAILURE),
        "outcome_payload_sha256": failure["integrity"]["payload_sha256"],
        "mean_difference": failure["statistics"]["mean_difference"],
        "ci_lower": failure["statistics"]["ci_lower"],
        "failed_run_may_be_rerun": False,
        "thresholds_may_be_relaxed": False,
    }
    payload["opened_v26_diagnostic"] = {
        "path": "benchmarks/scientific_memops_v26_opened_diagnostic_results.json",
        "file_sha256": file_sha256(V26_DIAGNOSTIC),
        "payload_sha256": diagnostic["integrity"]["payload_sha256"],
        "mean_difference": diagnostic["statistics"]["mean_difference"],
        "ci_lower": diagnostic["statistics"]["ci_lower"],
        "diagnostic_gate_pass": diagnostic["diagnostic_gate_pass"],
        "official_gate_decision": False,
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
