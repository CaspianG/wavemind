from __future__ import annotations

import json
from pathlib import Path

from wavemind.evidence import validate_artifact_integrity


ROOT = Path(__file__).resolve().parents[1]
RESULT = ROOT / "benchmarks" / "scientific_v31_longmem_loopback_probe_results.json"


def test_loopback_probe_is_synthetic_and_integrity_bound():
    payload = json.loads(RESULT.read_text(encoding="utf-8"))

    assert validate_artifact_integrity(payload) == []
    assert payload["status"] == "passed_synthetic_loopback_transport_probe"
    assert payload["probe_scope"] == "infrastructure_only_synthetic_text"
    assert payload["scientific_boundary"] == {
        "benchmark_prompt_read": False,
        "benchmark_answer_read": False,
        "gold_read": False,
        "score_read": False,
        "synthetic_model_calls_only": True,
        "model_or_digest_changed": False,
        "threshold_changed": False,
    }


def test_loopback_probe_proves_proxy_interception_and_bypass():
    payload = json.loads(RESULT.read_text(encoding="utf-8"))
    contrast = payload["observed_transport_contrast"]
    concurrent = payload["no_proxy_concurrent_openai_sdk"]

    assert contrast["inherited_httpx_trust_env_true"]["status"] == 503
    assert contrast["explicit_httpx_trust_env_false"]["status"] == 200
    assert concurrent["no_proxy"] == "127.0.0.1,localhost"
    assert concurrent["request_count"] == 4
    assert concurrent["all_status_200"] is True
    assert [row["status"] for row in concurrent["results"]] == [200, 200, 200, 200]
