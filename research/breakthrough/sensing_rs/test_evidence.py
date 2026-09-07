"""Read-only audits of the preserved positive and adverse sensing evidence."""

import json

import numpy as np
import pytest

from experiment import HERE, fisher, phases, propagate, sha
from off_grid_audit import check_evidence, state_qfi


def read(path):
    return json.loads(path.read_text(encoding="utf-8"))


def test_source_and_artifact_checksums():
    provenance = check_evidence(HERE/"runs"/"v1")
    assert provenance["source_commit"] == "ace8b6adee5ba26585c2db629a9cbbc368ccda08"
    audit = HERE/"runs"/"off_grid_v1"
    assert sha(audit/"results.json") == read(audit/"checksums.json")["results.json"]
    result = read(audit/"results.json")
    assert sha(HERE/"off_grid_audit.py") == result["followup_script_sha256"]
    assert sha(HERE/"OFF_GRID_AUDIT.md") == result["followup_protocol_sha256"]


def test_saved_engineering_metric_is_all_shot_and_complete():
    source = HERE/"runs"/"v1"
    result = read(source/"results.json")
    cfg = read(HERE/"protocol.json")["engineering_screen"]
    expected = cfg["detuning_cycles"]["count"] * len(cfg["amplitude_errors"]) * len(cfg["qubit_detuning_over_omega"])
    assert expected == result["engineering_parameter_points_per_protocol"] == 9225
    for summary in result["engineering"]:
        with np.load(source/f"engineering_{summary['protocol']}.npz", allow_pickle=False) as arrays:
            p, dp = arrays["probability"], arrays["dp_db"]
            recalculated = dp**2/(p*(1-p))/(cfg["n"]+cfg["overhead"])
            assert recalculated.size == expected
            assert np.allclose(arrays["fi_rate"], recalculated, rtol=1e-12, atol=1e-14)
            assert np.isclose(recalculated.min(), summary["minimum_fi_rate"], rtol=1e-12, atol=1e-16)
            assert np.isclose(np.median(recalculated), summary["median_fi_rate"], rtol=1e-12)


def test_all_saved_sign_changes_accounted_for_and_first_root_replayed():
    result = read(HERE/"runs"/"off_grid_v1"/"results.json")
    with np.load(HERE/"runs"/"v1"/"engineering_RS_prefix.npz", allow_pickle=False) as arrays:
        slopes = arrays["dp_db"]
        assert np.count_nonzero(slopes[:,1:]*slopes[:,:-1] < 0) == len(result["roots"]) == 8
    first = result["roots"][0]
    endpoints = first["original_bracket"]
    assert endpoints[0]["dp_db"]*endpoints[1]["dp_db"] < 0
    error = first["error_setting"]
    root = first["root_approximation"]
    u, du = propagate(phases("RS_prefix", 64), np.array([2*np.pi*root["cycles"]]), 1,
                      amplitude_error=error[0], qubit_detuning=error[1]*4*np.pi, derivative="signal")
    fi, p, dp = fisher(u, du)
    assert abs(dp[0]) < 1e-7
    assert 0 < p[0] < 1
    assert fi[0]/74 < 1e-12
    assert state_qfi(u,du)[0] > 600
    for row in result["first_root_comparison"]:
        assert row["fi_rate"]*74 <= row["state_qfi"]+1e-7
    assert result["decision"] == "V1_READOUT_NOT_UNIFORMLY_SENSITIVE"
    assert result["mission_complete"] is False


def test_tampered_evidence_rejected(tmp_path):
    # Deliberately wrong digest must fail before any provenance is trusted.
    payload = tmp_path/"payload.json"
    payload.write_text("{}", encoding="utf-8")
    (tmp_path/"checksums.json").write_text(json.dumps({"payload.json": "0"*64}), encoding="utf-8")
    with pytest.raises(ValueError, match="Evidence checksum mismatch"):
        check_evidence(tmp_path)
