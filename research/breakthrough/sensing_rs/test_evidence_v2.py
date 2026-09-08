"""Read-only reproduction of native-readout evidence, including its rejection."""

import json

import numpy as np

from experiment import HERE, grid, phases, sha
from readout_v2 import curvature_bound, interpolation_lower, native_statistics, protocol_members


RUN = HERE / "runs" / "readout_v2"


def read(path):
    return json.loads(path.read_text(encoding="utf-8"))


def options(cfg, error):
    return dict(eta=cfg["eta"], tp=cfg["tp"],
                amplitude_error=error[0], qubit_detuning=error[1]*np.pi/cfg["tp"],
                exponent=cfg["noise"]["primary_depolarizing_exponent"],
                p_bright=cfg["readout"]["p_bright"], p_dark=cfg["readout"]["p_dark"],
                overhead=cfg["overhead"])


def test_v2_exact_source_and_complete_artifact_manifest():
    manifest = read(RUN / "checksums.json")
    assert set(manifest) == {p.name for p in RUN.iterdir() if p.is_file()} - {"checksums.json"}
    for name, expected in manifest.items():
        assert sha(RUN / name) == expected, name
    provenance = read(RUN / "provenance.json")
    assert provenance["source_commit"] == "66550207872d662e059d6b43bf29b0c4ee6c9edc"
    for name, expected in provenance["sources"].items():
        assert sha(HERE / name) == expected, name
    assert provenance["old_roots_sha256"] == sha(HERE / "runs" / "off_grid_v1" / "results.json")
    assert provenance["independent_investigator"] is False
    assert provenance["hardware_calls"] == 0
    assert read(RUN / "schedule.json")["simulation_only"] is True


def test_v2_screen_complete_and_equal_shot_budget():
    cfg, result = read(HERE / "protocol_v2.json"), read(RUN / "results.json")
    expected_errors = np.array([(a,q) for a in cfg["amplitude_errors"]
                                for q in cfg["qubit_detuning_over_omega"]])
    assert result["points_per_protocol"] == 9225
    assert [s["protocol"] for s in result["screen"]] == cfg["protocols"]
    random = cfg["randomized_baseline"]
    for summary in result["screen"]:
        name = summary["protocol"]
        members = protocol_members(name, cfg["n"], random["seeds"], random["seed_base"])
        with np.load(RUN / f"screen_{name}.npz", allow_pickle=False) as arrays:
            assert np.array_equal(arrays["cycles"], grid(cfg["grid"]))
            assert np.array_equal(arrays["errors"], expected_errors)
            assert np.array_equal(arrays["phase_realizations"], members)
            member_rates = arrays["member_fi_rates"]
            assert member_rates.shape == (len(members), 9, 1025)
            assert summary["phase_realizations"] == len(members)
            if "click_probability" in arrays:
                p, dp = arrays["click_probability"], arrays["dp_db"]
                assert p.shape == dp.shape == (9, 1025, 6)
                assert np.all((p >= cfg["readout"]["p_dark"]) & (p <= cfg["readout"]["p_bright"]))
                rate = np.mean(dp**2/(p*(1-p)), axis=-1)/(cfg["n"]+cfg["tp"]+cfg["overhead"])
                np.testing.assert_allclose(member_rates[0], rate, rtol=1e-12, atol=1e-15)
            rate = member_rates.mean(axis=0)  # 32 realizations share ONE budget.
            np.testing.assert_allclose(arrays["fi_rate"], rate, rtol=1e-12, atol=1e-15)
            assert np.isclose(rate.min(), summary["minimum_rate"], rtol=1e-12, atol=1e-15)
            assert np.isclose(np.median(rate), summary["median_rate"], rtol=1e-12, atol=1e-15)
            worst = np.unravel_index(np.argmin(rate), rate.shape)
            assert summary["worst_point"]["spectator_cycles"] == arrays["cycles"][worst[1]]
            if len(members) > 1:
                se = member_rates[:, worst[0], worst[1]].std(ddof=1)/np.sqrt(len(members))
                assert np.isclose(se, summary["seed_standard_error_at_worst_point"], rtol=1e-12)


def test_v2_conditional_cover_has_no_holes_and_endpoints_replay():
    cfg, result = read(HERE / "protocol_v2.json"), read(RUN / "results.json")
    cfg_audit, detector = cfg["continuous_audit"], cfg["readout"]
    curvature = curvature_bound(cfg["n"], cfg["tp"], cfg["noise"]["primary_depolarizing_exponent"],
                                detector["p_bright"], detector["p_dark"])
    assert len(result["continuous_covers"]) == 9
    accepted_total = 0
    for index, summary in enumerate(result["continuous_covers"]):
        with np.load(RUN / f"cover_{index}.npz", allow_pickle=False) as arrays:
            cells, unresolved = arrays["accepted_intervals"], arrays["unresolved_intervals"]
            assert unresolved.shape == (0, 2)
            assert cells.shape == (summary["accepted_intervals"], 3)
            assert cells[0, 0] == cfg["grid"]["start"] and cells[-1, 1] == cfg["grid"]["stop"]
            assert np.all(cells[:, 1] > cells[:, 0])
            assert np.array_equal(cells[:-1, 1], cells[1:, 0])
            assert np.all(cells[:, 2] > 0)
            endpoints = np.r_[cells[:, 0], cells[-1, 1]]
            assert len(endpoints) == summary["evaluated_points"]
            assert len(endpoints) <= cfg_audit["maximum_points_per_error_pair"]
            dp = native_statistics(phases("RS_prefix", cfg["n"]), endpoints,
                                   **options(cfg, summary["errors"]))[2]
            lower = interpolation_lower(dp[:-1], dp[1:], np.diff(endpoints), curvature,
                                        cfg_audit["endpoint_slope_vector_error_allowance"])
            np.testing.assert_allclose(cells[:, 2], lower, rtol=1e-9, atol=1e-11)
            bound = lower.min()**2/(6*detector["p_bright"]*(1-detector["p_bright"])
                                   *(cfg["n"]+cfg["tp"]+cfg["overhead"]))
            assert np.isclose(bound, summary["conditional_minimum_fi_rate"], rtol=1e-8, atol=1e-14)
            assert summary["conditional_cover_complete"] is True
            assert summary["interval_arithmetic_certified"] is False
            accepted_total += len(cells)
    assert accepted_total == 18443


def test_v2_blind_spot_repair_does_not_override_failed_advantage_gate():
    cfg, result = read(HERE / "protocol_v2.json"), read(RUN / "results.json")
    old = read(HERE / "runs" / "off_grid_v1" / "results.json")["roots"]
    assert len(old) == len(result["old_blind_spots"]) == 8
    ideal = native_statistics(phases("CP", cfg["n"]), [0.], **{**options(cfg, [0.,0.]), "eta":0.})[0][0]
    assert np.isclose(ideal, result["ideal_cp_rate_same_noise_and_detector"], rtol=1e-12)
    for previous, row in zip(old, result["old_blind_spots"]):
        assert row["cycles"] == previous["root_approximation"]["cycles"]
        assert row["errors"] == previous["error_setting"]
        rate, p, dp = native_statistics(phases("RS_prefix", cfg["n"]), [row["cycles"]],
                                       **options(cfg, row["errors"]))
        np.testing.assert_allclose(p[0], row["click_probabilities"], rtol=1e-11, atol=1e-12)
        np.testing.assert_allclose(dp[0], row["slopes"], rtol=1e-9, atol=1e-11)
        assert np.isclose(rate[0]/ideal, row["fraction_of_ideal_rate"], rtol=1e-10)
        assert rate[0]/ideal >= .01
    assert result["old_blind_spot_gate_pass"] is True
    assert result["conditional_continuous_covers_complete"] is True
    scores = {s["protocol"]:s for s in result["screen"]}
    baselines = [s for n,s in scores.items() if n not in ("RS_prefix", "raw_RS")]
    best_min, best_med = max(baselines, key=lambda s:s["minimum_rate"]), max(baselines, key=lambda s:s["median_rate"])
    ratios = (scores["RS_prefix"]["minimum_rate"]/best_min["minimum_rate"],
              scores["RS_prefix"]["median_rate"]/best_med["median_rate"])
    assert best_min["protocol"] == result["best_minimum_baseline"] == "RXY8"
    assert best_med["protocol"] == result["best_median_baseline"] == "XY8"
    np.testing.assert_allclose(ratios, [result["candidate_to_best_minimum_ratio"],
                                      result["candidate_to_best_median_ratio"]], rtol=1e-12)
    assert not (ratios[0] >= 2 and ratios[1] >= .9)
    assert result["advantage_gate_pass"] is False
    stress = cfg["dephasing_stress"]
    for row in result["dephasing_stress"]:
        with np.load(RUN / f"dephasing_{row['protocol']}.npz", allow_pickle=False) as arrays:
            assert arrays["cases"].shape == (29, 3)
            assert np.array_equal(arrays["slices"], stress["pulse_slices"])
            assert arrays["rates"].shape == (4, 29)
            np.testing.assert_allclose(arrays["rates"][-1], arrays["rates"][-2],
                                       rtol=stress["convergence_relative_tolerance"],
                                       atol=stress["convergence_absolute_tolerance"])
            assert np.isclose(arrays["rates"][-1].min(), row["minimum_rate"], rtol=1e-12)
            assert row["converged"] is True
    assert result["decision"] == "READOUT_UPGRADE_NO_QUALIFYING_ADVANTAGE"
    assert result["novelty"] == "UNKNOWN"
    assert result["hardware_validation"] == result["mass_enterprise_validation"] == "NOT_TESTED"
    assert result["mission_complete"] is False
