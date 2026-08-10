from __future__ import annotations

import hashlib
import json
from pathlib import Path

from wavemind.evidence import validate_artifact_integrity


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DECISION_PATH = PROJECT_ROOT / "benchmarks" / "quality_leadership_stop_decision.json"


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_quality_leadership_stop_decision_is_fail_closed_and_reproducible() -> None:
    decision = _load(DECISION_PATH)

    assert validate_artifact_integrity(decision) == []
    assert decision["status"] == "blocked"
    assert decision["decision"] == (
        "stop_after_two_failed_bounded_development_candidates"
    )
    assert decision["go_no_go"] == {
        "max_architecture_candidates_before_blocked": 2,
        "attempted_candidates": 2,
        "failed_candidates": 2,
        "tuning_allowed": False,
        "candidate_3_allowed": False,
        "held_out_opened": False,
        "gpu_or_full_run_allowed": False,
    }

    candidates = decision["candidates"]
    assert [candidate["id"] for candidate in candidates] == [
        "candidate-1",
        "candidate-2-memoryagentbench-balanced",
    ]
    assert all(candidate["status"] == "failed" for candidate in candidates)
    assert all(candidate["held_out_policy"] == "not_opened" for candidate in candidates)

    for candidate in candidates:
        artifact = PROJECT_ROOT / candidate["artifact"]
        assert _sha256(artifact) == candidate["artifact_sha256"]

    candidate2 = candidates[1]
    protocol_path = PROJECT_ROOT / candidate2["protocol_artifact"]
    per_query_path = PROJECT_ROOT / candidate2["per_query_artifact"]
    assert _sha256(protocol_path) == candidate2["protocol_artifact_sha256"]
    assert _sha256(per_query_path) == candidate2["per_query_artifact_sha256"]

    protocol = _load(protocol_path)
    diagnostic = _load(PROJECT_ROOT / candidate2["artifact"])
    assert protocol["new_quality_dataset"]["held_out_viewed"] is False
    assert diagnostic["protocol"]["held_out_viewed"] is False
    assert diagnostic["paired_lift"]["overall_task_success"]["mean"] == 0.0
    assert candidate2["metrics"]["memory_os_uplift_over_core"] == 0.0
    assert candidate2["metrics"]["improved_category_count"] == 0
    assert candidate2["metrics"]["p95_overhead_ms"] > 5.0
    assert candidate2["protocol_review"]["fixable_runner_or_protocol_defect"] is False

    taxonomy_path = PROJECT_ROOT / decision["canonical_taxonomy_artifact"]
    assert _sha256(taxonomy_path) == decision["canonical_taxonomy_artifact_sha256"]
    taxonomy = _load(taxonomy_path)["blocker_taxonomy"]
    assert taxonomy["candidate"] == "candidate-2-memoryagentbench-balanced"
    assert taxonomy["candidate_status"] == "failed"
    assert taxonomy["held_out_policy"].startswith("not_opened")
