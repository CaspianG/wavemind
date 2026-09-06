"""Post-run preservation checks; original frozen sources remain untouched."""

import json
import shutil

import pytest

from verify_workflow_bridge import verify
from workflow_bridge_control import HERE


def test_frozen_known_boundary_replays():
    assert verify()["ratios"]["phase_repetition"] == "14702/149"


@pytest.mark.parametrize("tamper", ["raw", "novelty"])
def test_tampered_boundary_evidence_rejected(tmp_path, tamper):
    directory = tmp_path / "copy"
    shutil.copytree(HERE / "runs/workflow_bridge", directory)
    if tamper == "raw":
        path = directory / "raw.jsonl"
        path.write_bytes(path.read_bytes() + b"\n")
    else:
        path = directory / "result.json"
        result = json.loads(path.read_text())
        result["novel_discovery"] = True
        path.write_text(json.dumps(result))
    with pytest.raises(AssertionError):
        verify(directory)
