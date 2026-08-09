from __future__ import annotations

import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DATASET = ROOT / "benchmarks" / "data" / "safe_product_retrieval_v3_holdout.json"
PROTOCOL = ROOT / "benchmarks" / "data" / "safe_product_retrieval_v3_protocol.json"


def test_v3_holdout_is_sealed_before_first_execution() -> None:
    dataset = json.loads(DATASET.read_text(encoding="utf-8"))
    protocol = json.loads(PROTOCOL.read_text(encoding="utf-8"))

    assert hashlib.sha256(DATASET.read_bytes()).hexdigest() == protocol[
        "dataset_sha256"
    ]
    assert dataset["revision"] == protocol["revision"]
    assert dataset["holdout_status"] == "sealed_unexecuted"
    assert len(dataset["memories"]) == 20
    assert len(dataset["relevant_queries"]) == 20
    assert len(dataset["irrelevant_queries"]) == 60
    assert protocol["execution_policy"] == {
        "first_execution_only_for_admission": True,
        "execute_only_after_protocol_commit": True,
        "maximum_admission_executions": 1,
        "failure_action": "record_blocked_without_tuning",
    }
    assert protocol["production_candidate"]["confidence_gate"] is True
    assert protocol["comparison_baseline"]["confidence_gate"] is False
    assert protocol["frozen_gates"] == {
        "max_false_memory_injection_rate": 0.02,
        "min_relevant_recall_at_1": 0.9,
        "min_relevant_recall_ratio_vs_baseline": 0.95,
        "namespace_leakage": 0,
        "unverified_injection": 0,
    }
