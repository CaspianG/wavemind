import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from benchmarks.validate_memory_os_admission_artifacts import (
    MemoryOSAdmissionArtifactError,
    validate_memory_os_admission_artifacts,
)


def test_checked_in_memory_os_admission_artifacts_are_valid():
    report = validate_memory_os_admission_artifacts()

    assert report["status"] == "pass"
    assert report["tested_commit"] == "23edad3b172fe0480e3b49640071c1930304c665"
    assert report["duration_seconds"] >= 21_600
    assert report["worker_cycles"] >= 500
    assert report["worker_count"] >= 2


def test_validation_rejects_evidence_that_differs_from_admission(tmp_path):
    root = Path(__file__).resolve().parents[1]
    (tmp_path / "benchmarks").mkdir()
    for filename in (
        "memory_os_remote_worker_soak_results.json",
        "memory_os_admission_results.json",
    ):
        shutil.copy2(root / "benchmarks" / filename, tmp_path / "benchmarks" / filename)
    evidence_path = tmp_path / "benchmarks" / "memory_os_remote_worker_soak_results.json"
    evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
    evidence["metrics"]["worker_cycles"] = 501
    evidence_path.write_text(json.dumps(evidence, indent=2) + "\n", encoding="utf-8")

    with pytest.raises(MemoryOSAdmissionArtifactError) as exc:
        validate_memory_os_admission_artifacts(tmp_path)

    assert "embedded admission evidence differs" in str(exc.value)


def test_validation_cli_passes_for_checked_in_artifacts():
    root = Path(__file__).resolve().parents[1]
    result = subprocess.run(
        [sys.executable, "benchmarks/validate_memory_os_admission_artifacts.py"],
        cwd=root,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=True,
    )

    assert json.loads(result.stdout)["status"] == "pass"
