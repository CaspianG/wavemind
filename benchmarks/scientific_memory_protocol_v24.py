from __future__ import annotations

import copy
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from wavemind.evidence import canonical_json_bytes, file_sha256, sha256_bytes


BASE = ROOT / "benchmarks" / "scientific_memory_protocol_v20.json"
V20_FAILURE = ROOT / "benchmarks" / "scientific_memops_v20_longitudinal_run1_results.json"
DIAGNOSTICS = (
    ROOT / "benchmarks" / "scientific_memops_v21_opened_diagnostic_results.json",
    ROOT / "benchmarks" / "scientific_memops_v22_opened_diagnostic_results.json",
    ROOT / "benchmarks" / "scientific_memops_v23_opened_diagnostic_results.json",
)
OUTPUT = ROOT / "benchmarks" / "scientific_memory_protocol_v24.json"


MAB_DEVELOPMENT = [
    "Long_Range_Understanding:0079:8d12067c93f36205",
    "Long_Range_Understanding:0080:1e3c9386f6389d19",
    "Long_Range_Understanding:0081:b448d04712c3b0ff",
    "Long_Range_Understanding:0084:c0f8cf56d00012e9",
    "Long_Range_Understanding:0086:99d769c182f259fd",
    "Long_Range_Understanding:0087:cf4482da4014b92c",
    "Long_Range_Understanding:0092:4221d0632c354128",
    "Long_Range_Understanding:0093:e9669039f2684bf4",
    "Long_Range_Understanding:0097:1ebe843e50d22cae",
    "Long_Range_Understanding:0099:fe7d09b9fd9f2c33",
]
MEMOPS_DEVELOPMENT = ["A04", "B30", "C02", "D01", "E07"]
MAB_FINAL = [
    "Long_Range_Understanding:0069:c7f1535f7238600e",
    "Long_Range_Understanding:0070:8a93d4cd5cbd681e",
    "Long_Range_Understanding:0072:893a573e50a0f0ec",
    "Long_Range_Understanding:0076:3448e84ad791bded",
    "Long_Range_Understanding:0077:d3fa1ef5e2ffc10b",
    "Long_Range_Understanding:0078:ef8ee769eeaaf621",
    "Long_Range_Understanding:0083:db96042a8a5aa313",
    "Long_Range_Understanding:0085:a348120f6cdda6a0",
    "Long_Range_Understanding:0088:4f8eeff8019e736b",
    "Long_Range_Understanding:0098:b8164c32e0eba3df",
]
MEMOPS_FINAL = ["B23", "C11", "D20", "E08", "E11"]


def main() -> int:
    base = json.loads(BASE.read_text(encoding="utf-8"))
    v20_failure = json.loads(V20_FAILURE.read_text(encoding="utf-8"))
    diagnostics = [json.loads(path.read_text(encoding="utf-8")) for path in DIAGNOSTICS]
    payload = copy.deepcopy(base)
    payload.update(
        {
            "schema": "wavemind.scientific_memory_protocol.v24",
            "protocol_id": "scientific-core-targeted-operation-application-2026-08-26-v24",
            "status": "preregistered",
            "preregistered_at": "2026-08-26",
            "supersedes_protocol_digest": base["protocol_digest"],
            "candidate": {
                "id": "targeted-operation-application-agent-v24",
                "memory_algorithm": (
                    "Select the earliest official OperationApplication question using "
                    "evaluation_type and question_id only. Use v19 target-scoped "
                    "operation retrieval for every MemOps file without blind sequence "
                    "coverage. MAB routing remains the frozen v19/v14 task-aware path."
                ),
                "hypothesis": (
                    "OperationTrace and option-choice probes allow high no-memory judge "
                    "scores. A multi-hop OperationApplication probe requires applying "
                    "retrieved current state to a new decision and should preserve "
                    "perfect treatment accuracy while producing a strictly positive "
                    "subject-cluster lower confidence bound."
                ),
                "routing_inputs": (
                    "Pinned source name, official evaluation_type, question_id, "
                    "operation-file name, operation dialogue, candidate options, and "
                    "explicit task text only; output, gold, expected answer, metric "
                    "values, split, and case outcome are forbidden."
                ),
                "frozen_before_first_v24_outcome": True,
            },
        }
    )
    payload["frozen_parameters"].update(
        {
            "memops_question_selection": "causal-application-v2",
            "memops_trajectory_sequence_coverage": False,
            "memops_trajectory_operation_only_sequence_coverage": False,
            "memops_update_sequence_coverage": False,
            "memops_operation_trace_sequence_coverage": False,
            "memops_operation_trace_operation_only_sequence_coverage": False,
            "memops_candidate_disambiguation_query_options": False,
            "memops_candidate_disambiguation_sequence_coverage": False,
            "memops_candidate_disambiguation_operation_only_sequence_coverage": False,
        }
    )
    payload["development_firewall"] = {
        "allowed": (
            "Only the ten listed never-executed MAB development contexts and five "
            "listed never-opened MemOps development subjects."
        ),
        "forbidden": [
            "all MAB contexts or duplicate context_sha256 values opened through v23",
            "all MAB validation and final units",
            "all MemOps subjects opened through v23 development or diagnostics",
            "all MemOps validation and final subjects",
            "all LongMemEval-V2 examples",
        ],
    }
    payload["frozen_development_gate"]["families"] = {
        "memoryagentbench_summarization": {
            "unit_ids": MAB_DEVELOPMENT,
            "selection": (
                "Ten frozen v20 development rows never executed because v20 stopped "
                "at its first MemOps fail-fast gate."
            ),
            "required_source": "infbench_sum_eng_shots2",
            "cluster": "whole context_sha256",
            "queries_per_context": 1,
        },
        "memops_longitudinal_operation": {
            "subjects": MEMOPS_DEVELOPMENT,
            "selection": (
                "One never-opened development subject from each of five distinct "
                "subject-ID groups, selected without reading source content."
            ),
            "evaluation_setting": "longitudinal_operation",
            "questions_per_operation_file": 1,
            "question_selection": "causal-application-v2",
            "cluster": "subject_id",
            "required_operation_files_per_subject": 5,
            "previously_opened": False,
        },
    }
    payload["frozen_admission"].update(
        {
            "memoryagentbench_fresh_final_unit_ids": MAB_FINAL,
            "memops_final_subjects": MEMOPS_FINAL,
        }
    )
    payload["immutable_v20_development_evidence"] = {
        "status": v20_failure["status"],
        "outcome_path": "benchmarks/scientific_memops_v20_longitudinal_run1_results.json",
        "outcome_file_sha256": file_sha256(V20_FAILURE),
        "outcome_payload_sha256": v20_failure["integrity"]["payload_sha256"],
        "mean_difference": v20_failure["statistics"]["mean_difference"],
        "ci_lower": v20_failure["statistics"]["ci_lower"],
        "failed_run_may_be_rerun": False,
        "thresholds_may_be_relaxed": False,
    }
    payload["opened_v21_v23_diagnostics"] = [
        {
            "path": f"benchmarks/{path.name}",
            "file_sha256": file_sha256(path),
            "payload_sha256": result["integrity"]["payload_sha256"],
            "candidate_id": result["candidate_id"],
            "mean_difference": result["statistics"]["mean_difference"],
            "ci_lower": result["statistics"]["ci_lower"],
            "diagnostic_gate_pass": result["diagnostic_gate_pass"],
            "official_gate_decision": False,
        }
        for path, result in zip(DIAGNOSTICS, diagnostics)
    ]
    payload["claim_boundary"] = (
        "Only full exact-SHA admission permits a bounded claim; 100%-pass, SOTA, "
        "universal, production, and revolutionary claims remain forbidden without "
        "separate evidence."
    )
    payload.pop("opened_v20_diagnostic", None)
    payload.pop("protocol_digest", None)
    payload["protocol_digest"] = sha256_bytes(canonical_json_bytes(payload))
    OUTPUT.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    print(json.dumps(payload, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
