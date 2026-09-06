from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
OFFICIAL = (
    ROOT.parents[1]
    / "scientific-evidence"
    / "upstreams"
    / "longmemeval-v2"
)
CANDIDATE = ROOT.parent / "wavemind-scientific-v6-admission"


def _module():
    path = ROOT / "benchmarks" / "scientific_longmemeval_v2_backend.py"
    spec = importlib.util.spec_from_file_location("scientific_lme_v6_backend", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_state_slices_are_deterministic_and_bounded():
    module = _module()
    trajectory = {
        "id": "trajectory-1",
        "environment": "shop",
        "goal": "buy tea",
        "outcome": "success",
        "states": [
            {
                "state_index": 2,
                "url": "https://example.test/tea",
                "action": "click checkout",
                "thought": "finish",
                "accessibility_tree": "tea " * 1400,
            }
        ],
    }
    first = module._state_slices(trajectory)
    second = module._state_slices(trajectory)

    assert first == second
    assert len(first) == 3
    assert all(row["trajectory_id"] == "trajectory-1" for row in first)
    assert all(len(row["text"]) < module.STATE_SLICE_CHARACTERS + 300 for row in first)


@pytest.mark.skipif(
    not OFFICIAL.is_dir(),
    reason="official LongMemEval v2 upstream is not included in this repository",
)
def test_registered_backend_is_gold_blind_atomic_and_production_empty(tmp_path):
    module = _module()
    backend_class = module.register_backend(
        official_repository=OFFICIAL,
        candidate_repository=CANDIDATE,
    )
    backend = backend_class({"scratch_root": str(tmp_path)})
    try:
        backend.insert(
            {
                "id": "trajectory-1",
                "domain": "web",
                "environment": "shop",
                "goal": "find the tea checkout rule",
                "outcome": "success",
                "states": [
                    {
                        "state_index": 0,
                        "url": "https://example.test/tea",
                        "action": "open checkout",
                        "thought": "observe",
                        "accessibility_tree": (
                            "Tea checkout requires selecting a delivery window."
                        ),
                    }
                ],
            }
        )
        context = backend.query("What does tea checkout require?")
        metadata = backend.post_query_hook(
            query="What does tea checkout require?",
            query_image=None,
            memory_context=context,
        )
    finally:
        backend.close()

    assert context
    assert metadata is not None
    assert metadata["candidate_source_sha"] == module.CANDIDATE_SOURCE_SHA
    assert metadata["event_chain_valid"] is True
    assert metadata["production_index_count"] == 0
    assert metadata["evaluation_only"] is True
    assert metadata["intervention_present"] is True
    assert metadata["selected_estimated_tokens"] <= 8192
    assert metadata["selected_estimated_tokens"] < metadata["full_context_estimated_tokens"] + 1
