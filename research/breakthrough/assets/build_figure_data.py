"""Prepare auditable numerical inputs, not graphics; no style choice is implied."""

import argparse
import json
from pathlib import Path
import sys

import numpy as np


HERE = Path(__file__).resolve().parent
SCIENCE = HERE.parent / "sensing_rs"
sys.path.insert(0, str(SCIENCE))
from experiment import sha  # noqa: E402
from pulse_v3 import waveform  # noqa: E402
from verify_v2_replay import manifest_check, read  # noqa: E402


def build():
    run = SCIENCE / "runs" / "pulse_v3"
    manifest_check(run)
    result, cfg = read(run / "results.json"), read(SCIENCE / "protocol_v3.json")
    rows = {row["id"]: row for row in result["screen"]}
    groups = []
    for shape in cfg["waveforms"]:
        candidate = rows[f"{shape}/RS_prefix"]
        baselines = [row for row in rows.values()
                     if row["waveform"] == shape and row["sequence"] not in ("RS_prefix", "raw_RS")]
        best = max(baselines, key=lambda row: row["minimum_rate"])
        for row in (candidate, best):
            with np.load(run / f"screen_{shape}_{row['sequence']}.npz", allow_pickle=False) as data:
                assert data["fi_rate"].shape == (9, 1024)
                assert np.isclose(data["fi_rate"].min(), row["minimum_rate"], rtol=1e-12)
        groups.append({"waveform": shape, "candidate_id": candidate["id"],
                       "candidate_minimum": candidate["minimum_rate"], "baseline_id": best["id"],
                       "baseline_minimum": best["minimum_rate"],
                       "baseline_seed_standard_error_at_its_worst_point": best.get("seed_standard_error_at_worst_point")})
    t = np.linspace(0., .25, 257)
    x, y, d = waveform("DRAG3", t)
    rectangle, drag = rows["RECT/RS_prefix"], rows[cfg["candidate"]]
    resources = {r["waveform"]: r for r in result["resources"]}
    return {
        "schema": "sensing-research-figures/v1",
        "status": "numerical_inputs_only_not_a_rendered_chart",
        "source_paths_relative_to_research": {
            "result": "sensing_rs/runs/pulse_v3/results.json", "protocol": "sensing_rs/protocol_v3.json",
            "waveform": "sensing_rs/pulse_v3.py", "contract": "assets/FIGURE_CONTRACT.md"},
        "sha256": {"result": sha(run / "results.json"), "run_manifest": sha(run / "checksums.json"),
                   "protocol": sha(SCIENCE / "protocol_v3.json"), "waveform": sha(SCIENCE / "pulse_v3.py"),
                   "generator": sha(Path(__file__))},
        "frozen_experiment_source_commit": read(run / "provenance.json")["source_commit"],
        "metric": {"name": "minimum Fisher information per total time", "units": "normalized model units",
                   "points_per_combination": result["points_per_combination"],
                   "total_time": 74.25, "readout_settings": 6,
                   "minimization": "over 9 error pairs and 1024 new detuning midpoints",
                   "randomized_budget": "32 retained phase realizations share one budget; mean FI, not sum",
                   "continuous_domain_certified": False, "hardware_measured": False},
        "pulse_comparison": groups,
        "waveform": {"id": "DRAG3", "time_unit": "tau", "amplitude_unit": "inverse tau",
                     "quantity": "commanded controls, not measured traces", "time": t.tolist(),
                     "X": x.tolist(), "Y": y.tolist(), "d": d.tolist()},
        "resources": result["resources"],
        "claims": {"RS_minimum_gain_DRAG3_over_RECT_on_same_v3_grid": drag["minimum_rate"] / rectangle["minimum_rate"],
                   "RF_energy_increase_percent_DRAG3_over_RECT": 100 * (resources["DRAG3"]["nominal_rf_energy"] / resources["RECT"]["nominal_rf_energy"] - 1),
                   "candidate_to_best_minimum_ratio": result["candidate_to_best_minimum_ratio"],
                   "advantage_threshold_minimum_ratio": 2.0,
                   "advantage_gate_pass": result["advantage_gate_pass"], "mission_complete": False},
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="Compare with the checked-in inputs without writing")
    args = parser.parse_args()
    expected = build()
    output = HERE / "figure-data.json"
    if args.check:
        assert read(output) == expected, "Figure inputs drifted from their frozen evidence or generator"
        print("FIGURE_DATA_MATCH: 8 bars, 3 analytic control traces; no graphics rendered")
    else:
        output.write_text(json.dumps(expected, indent=2, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n")
        print(output)
