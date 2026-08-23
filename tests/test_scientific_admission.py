from __future__ import annotations

from pathlib import Path

from wavemind.evidence import attach_artifact_integrity
from wavemind.scientific_admission import (
    SCIENTIFIC_RUN_SCHEMA,
    evaluate_scientific_memory_admission,
    validate_scientific_run,
)
from wavemind.scientific_protocol import (
    REQUIRED_BASELINES,
    load_scientific_protocol,
)


ROOT = Path(__file__).resolve().parents[1]
PROTOCOL_PATH = ROOT / "benchmarks" / "scientific_memory_protocol_v1.json"
SOURCE_SHA = "a" * 40
CANDIDATE = "causal-utility-controller-v1"
SHA256 = "b" * 64


def _arm(*, candidate: bool) -> dict[str, float | int]:
    return {
        "task_success": 1.0 if candidate else 0.0,
        "repeated_errors": 0 if candidate else 1,
        "stale_or_contradiction_errors": 0,
        "false_verified_promotions": 0,
        "context_tokens": 50 if candidate else 100,
        "runtime_ms": 1.0,
    }


def _row(family: str, case_id: str, category: str) -> dict[str, object]:
    arms = {baseline: _arm(candidate=False) for baseline in REQUIRED_BASELINES}
    arms[CANDIDATE] = _arm(candidate=True)
    return {
        "benchmark_family": family,
        "case_id": case_id,
        "category": category,
        "full_context_tokens": 100,
        "verification": {
            "source": "test",
            "receipt_digest": SHA256,
            "evidence_digest": SHA256,
        },
        "arms": arms,
    }


def _run(run_number: int, protocol: dict[str, object]) -> dict[str, object]:
    families = ["memops", "memoryagentbench", "state-bench-agent-learning"]
    rows = [
        _row(family, f"{family}-case-{case}", f"category-{case}")
        for family in families
        for case in range(3)
    ]
    if run_number == 1:
        rows.extend(
            _row(
                "longmemeval-v2",
                f"longmemeval-v2-case-{case}",
                f"category-{case // 2}",
            )
            for case in range(10)
        )
    ablation_ids = protocol["evaluation"]["required_ablations"]  # type: ignore[index]
    ablation_rows = [
        {
            "ablation_id": ablation_id,
            "benchmark_family": family,
            "case_id": f"{family}-ablation-case",
            "with_component_success": 1.0,
            "without_component_success": 0.0,
        }
        for family in (
            "memops",
            "memoryagentbench",
            "state-bench-agent-learning",
            "longmemeval-v2",
        )
        for ablation_id in ablation_ids
    ]
    run = {
        "schema": SCIENTIFIC_RUN_SCHEMA,
        "phase": "held-out-admission",
        "source_sha": SOURCE_SHA,
        "protocol_digest": protocol["protocol_digest"],
        "candidate_id": CANDIDATE,
        "run_id": f"run-{run_number}",
        "seed": run_number * 11,
        "longmemeval_v2_full_run": run_number == 1,
        "controls": {
            "model_id": "frozen-model",
            "model_revision": "revision-1",
            "prompt_bytes": 100,
            "prompt_sha256": SHA256,
            "embedding_model_id": "frozen-embedding",
            "embedding_model_revision": "revision-1",
            "seed_list": [11, 22, 33],
            "token_budget": 100,
            "hardware_inventory": "cpu:test",
            "runtime_lock_sha256": SHA256,
            "case_order_sha256": SHA256,
            "latency_budget_ms": 10.0,
        },
        "baselines_executed": sorted(REQUIRED_BASELINES),
        "package_metadata": {
            "mem0-oss": {
                "package": "mem0ai",
                "version": "1.0.0",
                "source_revision": "c" * 40,
                "execution": "real-local-package",
            },
            "langgraph": {
                "package": "langgraph",
                "version": "1.0.0",
                "source_revision": "d" * 40,
                "execution": "real-local-package",
            },
            "chroma": {
                "package": "chromadb",
                "version": "1.0.0",
                "execution": "real-local-package",
            },
            "qdrant-local": {
                "package": "qdrant-client",
                "version": "1.0.0",
                "execution": "real-local-package",
            },
        },
        "raw_rows": rows,
        "ablation_rows": ablation_rows,
    }
    return attach_artifact_integrity(run)


def test_missing_evidence_is_failed_experiment_not_an_admission():
    result = evaluate_scientific_memory_admission(
        [],
        protocol_path=PROTOCOL_PATH,
        project_root=ROOT,
        expected_source_sha=SOURCE_SHA,
    )

    assert result["status"] == "failed_experiment"
    assert result["admitted"] is False
    assert result["admitted_candidates"] == []


def test_agent_self_verification_and_tampering_are_rejected():
    protocol = load_scientific_protocol(PROTOCOL_PATH)
    run = _run(1, protocol)
    run["raw_rows"][0]["verification"]["source"] = "agent_self"

    errors = validate_scientific_run(
        run,
        protocol=protocol,
        expected_source_sha=SOURCE_SHA,
    )

    assert "artifact payload digest mismatch" in errors
    assert "raw row 0 verifier is not independent" in errors


def test_exact_three_run_positive_evidence_can_be_admitted():
    protocol = load_scientific_protocol(PROTOCOL_PATH)
    runs = [_run(index, protocol) for index in (1, 2, 3)]

    result = evaluate_scientific_memory_admission(
        runs,
        protocol_path=PROTOCOL_PATH,
        project_root=ROOT,
        expected_source_sha=SOURCE_SHA,
    )

    assert result["status"] == "admitted"
    assert result["admitted_candidates"] == [CANDIDATE]
    candidate = result["candidate_results"][CANDIDATE]
    assert candidate["admitted"] is True
    assert all(check["passed"] for check in candidate["checks"])
    assert candidate["metrics"]["positive_uplift_lcb_families"] == 4
    assert candidate["metrics"]["longmemeval_v2_improved_categories"] == 5
