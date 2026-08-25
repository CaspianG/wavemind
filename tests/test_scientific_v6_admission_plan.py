from __future__ import annotations

import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PLAN = ROOT / "benchmarks" / "scientific_v6_admission_plan.json"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_v6_admission_plan_is_frozen_before_held_out_execution():
    payload = json.loads(PLAN.read_text(encoding="utf-8"))
    expected_digest = payload.pop("plan_digest")
    actual_digest = hashlib.sha256(
        json.dumps(
            payload,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        ).encode("utf-8")
    ).hexdigest()

    assert actual_digest == expected_digest
    assert payload["status"] == "preregistered"
    assert payload["candidate"]["source_sha"] == (
        "a8240fe6bd9a79aec3d524b1cbbbdb4b907f8d97"
    )
    assert payload["held_out_state_at_preregistration"] == {
        "memoryagentbench_validation_outcomes_opened": False,
        "memops_validation_outcomes_opened": False,
        "longmemeval_v2_examples_downloaded": False,
        "longmemeval_v2_full_runs": 0,
    }
    assert payload["frozen_metrics"]["longmemeval_v2"]["uplift_minimum"] == 0.01
    assert (
        payload["frozen_metrics"]["longmemeval_v2"][
            "improved_categories_minimum"
        ]
        == 4
    )
    assert (
        payload["frozen_metrics"]["family_validation"][
            "ci_lower_strictly_greater_than"
        ]
        == 0.0
    )
    for record in payload["execution_harness"]["files"]:
        assert _sha256(ROOT / record["path"]) == record["sha256"]
