from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "benchmarks" / "scientific_v31_admission_outcome.py"


def _load_module():
    name = "test_scientific_v31_admission_outcome_module"
    spec = importlib.util.spec_from_file_location(name, MODULE_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def _rows(*, candidate: bool) -> list[dict[str, object]]:
    categories = (
        "static",
        "static-abs",
        "dynamic",
        "dynamic-abs",
        "procedure",
        "procedure-abs",
        "gotchas",
    )
    rows: list[dict[str, object]] = []
    for index in range(451):
        rows.append(
            {
                "question_id": f"question-{index:03d}",
                "category": categories[index % len(categories)],
                "score": 1.0 if candidate else 0.0,
                "memory_query_duration_seconds": 0.25 if candidate else 0.0,
                "memory_post_query_metadata": (
                    {
                        "selected_estimated_tokens": 50,
                        "full_context_estimated_tokens": 100,
                    }
                    if candidate
                    else {}
                ),
            }
        )
    return rows


def test_v31_longmem_derivation_is_paired_and_uses_all_451_rows():
    module = _load_module()

    metrics = module.derive_longmem_metrics(
        {
            "no_retrieval": _rows(candidate=False),
            "candidate": _rows(candidate=True),
        }
    )

    assert metrics["paired_question_count"] == 451
    assert metrics["baseline_overall"] == 0.0
    assert metrics["candidate_overall"] == 1.0
    assert metrics["uplift"] == 1.0
    assert metrics["improved_categories"] == [
        "dynamic",
        "gotchas",
        "procedure",
        "static",
    ]
    assert metrics["context_reduction_vs_full_context"] == 0.5
    assert metrics["runtime_p95_seconds"] == 0.25
    assert metrics["paired_no_retrieval_ablation_complete"] is True


def test_v31_longmem_derivation_keeps_unmeasured_gates_fail_closed():
    module = _load_module()

    metrics = module.derive_longmem_metrics(
        {
            "no_retrieval": _rows(candidate=False),
            "candidate": _rows(candidate=True),
        }
    )

    assert metrics["repeated_error_reduction"]["verifiable"] is False
    assert metrics["repeated_error_reduction"]["value"] is None
    assert metrics["stale_or_contradiction_error_rate"]["verifiable"] is False
    assert metrics["stale_or_contradiction_error_rate"]["value"] is None


def test_v31_longmem_derivation_rejects_unpaired_question_ids():
    module = _load_module()
    candidate = _rows(candidate=True)
    candidate[-1] = {**candidate[-1], "question_id": "different-question"}

    with pytest.raises(RuntimeError, match="question IDs differ"):
        module.derive_longmem_metrics(
            {
                "no_retrieval": _rows(candidate=False),
                "candidate": candidate,
            }
        )


def test_v31_longmem_derivation_rejects_nonofficial_category():
    module = _load_module()
    candidate = _rows(candidate=True)
    candidate[0] = {**candidate[0], "category": "invented-after-outcome"}

    with pytest.raises(RuntimeError, match="categories differ"):
        module.derive_longmem_metrics(
            {
                "no_retrieval": _rows(candidate=False),
                "candidate": candidate,
            }
        )
