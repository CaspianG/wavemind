"""Read-only checks of the frozen pulse-compensation run, including rejection."""

import json

import numpy as np

from experiment import HERE, phases, sha
from pulse_v3 import local_response, readout_response, resource_record, sensing_response
from readout_v2 import protocol_members
from verify_v2_replay import compare_json, manifest_check


RUN = HERE / "runs" / "pulse_v3"


def read(path):
    return json.loads(path.read_text(encoding="utf-8"))


def test_v3_frozen_sources_and_complete_manifest():
    manifest_check(RUN)
    provenance = read(RUN / "provenance.json")
    assert provenance["source_commit"] == "cd73cd5028bfa6820039e96c29c1f00e000b4aa6"
    assert provenance["v2_results_sha256"] == sha(HERE / "runs" / "readout_v2" / "results.json")
    assert provenance["independent_investigator"] is False
    assert provenance["hardware_calls"] == provenance["paid_calls"] == 0
    assert len(list(RUN.glob("*.npz"))) == 40


def test_v3_all_combinations_and_shared_randomized_shot_budget():
    cfg, result = read(HERE / "protocol_v3.json"), read(RUN / "results.json")
    expected_ids = [f"{w}/{s}" for w in cfg["waveforms"] for s in cfg["protocols"]]
    assert [r["id"] for r in result["screen"]] == expected_ids
    assert result["points_per_combination"] == 9216 and result["combinations"] == 36
    g = cfg["grid"]
    cycles = g["start"] + (np.arange(g["cells"]) + .5) * (g["stop"] - g["start"]) / g["cells"]
    old_cycles = np.linspace(12., 16., 1025)
    assert np.intersect1d(cycles, old_cycles).size == 0
    errors = np.array([(a, q) for a in cfg["amplitude_errors"]
                       for q in cfg["qubit_detuning_over_reference_omega"]])
    random = cfg["randomized_baseline"]
    for row in result["screen"]:
        members = protocol_members(row["sequence"], cfg["n"], random["seeds"], random["seed_base"])
        with np.load(RUN / f"screen_{row['waveform']}_{row['sequence']}.npz", allow_pickle=False) as data:
            assert np.array_equal(data["cycles"], cycles)
            assert np.array_equal(data["errors"], errors)
            assert np.array_equal(data["phase_members"], members)
            member_rates = data["member_fi_rate"]
            assert member_rates.shape == (len(members), 9, 1024)
            assert np.all(np.isfinite(member_rates)) and np.all(member_rates >= 0.)
            score = member_rates.mean(axis=0)  # Never sum 32 independent budgets.
            np.testing.assert_allclose(data["fi_rate"], score, rtol=1e-13, atol=1e-15)
            np.testing.assert_allclose([score.min(), np.median(score), score.max()],
                                       [row["minimum_rate"], row["median_rate"], row["maximum_rate"]], rtol=1e-12)
            worst = np.unravel_index(np.argmin(score), score.shape)
            assert row["worst_cycles"] == cycles[worst[1]]
            assert row["worst_errors"] == errors[worst[0]].tolist()
            leak = data["mean_worst_input_leakage"]
            assert leak.shape == (9, 1024) and np.all(np.isfinite(leak))
            assert np.all((leak >= 0.) & (leak <= 1. + 2e-9))
            assert np.isclose(leak.max(), row["max_mean_worst_input_leakage"], rtol=1e-12)
            assert row["phase_realizations"] == len(members)
            if len(members) > 1:
                se = member_rates[:, worst[0], worst[1]].std(ddof=1) / np.sqrt(len(members))
                assert np.isclose(se, row["seed_standard_error_at_worst_point"], rtol=1e-12)


def test_v3_resources_and_bounded_convergence():
    cfg, result = read(HERE / "protocol_v3.json"), read(RUN / "results.json")
    for recorded in result["resources"]:
        compare_json(recorded, resource_record(recorded["waveform"]))
        assert recorded["within_common_caps"] is True
    resources = {r["waveform"]: r for r in result["resources"]}
    assert resources["DRAG3"]["nominal_rf_energy"] > resources["RECT"]["nominal_rf_energy"]
    assert resources["DRAG3"]["nominal_longitudinal_peak"] > 0.
    conv = cfg["convergence"]
    assert len(result["convergence"]) == 4
    for row in result["convergence"]:
        wave, seq = row["id"].split("/")
        with np.load(RUN / f"convergence_{wave}_{seq}.npz", allow_pickle=False) as data:
            assert np.array_equal(data["cycles"], conv["cycles"])
            assert np.array_equal(data["slices"], conv["slices"])
            rates = data["rates"]
            assert rates.shape == (3, 8)
            np.testing.assert_allclose(rates[-1], rates[-2], rtol=conv["rtol"], atol=conv["atol"])
            relative = np.max(np.abs(rates[-1] - rates[-2]) / np.maximum(rates[-1], 1e-15))
            assert np.isclose(relative, row["max_relative_128_256_difference"], rtol=1e-12)
            assert row["pass"] is True
    assert result["numerical_gate_pass"] is True
    assert result["continuous_domain_certified"] is False


def test_v3_recompute_fixed_controls_and_native_observable():
    cfg = read(HERE / "protocol_v3.json")
    indices = [0, 313, 777, 1023]  # Fixed replay subset, not an additional search.
    args = dict(eta=cfg["eta"], amplitude_error=.02, qubit_detuning=-.02 * 4 * np.pi)
    for wave in cfg["waveforms"]:
        with np.load(RUN / f"screen_{wave}_RS_prefix.npz", allow_pickle=False) as data:
            cycles = data["cycles"][indices]
            e = np.flatnonzero(np.all(data["errors"] == [.02, -.02], axis=1))[0]
            local = local_response(wave, cycles, slices=cfg["integration_slices"], **args)
            u, du = sensing_response(wave, phases("RS_prefix", cfg["n"]), cycles, local, args["qubit_detuning"])
            rate, p, dp = readout_response(u, du, cycles, n=cfg["n"], **args)
            np.testing.assert_allclose(rate, data["fi_rate"][e, indices], rtol=1e-10, atol=1e-12)
            np.testing.assert_allclose(np.sum(np.abs(u[:, 2, :2])**2, axis=1),
                                       data["mean_worst_input_leakage"][e, indices], rtol=1e-10, atol=1e-12)
            assert p.shape == dp.shape == (4, 6)
            assert np.all((p >= .07) & (p <= .10))
            np.testing.assert_allclose(rate, np.mean(dp**2 / (p * (1-p)), axis=1) / 74.25, rtol=1e-12)


def test_v3_gain_does_not_override_failed_advantage_or_novelty():
    cfg, result = read(HERE / "protocol_v3.json"), read(RUN / "results.json")
    rows = {r["id"]: r for r in result["screen"]}
    candidate = rows[cfg["candidate"]]
    baselines = [r for r in rows.values() if r["sequence"] not in ("RS_prefix", "raw_RS")]
    assert len(baselines) == 28
    best_min = max(baselines, key=lambda r: r["minimum_rate"])
    best_med = max(baselines, key=lambda r: r["median_rate"])
    assert best_min["id"] == result["best_minimum_baseline"] == "DRAG3/RXY8"
    assert best_med["id"] == result["best_median_baseline"] == "DRAG3/XY16"
    ratio_min = candidate["minimum_rate"] / best_min["minimum_rate"]
    ratio_med = candidate["median_rate"] / best_med["median_rate"]
    np.testing.assert_allclose([ratio_min, ratio_med], [result["candidate_to_best_minimum_ratio"],
                               result["candidate_to_best_median_ratio"]], rtol=1e-12)
    assert ratio_min < 1.
    assert candidate["minimum_rate"] > 12 * rows["RECT/RS_prefix"]["minimum_rate"]
    assert result["advantage_gate_pass"] is False
    assert result["decision"] == "NO_QUALIFYING_COMBINATION_ADVANTAGE"
    assert result["novelty"] == "NOT_ADMITTED_KNOWN_CONTROL_FOUNDATION"
    assert result["hardware_validation"] == result["mass_enterprise_validation"] == "NOT_TESTED"
    assert result["mission_complete"] is False
