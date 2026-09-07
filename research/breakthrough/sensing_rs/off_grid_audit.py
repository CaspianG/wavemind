"""Post-screen diagnostic: preserve and expose missed readout blind spots."""

import argparse
import json
from pathlib import Path

import numpy as np

from experiment import (HERE, PLUS_X, PLUS_Y, finite_signal, fisher, git,
                        json_write, phases, propagate, sha)


def state_qfi(u, du):
    psi, dpsi = u @ PLUS_X, du @ PLUS_X
    return 4*(np.sum(np.abs(dpsi)**2, axis=-1)
              - np.abs(np.sum(psi.conj()*dpsi, axis=-1))**2)


def check_evidence(source):
    manifest = json.loads((source/"checksums.json").read_text(encoding="utf-8"))
    for name, expected in manifest.items():
        if sha(source/name) != expected:
            raise ValueError(f"Evidence checksum mismatch: {name}")
    provenance = json.loads((source/"provenance.json").read_text(encoding="utf-8"))
    for name, expected in provenance["source_files"].items():
        if sha(HERE/name) != expected:
            raise ValueError(f"Frozen source has changed: {name}")
    return provenance


def run(source: Path, output: Path):
    if output.exists():
        raise FileExistsError("Never overwrite an evidence directory")
    if git("status", "--porcelain", "--untracked-files=no"):
        raise RuntimeError("Commit the follow-up protocol and script first")
    provenance = check_evidence(source)
    cfg = json.loads((HERE/"protocol.json").read_text(encoding="utf-8"))
    eng = cfg["engineering_screen"]
    phase = phases("RS_prefix", eng["n"])
    archive = np.load(source/"engineering_RS_prefix.npz", allow_pickle=False)
    cycles, errors, slopes = archive["detuning_cycles"], archive["errors"], archive["dp_db"]
    intervals = np.argwhere(slopes[:, 1:]*slopes[:, :-1] < 0)
    roots = []

    def point(cycle, error, name="RS_prefix"):
        u, du = propagate(phases(name, eng["n"]), np.array([2*np.pi*cycle]), eng["eta"],
                          amplitude_error=float(error[0]),
                          qubit_detuning=float(error[1])*np.pi/cfg["pulse_duration"],
                          derivative="signal")
        fi, p, dp = fisher(u, du)
        return {"cycles": float(cycle), "p": float(p[0]), "dp_db": float(dp[0]),
                "fi_rate": float(fi[0]/(eng["n"]+eng["overhead"])),
                "state_qfi": float(state_qfi(u, du)[0]),
                "worst_input_leakage": float(np.sum(np.abs(u[0,2,:2])**2))}

    for error_index, grid_index in intervals:
        error = errors[error_index]
        left, right = float(cycles[grid_index]), float(cycles[grid_index+1])
        original = [point(left, error), point(right, error)]
        left_slope = original[0]["dp_db"]
        for _ in range(32):
            mid = (left+right)/2
            mid_slope = point(mid, error)["dp_db"]
            if left_slope*mid_slope <= 0:
                right = mid
            else:
                left, left_slope = mid, mid_slope
        roots.append({"error_setting": error.tolist(), "original_bracket": original,
                      "localized_bracket": [left, right], "root_approximation": point((left+right)/2, error)})

    endpoint_checks, comparison = [], []
    if roots:
        first = roots[0]
        error = np.array(first["error_setting"])
        delta = 2*np.pi*np.array([p["cycles"] for p in first["original_bracket"]])
        exact_slopes = np.array([p["dp_db"] for p in first["original_bracket"]])
        step = 1e-5/eng["n"]
        for slices in (128, 256):
            plus = finite_signal(phase, delta, eng["eta"], step, slices,
                                 amplitude_error=error[0], qubit_detuning=error[1]*np.pi/cfg["pulse_duration"])
            minus = finite_signal(phase, delta, eng["eta"], -step, slices,
                                  amplitude_error=error[0], qubit_detuning=error[1]*np.pi/cfg["pulse_duration"])
            p_plus = np.abs((plus @ PLUS_X) @ PLUS_Y.conj())**2
            p_minus = np.abs((minus @ PLUS_X) @ PLUS_Y.conj())**2
            numerical = (p_plus-p_minus)/(2*step)
            endpoint_checks.append({"slices": slices, "finite_signal_slopes": numerical.tolist(),
                                    "exact_slopes": exact_slopes.tolist(),
                                    "max_scaled_error": float(np.max(np.abs(numerical-exact_slopes)/(1+np.abs(exact_slopes)))),
                                    "opposite_signs": bool(numerical[0]*numerical[1] < 0)})
        for name in ["RS_prefix"]+cfg["control_protocols"]:
            comparison.append({"protocol": name, **point(first["root_approximation"]["cycles"], error, name)})
    confirmed = (bool(roots) and endpoint_checks[-1]["opposite_signs"]
                 and endpoint_checks[-1]["max_scaled_error"] < 3e-6)
    result = {"source_commit": git("rev-parse", "HEAD"), "original_source_commit": provenance["source_commit"],
              "original_checksums_sha256": sha(source/"checksums.json"),
              "followup_protocol_sha256": sha(HERE/"OFF_GRID_AUDIT.md"),
              "followup_script_sha256": sha(Path(__file__)),
              "posthoc_diagnostic": True, "all_sign_change_intervals": len(roots), "roots": roots,
              "finite_signal_endpoint_checks": endpoint_checks, "first_root_comparison": comparison,
              "blind_spot_confirmed_numerically": confirmed,
              "interval_arithmetic_proof": False,
              "decision": "V1_READOUT_NOT_UNIFORMLY_SENSITIVE" if confirmed else "UNRESOLVED",
              "original_grid_pass_preserved": True, "leading_order_leakage_bound_refuted": False,
              "all_readouts_refuted": False, "novelty_gate": "UNKNOWN",
              "physical_gate": "NOT_TESTED", "mass_and_enterprise_gate": "NOT_TESTED",
              "mission_complete": False}
    output.mkdir(parents=True)
    json_write(output/"results.json", result)
    json_write(output/"checksums.json", {"results.json": sha(output/"results.json")})
    print(json.dumps(result, indent=2), flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=HERE/"runs"/"v1")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    run(args.source.resolve(), args.output.resolve())
