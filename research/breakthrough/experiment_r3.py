"""Exact two-world quantum counterexample, with a matched classical control."""

import argparse
import json
import time
from pathlib import Path

import numpy as np

from experiment_r1 import HERE, digest, dump, source_identity


def z_unitary(angle):
    return np.diag([np.exp(-.5j * angle), np.exp(.5j * angle)])


def probability(state, observable):
    return float((1. + np.vdot(state, observable @ state).real) / 2.)


def run(output):
    protocol = json.loads((HERE / "protocol_r3.json").read_text())
    receipt = {"source_sha": source_identity(), "started_unix_ns": time.time_ns(),
               "hashes": {f: digest(HERE / f) for f in ["protocol_r3.json", "experiment_r3.py",
                                                       "experiment_r1.py"]},
               "evidence_class": "exact_analytic_model_counterexample_not_physical_data",
               "external_data_used": False, "paid_calls": 0, "longmemeval_runs": 0}
    output.mkdir(parents=True, exist_ok=False)
    dump(output / "receipt_start.json", receipt)
    plus = np.array([1., 1.], dtype=complex) / np.sqrt(2.)
    x = np.array([[0, 1], [1, 0]], dtype=complex)
    y = np.array([[0, -1j], [1j, 0]], dtype=complex)
    history, controls, probes = [], [], []
    start = time.perf_counter()
    try:
        lo, hi, count = protocol["history_times"]
        for t in np.linspace(lo, hi, count):
            probabilities = [probability(z_unitary(sign * t) @ plus, x) for sign in [-1, 1]]
            history.append({"time": float(t), "negative_world_p_x_plus": probabilities[0],
                            "positive_world_p_x_plus": probabilities[1]})
            if abs(probabilities[0] - probabilities[1]) > 1e-12:
                raise AssertionError("X history distinguishes the signs")
        for unit in protocol["target_angles_pi_units"]:
            theta = unit * np.pi
            for sign in [-1, 1]:
                state = z_unitary(sign * theta) @ plus
                for action in protocol["control_actions"]:
                    corrected = z_unitary(-action * theta) @ state
                    fidelity = float(abs(np.vdot(plus, corrected)) ** 2)
                    predicted = 1. if sign == action else float(np.cos(theta) ** 2)
                    if abs(fidelity - predicted) > 1e-12:
                        raise AssertionError("control fidelity disagrees with analytic formula")
                    controls.append({"theta_pi_units": unit, "world_sign": sign,
                                     "control_sign": action, "fidelity": fidelity,
                                     "predicted_fidelity": predicted})
        for error in protocol["readout_error_rates"]:
            correct = []
            for sign in [-1, 1]:
                p_plus = probability(z_unitary(sign * np.pi / 2) @ plus, y)
                observed = error + (1. - 2. * error) * p_plus
                success = observed if sign == 1 else 1. - observed
                correct.append(success)
                probes.append({"readout_error": error, "world_sign": sign,
                               "p_y_plus": p_plus, "noisy_p_y_plus": observed,
                               "correct_sign_probability": success})
            if abs(float(np.mean(correct)) - (1. - error)) > 1e-12:
                raise AssertionError("fresh diagnostic disagrees with known channel")
        # Any randomized history-only rule chooses + with some q. Since
        # histories have identical laws, the same q applies in both worlds:
        # 0.5*q + 0.5*(1-q) = 0.5. Enumerated q are sanity checks of that identity.
        randomized = [{"choose_positive_probability": float(q),
                       "mean_success": float(.5 * q + .5 * (1. - q))}
                      for q in np.linspace(0., 1., 11)]
        raw = {"history": history, "controls": controls, "fresh_probes": probes,
               "randomized_rules": randomized,
               "classical_control": {"hidden_bit_prior": [.5, .5],
                                     "history_only_success": .5,
                                     "diagnostic_success": [1. - e for e in protocol["readout_error_rates"]]}}
        dump(output / "raw.json", raw)
        elapsed = time.perf_counter() - start
        if elapsed > protocol["resources"]["max_seconds"]:
            raise TimeoutError("registered time bound")
        result = {**receipt, "status": "scope_alone_universal_claim_refuted",
                  "history_max_probability_difference": max(abs(r["negative_world_p_x_plus"]
                      - r["positive_world_p_x_plus"]) for r in history),
                  "history_only_optimal_mean_success": .5,
                  "fresh_probe_success": [1. - e for e in protocol["readout_error_rates"]],
                  "new_physics": False, "external_validation": False,
                  "scientific_breakthrough_gate": False, "mass_indispensability_gate": False,
                  "raw_sha256": digest(output / "raw.json"), "elapsed_seconds": elapsed,
                  "boundary": "Rejects universal scope-only transfer. Known identifiability obstruction, not a new theorem or a claim of failure of all WaveMind memory."}
        dump(output / "result.json", result)
        print(json.dumps(result, indent=2))
    except Exception as error:
        dump(output / "failure.json", {**receipt, "status": "execution_failed", "error": repr(error)})
        raise


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    run(parser.parse_args().output.resolve())
