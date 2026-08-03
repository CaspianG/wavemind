from __future__ import annotations

import json
from pathlib import Path

import pytest

from benchmarks.validate_verified_experience_artifacts import (
    ADMISSION_PATH,
    BENCHMARK_PATH,
    STATE_BENCH_PATH,
    VerifiedExperienceArtifactError,
    validate_verified_experience_artifacts,
)
from wavemind.verified_experience_admission import canonical_artifact_sha256


def test_checked_in_verified_experience_artifacts_are_consistent() -> None:
    report = validate_verified_experience_artifacts()

    assert report["status"] == "pass"
    assert report["errors"] == []


def test_validator_rejects_benchmark_bytes_changed_after_admission(
    tmp_path: Path,
) -> None:
    for path in (BENCHMARK_PATH, ADMISSION_PATH, STATE_BENCH_PATH):
        target = tmp_path / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(path.read_bytes())
    payload = json.loads((tmp_path / BENCHMARK_PATH).read_text(encoding="utf-8"))
    payload["metrics"]["task_success_uplift"] = 1.0
    (tmp_path / BENCHMARK_PATH).write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(VerifiedExperienceArtifactError, match="hash"):
        validate_verified_experience_artifacts(tmp_path)


def test_artifact_hash_is_independent_of_checkout_line_endings(tmp_path: Path) -> None:
    lf = tmp_path / "lf.json"
    crlf = tmp_path / "crlf.json"
    lf.write_bytes(b'{\n  "status": "pass"\n}\n')
    crlf.write_bytes(b'{\r\n  "status": "pass"\r\n}\r\n')

    assert canonical_artifact_sha256(lf) == canonical_artifact_sha256(crlf)
