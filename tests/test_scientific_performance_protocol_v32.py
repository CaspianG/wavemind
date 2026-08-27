from __future__ import annotations

import json
from pathlib import Path

from wavemind.evidence import canonical_json_bytes, sha256_bytes


ROOT = Path(__file__).resolve().parents[1]
PROTOCOL = ROOT / "benchmarks" / "scientific_performance_protocol_v32.json"


def test_v32_performance_protocol_is_digest_bound_and_pre_execution():
    payload = json.loads(PROTOCOL.read_text(encoding="utf-8"))
    content = dict(payload)
    digest = content.pop("protocol_digest")

    assert digest == sha256_bytes(canonical_json_bytes(content))
    assert payload["status"] == "preregistered_before_first_v32_workload_execution"
    assert payload["candidate"]["source_sha"] == (
        "d33163840ee2871f66cac3c585853aa031eb79ab"
    )
    assert payload["workloads"]["development"]["executed_at_preregistration"] is False
    assert payload["workloads"]["validation"]["executed_at_preregistration"] is False


def test_v32_preserves_latency_and_exactness_without_v31_tuning():
    payload = json.loads(PROTOCOL.read_text(encoding="utf-8"))
    gates = payload["frozen_gates"]

    assert gates["exact_selection_equality_every_query_every_repeat"] is True
    assert gates["indexed_p95_seconds_maximum_every_repeat"] == 1.0
    assert gates["p95_speedup_minimum_every_repeat"] == 5.0
    assert gates["required_repeats"] == 3
    assert payload["firewall"]["forbidden"][0].startswith(
        "all v31 LongMemEval per-question"
    )
    assert payload["relationship_to_v31"]["v31_rows_reusable_for_tuning"] is False
    assert payload["relationship_to_v31"]["v31_status_may_be_rewritten"] is False
    assert payload["relationship_to_v31"]["v32_scope"] == (
        "performance development and validation only"
    )
