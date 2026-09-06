from __future__ import annotations

import copy
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from wavemind.evidence import canonical_json_bytes, file_sha256, sha256_bytes


BASE = ROOT / "benchmarks" / "scientific_memory_protocol_v19.json"
V19_OUTCOME = ROOT / "benchmarks" / "scientific_v19_admission_outcome.json"
DIAGNOSTIC = ROOT / "benchmarks" / "scientific_memops_v20_opened_diagnostic_results.json"
OUTPUT = ROOT / "benchmarks" / "scientific_memory_protocol_v20.json"


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
MEMOPS_DEVELOPMENT = ["C23", "C28", "E03", "F01", "F13"]
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
    outcome = json.loads(V19_OUTCOME.read_text(encoding="utf-8"))
    diagnostic = json.loads(DIAGNOSTIC.read_text(encoding="utf-8"))
    payload = copy.deepcopy(base)
    payload.update(
        {
            "schema": "wavemind.scientific_memory_protocol.v20",
            "protocol_id": (
                "scientific-core-operation-trace-dual-coverage-2026-08-26-v20"
            ),
            "status": "preregistered",
            "preregistered_at": "2026-08-26",
            "supersedes_protocol_digest": base["protocol_digest"],
            "candidate": {
                "id": "operation-trace-dual-coverage-agent-v20",
                "memory_algorithm": (
                    "Retain v19 target-scoped retrieval and trajectory operation-only "
                    "coverage. Select the earliest official OperationTrace question "
                    "using evaluation_type and question_id only. For every selected "
                    "OperationTrace question, add deterministic chronological coverage "
                    "restricted to explicit memory-operation dialogue, regardless of "
                    "operation-file type. MAB routing remains the frozen v19/v14 path."
                ),
                "hypothesis": (
                    "State-verification questions frequently permit a correct no-memory "
                    "answer from their own wording. A gold-blind OperationTrace-first "
                    "selector plus operation-only chronological coverage should expose "
                    "causal memory dependence and yield a strictly positive subject-"
                    "cluster lower confidence bound on five fresh MemOps subjects."
                ),
                "routing_inputs": (
                    "Pinned source name, official evaluation_type, question_id, "
                    "operation-file name, operation dialogue, candidate options, and "
                    "explicit task text only; output, gold, expected answer, metric "
                    "values, split, and case outcome are forbidden."
                ),
                "frozen_before_first_v20_outcome": True,
            },
        }
    )
    payload["frozen_parameters"].update(
        {
            "memops_question_selection": "memory-dependence-v5",
            "memops_operation_trace_sequence_coverage": True,
            "memops_operation_trace_operation_only_sequence_coverage": True,
        }
    )
    payload["development_firewall"] = {
        "allowed": (
            "Only the ten listed untouched MAB development contexts and five listed "
            "untouched MemOps development subjects."
        ),
        "forbidden": [
            "all MAB contexts or duplicate context_sha256 values opened through v19",
            "all MAB validation and final units, including v19 final outcomes",
            "all MemOps subjects opened through v19 development, diagnostics, or final",
            "all MemOps validation and final subjects",
            "all LongMemEval-V2 examples",
        ],
    }
    payload["frozen_development_gate"]["families"] = {
        "memoryagentbench_summarization": {
            "unit_ids": MAB_DEVELOPMENT,
            "selection": (
                "Ten never-executed development rows with unique context_sha256 after "
                "excluding every raw-opened unit and duplicate fingerprint."
            ),
            "required_source": "infbench_sum_eng_shots2",
            "cluster": "whole context_sha256",
            "queries_per_context": 1,
        },
        "memops_longitudinal_operation": {
            "subjects": MEMOPS_DEVELOPMENT,
            "evaluation_setting": "longitudinal_operation",
            "questions_per_operation_file": 1,
            "question_selection": "memory-dependence-v5",
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
    payload["immutable_v19_admission_evidence"] = {
        "status": outcome["status"],
        "outcome_path": "benchmarks/scientific_v19_admission_outcome.json",
        "outcome_file_sha256": file_sha256(V19_OUTCOME),
        "outcome_payload_sha256": outcome["integrity"]["payload_sha256"],
        "mab_final_passed": True,
        "memops_final_mean_difference": 0.15,
        "memops_final_ci_lower": 0.0,
        "opened_v19_final_cases_may_be_reused": False,
        "thresholds_may_be_relaxed": False,
    }
    payload["opened_v20_diagnostic"] = {
        "status": "positive_on_opened_development_diagnostic_only",
        "outcome_path": (
            "benchmarks/scientific_memops_v20_opened_diagnostic_results.json"
        ),
        "outcome_file_sha256": file_sha256(DIAGNOSTIC),
        "outcome_payload_sha256": diagnostic["integrity"]["payload_sha256"],
        "observed_cases": diagnostic["case_count"],
        "mean_difference": diagnostic["statistics"]["mean_difference"],
        "ci_lower": diagnostic["statistics"]["ci_lower"],
        "official_gate_decision": False,
    }
    payload["claim_boundary"] = (
        "Only full exact-SHA admission permits a bounded claim; 100%-pass, SOTA, "
        "universal, production, and revolutionary claims remain forbidden without "
        "separate evidence."
    )
    payload.pop("failed_v18_opened_diagnostic", None)
    payload.pop("opened_diagnostic_evidence", None)
    payload.pop("immutable_v17_evidence", None)
    payload.pop("protocol_digest", None)
    payload["protocol_digest"] = sha256_bytes(canonical_json_bytes(payload))
    OUTPUT.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    print(json.dumps(payload, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
