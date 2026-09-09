import json
import shutil

import pytest

from experiment_r1 import HERE
from verify_prior_art_applicability import verify


def test_frozen_source_interpretation_audit():
    assert verify()["local_assignments_replayed"] == 2592


def test_changed_result_count_is_rejected(tmp_path):
    for name in ("receipt_start.json", "result.json"):
        shutil.copyfile(HERE / "runs/prior_art_applicability" / name, tmp_path / name)
    path = tmp_path / "result.json"
    result = json.loads(path.read_text())
    result["source_examples"][0]["local_css_assignments"] += 1
    path.write_text(json.dumps(result), encoding="utf-8")
    with pytest.raises(AssertionError):
        verify(tmp_path)
