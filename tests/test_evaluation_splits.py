from __future__ import annotations

import copy
from pathlib import Path

from wavemind.evaluation_splits import (
    MEMOPS_REVISION,
    STATE_BENCH_REVISION,
    _overlaps,
    _stable_partition,
    validate_evaluation_split_manifest,
)
from wavemind.evidence import attach_artifact_integrity, build_source_manifest


ROOT = Path(__file__).resolve().parents[1]


def _fixture() -> dict:
    units = [
        {
            "dataset": "state-bench",
            "unit_id": "state:a",
            "source_split": "train",
            "split": "development",
            "conversation_fingerprint": "a" * 64,
            "trajectory_fingerprint": "a" * 64,
            "derived_fingerprint": "1" * 64,
        },
        {
            "dataset": "state-bench",
            "unit_id": "state:b",
            "source_split": "test",
            "split": "final",
            "conversation_fingerprint": None,
            "trajectory_fingerprint": None,
            "derived_fingerprint": "2" * 64,
        },
        {
            "dataset": "memops",
            "unit_id": "memops:a",
            "subject_id": "A01",
            "split": "validation",
            "conversation_fingerprint": "b" * 64,
            "trajectory_fingerprint": "c" * 64,
            "derived_fingerprint": "3" * 64,
        },
    ]
    payload = {
        "schema": "wavemind.evaluation_split_manifest.v1",
        "source_sha": "f" * 40,
        "upstream": {
            "state-bench": {"revision": STATE_BENCH_REVISION},
            "memops": {"revision": MEMOPS_REVISION},
        },
        "overlaps": _overlaps(units),
        "units": units,
        "source_manifest": build_source_manifest(
            ROOT,
            (
                "wavemind/evaluation_splits.py",
                "benchmarks/evaluation_split_manifest.py",
                "tests/test_evaluation_splits.py",
            ),
        ),
    }
    return attach_artifact_integrity(payload)


def _resign(payload: dict) -> dict:
    payload.pop("integrity", None)
    return attach_artifact_integrity(payload)


def test_stable_partition_is_deterministic_and_exact_size():
    identifiers = [f"task-{index}" for index in range(10)]
    first = _stable_partition(identifiers, salt="revision", counts=(6, 2, 2))
    second = _stable_partition(
        list(reversed(identifiers)), salt="revision", counts=(6, 2, 2)
    )
    assert first == second
    assert list(first.values()).count("development") == 6
    assert list(first.values()).count("validation") == 2
    assert list(first.values()).count("final") == 2


def test_split_validator_accepts_disjoint_fixture():
    assert (
        validate_evaluation_split_manifest(
            _fixture(), project_root=ROOT, expected_source_sha="f" * 40
        )
        == []
    )


def test_split_validator_rejects_cross_split_derived_fingerprint():
    payload = copy.deepcopy(_fixture())
    payload["units"][2]["derived_fingerprint"] = payload["units"][0][
        "derived_fingerprint"
    ]
    payload["overlaps"] = _overlaps(payload["units"])
    errors = validate_evaluation_split_manifest(
        _resign(payload), project_root=ROOT, expected_source_sha="f" * 40
    )
    assert "evaluation split overlap detected: derived_fingerprint" in errors


def test_split_validator_rejects_state_test_outside_final():
    payload = copy.deepcopy(_fixture())
    payload["units"][1]["split"] = "validation"
    payload["overlaps"] = _overlaps(payload["units"])
    errors = validate_evaluation_split_manifest(
        _resign(payload), project_root=ROOT, expected_source_sha="f" * 40
    )
    assert "STATE-Bench official test row is not final-only" in errors


def test_split_validator_rejects_memops_subject_crossing_splits():
    payload = copy.deepcopy(_fixture())
    duplicate = copy.deepcopy(payload["units"][2])
    duplicate["unit_id"] = "memops:b"
    duplicate["split"] = "final"
    duplicate["conversation_fingerprint"] = "d" * 64
    duplicate["trajectory_fingerprint"] = "e" * 64
    duplicate["derived_fingerprint"] = "4" * 64
    payload["units"].append(duplicate)
    payload["overlaps"] = _overlaps(payload["units"])
    errors = validate_evaluation_split_manifest(
        _resign(payload), project_root=ROOT, expected_source_sha="f" * 40
    )
    assert "MemOps subject trajectory crosses splits" in errors


def test_split_validator_rejects_tampered_integrity():
    payload = _fixture()
    payload["units"][0]["split"] = "validation"
    errors = validate_evaluation_split_manifest(
        payload, project_root=ROOT, expected_source_sha="f" * 40
    )
    assert "artifact payload digest mismatch" in errors
