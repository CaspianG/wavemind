"""Post-run tamper regression; never changes frozen R8 run files."""

import json
import shutil

import pytest

from experiment_r1 import HERE
from verify_r8 import verify


@pytest.mark.parametrize("mutation", ["raw_hash", "summary"])
def test_r8_verifier_rejects_tampered_evidence(tmp_path, mutation):
    directory = tmp_path / "copy"
    shutil.copytree(HERE / "runs/r8", directory)
    if mutation == "raw_hash":
        path = directory / "raw.jsonl"
        path.write_bytes(path.read_bytes() + b"\n")
    else:
        path = directory / "result.json"
        payload = json.loads(path.read_text())
        payload["summary"]["small_negative"] -= 1
        path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(AssertionError):
        verify(directory)
