from __future__ import annotations

from pathlib import Path

from wavemind.evaluation_lifecycle_diagnostic import (
    NoMemoryBackend,
    StaticLastWriteWinsBackend,
    WaveMindCoreLifecycleBackend,
    classify_error,
    expected_state,
    score_observation,
)


def _operation(
    operation_id: str,
    kind: str,
    *,
    value: str | None,
    validity: str = "confirmed",
) -> dict:
    return {
        "operation_id": operation_id,
        "type": kind,
        "validity": validity,
        "target": {"target_id": "preference", "target_name": "Preference"},
        "old_value": None,
        "new_value": value,
        "evidence_spans": [{"segment_index": 1, "turn_index": 1, "quote": value}],
    }


def test_expected_state_applies_confirmed_updates_and_forgetting():
    operations = [
        _operation("one", "remember", value="old"),
        _operation("two", "update", value="tentative", validity="tentative"),
        _operation("three", "update", value="current"),
    ]
    assert expected_state(operations)["preference"]["value"] == "current"
    operations.append(_operation("four", "forget", value=None))
    assert expected_state(operations) == {}


def test_static_lww_is_strong_valid_operation_baseline():
    backend = StaticLastWriteWinsBackend()
    for operation in (
        _operation("one", "remember", value="old"),
        _operation("two", "update", value="current"),
    ):
        backend.apply(operation)
    score = score_observation(
        expected={"value": "current"},
        observation=backend.observe("preference", "Preference"),
    )
    assert score["target_correct"] is True
    assert score["stale_leakage"] is False


def test_no_memory_exposes_missing_state_transition():
    backend = NoMemoryBackend()
    score = score_observation(
        expected={"value": "current"},
        observation=backend.observe("preference", "Preference"),
    )
    assert score["target_correct"] is False
    assert score["over_forgetting"] is True
    assert classify_error(operation_type="Update", score=score) == "missing_state_transition"


def test_core_blocks_tentative_injection_and_preserves_namespace(tmp_path: Path):
    backend = WaveMindCoreLifecycleBackend(
        tmp_path / "core.sqlite3", namespace="tenant:one"
    )
    try:
        backend.apply(_operation("one", "remember", value="confirmed"))
        backend.apply(
            _operation("two", "update", value="tentative", validity="tentative")
        )
        observation = backend.observe("preference", "Preference")
        assert observation["wrong_namespace"] == []
        assert all(item["value"] != "tentative" for item in observation["active"])
    finally:
        backend.close()


def test_core_append_only_update_is_detected_as_stale(tmp_path: Path):
    backend = WaveMindCoreLifecycleBackend(
        tmp_path / "core.sqlite3", namespace="tenant:one"
    )
    try:
        for operation in (
            _operation("one", "remember", value="old"),
            _operation("two", "update", value="current"),
        ):
            backend.apply(operation)
        score = score_observation(
            expected={"value": "current"},
            observation=backend.observe("preference", "Preference"),
        )
        assert score["stale_leakage"] is True
        assert (
            classify_error(operation_type="Update", score=score)
            == "stale_or_contradictory_selection"
        )
    finally:
        backend.close()


def test_core_forget_removes_target_without_neighbor_over_forgetting(tmp_path: Path):
    backend = WaveMindCoreLifecycleBackend(
        tmp_path / "core.sqlite3", namespace="tenant:one"
    )
    try:
        target = _operation("one", "remember", value="remove")
        neighbor = {
            **_operation("neighbor", "remember", value="keep"),
            "target": {"target_id": "neighbor", "target_name": "Neighbor"},
        }
        backend.apply(target)
        backend.apply(neighbor)
        backend.apply(_operation("forget", "forget", value=None))
        assert backend.observe("preference", "Preference")["active"] == []
        assert backend.observe("neighbor", "Neighbor")["selected"]["value"] == "keep"
    finally:
        backend.close()
