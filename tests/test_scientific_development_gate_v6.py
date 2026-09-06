from __future__ import annotations

import json
from pathlib import Path

from wavemind.evidence import validate_artifact_integrity


ROOT = Path(__file__).resolve().parents[1]
RESULT = ROOT / "benchmarks" / "scientific_development_gate_v6_results.json"


def test_v6_checked_development_gate_is_exact_sha_and_reproducible():
    payload = json.loads(RESULT.read_text(encoding="utf-8"))

    assert validate_artifact_integrity(payload) == []
    assert payload["status"] == "pass"
    assert payload["development_gate_passed"] is True
    assert payload["advance_to_validation"] is True
    assert payload["admission_eligible"] is False
    assert payload["candidate_source_sha"] == (
        "a8240fe6bd9a79aec3d524b1cbbbdb4b907f8d97"
    )
    assert payload["positive_uplift_lcb_families"] == 2
    for family in payload["families"].values():
        assert family["passed"] is True
        assert family["reproducible_runs"] == 3
        assert all(run["positive_uplift_lcb"] for run in family["runs"])
        assert all(run["negative_effect_count"] == 0 for run in family["runs"])
        assert all(run["intervention_coverage"] == 1.0 for run in family["runs"])
    assert payload["longmemeval_v2_full_run_executed"] is False
