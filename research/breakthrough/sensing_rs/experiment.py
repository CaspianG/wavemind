"""Frozen, local three-level signed-pulse experiment. NumPy is sufficient.

No optimizer, hardware, external service, postselection, or fitted parameters.
All frequencies in the Hamiltonian are angular frequencies; tabulated
detuning_cycles means Delta*tau/(2*pi). See THEORY.md for the exact model.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
import platform
import subprocess
import sys
import time

import numpy as np


HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
Z = np.diag([1.0, -1.0, 0.0]).astype(complex)
PLUS_X = np.array([1, 1, 0], complex) / np.sqrt(2)
PLUS_Y = np.array([1, 1j, 0], complex) / np.sqrt(2)


def rs(count: int) -> np.ndarray:
    return np.array([1 - 2 * ((j & (j >> 1)).bit_count() % 2)
                     for j in range(count)], dtype=int)


def phases(name: str, n: int) -> np.ndarray:
    if n < 4 or n & (n - 1):
        raise ValueError("N must be a power of two >= 4")
    if name in {"RS_prefix", "raw_RS"}:
        r = rs(n + 1)
        signs = r[:n] * r[1:] if name == "RS_prefix" else r[:n]
        return np.where(signs == 1, 0.0, np.pi)
    # Axis convention: H01=Omega*exp(-i*phi)/2; Y is phi=pi/2.
    patterns = {
        "CP": [0], "CPMG": [1], "APCP": [0, 2],
        "XY8": [0, 1, 0, 1, 1, 0, 1, 0],
        "XY16": [0, 1, 0, 1, 1, 0, 1, 0,
                 2, 3, 2, 3, 3, 2, 3, 2],
        "MLEV8": [0, 0, 2, 2, 2, 0, 0, 2],
    }
    pattern = np.array(patterns[name]) * np.pi / 2
    if n % len(pattern):
        raise ValueError("N must contain complete baseline blocks")
    return np.tile(pattern, n // len(pattern))


def integral_exp(x: np.ndarray, duration: float) -> np.ndarray:
    """Integral exp(i*x*t) from 0 to duration, including x=0 continuously."""
    x = np.asarray(x)
    return duration * np.exp(0.5j * x * duration) * np.sinc(x * duration / (2*np.pi))


def hamiltonian(delta: np.ndarray, phi: float, eta: float, omega: float,
                amplitude_error: float = 0.0, qubit_detuning: float = 0.0):
    delta = np.atleast_1d(delta).astype(float)
    h = np.zeros((len(delta), 3, 3), complex)
    h[:, 0, 0] = qubit_detuning / 2
    h[:, 1, 1] = -qubit_detuning / 2
    h[:, 2, 2] = delta
    drive = omega * (1 + amplitude_error) * np.exp(-1j * phi) / 2
    h[:, 0, 1] = drive
    h[:, 1, 0] = drive.conjugate()
    h[:, 1, 2] = eta * drive
    h[:, 2, 1] = eta * drive.conjugate()
    dh = np.zeros_like(h)
    dh[:, 1, 2] = drive
    dh[:, 2, 1] = drive.conjugate()
    return h, dh


def unitary(h: np.ndarray, duration: float) -> np.ndarray:
    values, vectors = np.linalg.eigh(h)
    return (vectors * np.exp(-1j * duration * values)[..., None, :]) @ vectors.conj().swapaxes(-1, -2)


def pulse_response(h: np.ndarray, perturbation: np.ndarray, duration: float,
                   frequency: float = 0.0, start: float = 0.0):
    """Exact first derivative for H+b*perturbation*cos(frequency*t).

    Uses the spectral integral, not a finite difference or time grid. The
    sinc formula remains defined at degenerate eigenvalues/resonances.
    """
    values, vectors = np.linalg.eigh(h)
    adj = vectors.conj().swapaxes(-1, -2)
    u = (vectors * np.exp(-1j * duration * values)[..., None, :]) @ adj
    differences = values[..., :, None] - values[..., None, :]
    kernels = 0.5 * (
        np.exp(1j * frequency * start) * integral_exp(differences + frequency, duration)
        + np.exp(-1j * frequency * start) * integral_exp(differences - frequency, duration)
    )
    insertion = vectors @ ((adj @ perturbation @ vectors) * kernels) @ adj
    return u, -1j * u @ insertion


def propagate(pulse_phases: np.ndarray, delta: np.ndarray, eta: float = 0.0,
              tp: float = 0.25, tau: float = 1.0, amplitude_error: float = 0.0,
              qubit_detuning: float = 0.0, derivative: str = "eta"):
    """Batch full propagator and derivative, including BOTH edge intervals."""
    if derivative not in {"eta", "signal"} or not 0 < tp <= tau:
        raise ValueError("invalid derivative or pulse duration")
    delta = np.atleast_1d(delta).astype(float)
    n = len(pulse_phases)
    omega, frequency = np.pi / tp, np.pi / tau
    g = (tau - tp) / 2
    u = np.broadcast_to(np.eye(3, dtype=complex), (len(delta), 3, 3)).copy()
    du = np.zeros_like(u)
    energies = np.column_stack((np.full(len(delta), qubit_detuning/2),
                                np.full(len(delta), -qubit_detuning/2), delta))

    def free(current_u, current_du, start, length):
        diagonal = np.exp(-1j * energies * length)
        d_diagonal = np.zeros_like(diagonal)
        if derivative == "signal":
            field_integral = (np.sin(frequency*(start+length)) - np.sin(frequency*start)) / frequency
            d_diagonal = (-1j * field_integral / 2) * np.diag(Z) * diagonal
        return diagonal[:, :, None] * current_u, (diagonal[:, :, None] * current_du
                                                    + d_diagonal[:, :, None] * current_u)

    u, du = free(u, du, 0, g)
    cache = {}
    for phi in np.unique(pulse_phases):
        h, dh = hamiltonian(delta, float(phi), eta, omega, amplitude_error, qubit_detuning)
        cache[float(phi)] = pulse_response(h, dh if derivative == "eta" else Z/2, tp,
                                          0 if derivative == "eta" else frequency,
                                          0 if derivative == "eta" else g)
    for j, phi in enumerate(pulse_phases):
        step, dstep = cache[float(phi)]
        # cos(pi*(j*tau+g+u)/tau)=(-1)^j*cos(pi*(g+u)/tau).
        multiplier = 1 if derivative == "eta" else (-1)**j
        du = step @ du + multiplier * dstep @ u
        u = step @ u
        start = g + j*tau + tp
        u, du = free(u, du, start, g if j == n-1 else tau-tp)
    return u, du


def analytic_leakage(n: int, delta: np.ndarray, tp: float = 0.25, tau: float = 1.0):
    """Closed first-order row and squared norm bound from THEORY.md."""
    phases("RS_prefix", n)  # validate N
    delta = np.atleast_1d(delta)
    omega = np.pi / tp
    plus = integral_exp(delta+omega/2, tp)
    minus = integral_exp(delta-omega/2, tp)
    ic, iss = (plus+minus)/2, (plus-minus)/(2j)
    z = np.exp(1j*delta*tau)
    w = -z*z
    p = np.polynomial.polynomial.polyval(w, rs(n//2))
    p_minus = np.polynomial.polynomial.polyval(-w, rs(n//2))
    shifted = (p-1+w**(n//2))/w
    row = np.column_stack((-1j*(iss*p+z*ic*shifted), (ic-z*iss)*p_minus))
    row *= (-1j*omega/2*np.exp(-1j*delta*(n*tau-(tau-tp)/2)))[:, None]
    a = omega/2*np.abs(iss-ic/z)
    c = omega*np.abs(ic)
    return row, (a*np.sqrt(n)+c)**2


def fisher(u: np.ndarray, du: np.ndarray):
    state, dstate = u @ PLUS_X, du @ PLUS_X
    amplitude = state @ PLUS_Y.conj()
    d_amplitude = dstate @ PLUS_Y.conj()
    p = np.abs(amplitude)**2
    dp = 2*np.real(amplitude.conj()*d_amplitude)
    variance = p*(1-p)
    if np.any(variance <= 1e-12):
        raise ArithmeticError("Singular binary readout; no arbitrary probability clipping allowed")
    return dp**2 / variance, p, dp


def finite_signal(pulse_phases, delta, eta, b, slices, tp=0.25, tau=1.0,
                  amplitude_error=0.0, qubit_detuning=0.0):
    """Independent midpoint-in-time check at finite signal, not primary solver."""
    delta = np.atleast_1d(delta)
    omega, frequency = np.pi/tp, np.pi/tau
    g = (tau-tp)/2
    energies = np.column_stack((np.full(len(delta), qubit_detuning/2),
                                np.full(len(delta), -qubit_detuning/2), delta))
    u = np.broadcast_to(np.eye(3, dtype=complex), (len(delta), 3, 3)).copy()
    t = 0.0

    def free(current, start, length):
        field_integral = b*(np.sin(frequency*(start+length))-np.sin(frequency*start))/frequency
        angles = energies*length + field_integral*np.diag(Z)/2
        return np.exp(-1j*angles)[:, :, None]*current

    u = free(u, t, g)
    t += g
    for j, phi in enumerate(pulse_phases):
        h, _ = hamiltonian(delta, phi, eta, omega, amplitude_error, qubit_detuning)
        dt = tp/slices
        for k in range(slices):
            hm = h + b*np.cos(frequency*(t+(k+0.5)*dt))*Z/2
            u = unitary(hm, dt) @ u
        t += tp
        length = g if j == len(pulse_phases)-1 else tau-tp
        u = free(u, t, length)
        t += length
    return u


def grid(spec):
    return np.linspace(spec["start"], spec["stop"], spec["count"])


def json_write(path: Path, value):
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False)+"\n", encoding="utf-8")


def sha(path: Path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def git(*args):
    # Exact, per-command trust exception for the verified local worktree only.
    return subprocess.check_output(["git", "-c", f"safe.directory={REPO.as_posix()}", *args],
                                   cwd=REPO, text=True).strip()


def run(output: Path):
    if output.exists():
        raise FileExistsError("Output must be a NEW directory; evidence is never overwritten")
    if git("status", "--porcelain", "--untracked-files=no"):
        raise RuntimeError("Commit tracked changes before the frozen experiment")
    for name in ("protocol.json", "THEORY.md", "experiment.py", "test_experiment.py"):
        git("ls-files", "--error-unmatch", str((HERE/name).relative_to(REPO)))
    cfg = json.loads((HERE/"protocol.json").read_text(encoding="utf-8"))
    output.mkdir(parents=True)
    start = time.perf_counter()
    source = {name: sha(HERE/name) for name in ("protocol.json", "THEORY.md", "experiment.py", "test_experiment.py")}
    json_write(output/"provenance.json", {"source_commit": git("rev-parse", "HEAD"),
               "source_files": source, "protocol_id": cfg["id"], "python": sys.version,
               "numpy": np.__version__, "platform": platform.platform(),
               "utc_started": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
               "independent_investigator": False, "hardware_calls": 0})

    mechanism = []
    cycles = grid(cfg["mechanism_detuning_cycles"])
    delta = 2*np.pi*cycles/cfg["tau"]
    for n in cfg["mechanism_pulse_counts"]:
        u, du = propagate(phases("RS_prefix", n), delta, tp=cfg["pulse_duration"])
        row, bound = analytic_leakage(n, delta, tp=cfg["pulse_duration"])
        error = np.linalg.norm(du[:, 2, :2]-row, axis=1)/(1+np.linalg.norm(row, axis=1))
        coefficient = np.sum(np.abs(du[:, 2, :2])**2, axis=1)
        violations = int(np.count_nonzero(coefficient > bound+cfg["bound_relative_tolerance"]*(1+bound)))
        mechanism.append({"n": n, "points": len(delta), "max_formula_scaled_error": float(error.max()),
                          "bound_violations": violations, "max_coefficient": float(coefficient.max()),
                          "max_coefficient_cycles": float(cycles[np.argmax(coefficient)]),
                          "unitarity_error": float(np.max(np.abs(u.conj().swapaxes(-1,-2)@u-np.eye(3))))})
        np.savez_compressed(output/f"mechanism_{n}.npz", detuning_cycles=cycles,
                            exact_derivative=du[:, 2, :2], analytic_derivative=row, bound=bound)
        print(json.dumps({"stage": "mechanism", **mechanism[-1]}), flush=True)
    mechanism_ok = all(row["max_formula_scaled_error"] <= cfg["formula_relative_tolerance"]
                       and row["bound_violations"] == 0 for row in mechanism)

    finite = cfg["finite_coupling_control"]
    fd = 2*np.pi*np.array(finite["detuning_cycles"])
    fu, _ = propagate(phases("RS_prefix", finite["n"]), fd, finite["eta"])
    first, bounds = analytic_leakage(finite["n"], fd)
    residual = np.linalg.norm(fu[:, 2, :2]-finite["eta"]*first, axis=1)
    x = finite["eta"]*finite["n"]*np.pi/2
    remainder = float(np.sinh(x)-x)
    finite_result = {"n": finite["n"], "eta": finite["eta"],
                     "max_leakage_row_remainder": float(residual.max()),
                     "dyson_remainder_bound": remainder,
                     "all_within_remainder": bool(np.all(residual <= remainder+1e-12))}
    json_write(output/"mechanism_summary.json", {"checks": mechanism, "mechanism_pass": mechanism_ok,
                                                "finite_coupling": finite_result})

    eng = cfg["engineering_screen"]
    names = ["RS_prefix"]+cfg["control_protocols"]
    ec = grid(eng["detuning_cycles"])
    ed = 2*np.pi*ec
    errors = [(a, q) for a in eng["amplitude_errors"] for q in eng["qubit_detuning_over_omega"]]
    metrics, raw = [], {}
    for name in names:
        phase = phases(name, eng["n"])
        information, leakage, probability, derivative = [], [], [], []
        for a, q in errors:
            u, du = propagate(phase, ed, eng["eta"], amplitude_error=a,
                              qubit_detuning=q*np.pi/cfg["pulse_duration"], derivative="signal")
            fi, p, dp = fisher(u, du)
            information.append(fi/(eng["n"]*cfg["tau"]+eng["overhead"]))
            leakage.append(np.sum(np.abs(u[:, 2, :2])**2, axis=1))
            probability.append(p)
            derivative.append(dp)
        information, leakage = np.array(information), np.array(leakage)
        ui, dui = propagate(phase, np.array([0.0]), derivative="signal")
        ideal = float(fisher(ui, dui)[0][0])
        worst = np.unravel_index(np.argmin(information), information.shape)
        best = np.unravel_index(np.argmax(information), information.shape)
        metrics.append({"protocol": name, "minimum_fi_rate": float(information[worst]),
                        "median_fi_rate": float(np.median(information)),
                        "maximum_fi_rate": float(information[best]),
                        "worst_case": {"amplitude_error": errors[worst[0]][0],
                                       "qubit_detuning_over_omega": errors[worst[0]][1],
                                       "spectator_detuning_cycles": float(ec[worst[1]])},
                        "maximum_worst_input_leakage": float(leakage.max()),
                        "ideal_fisher_information": ideal})
        raw[name] = information
        np.savez_compressed(output/f"engineering_{name}.npz", detuning_cycles=ec,
                            errors=np.array(errors), fi_rate=information, worst_input_leakage=leakage,
                            probability=np.array(probability), dp_db=np.array(derivative))
        print(json.dumps({"stage": "engineering", **metrics[-1]}), flush=True)

    candidate = metrics[0]
    # raw_RS is an ablation, not a established-baseline advantage claim.
    baselines = [r for r in metrics if r["protocol"] not in {"RS_prefix", "raw_RS"}]
    robust_best = max(baselines, key=lambda r: r["minimum_fi_rate"])
    ratio = candidate["minimum_fi_rate"]/robust_best["minimum_fi_rate"]
    cp = next(r for r in metrics if r["protocol"] == "CP")
    ideal_ratio = candidate["ideal_fisher_information"]/cp["ideal_fisher_information"]
    screen_ok = ratio >= 2 and ideal_ratio >= 0.95
    stress = cfg["near_resonance_stress"]
    sc = grid(stress)
    stress_results = []
    for name in names:
        u, du = propagate(phases(name, stress["n"]), 2*np.pi*sc, stress["eta"], derivative="signal")
        fi, p, dp = fisher(u, du)
        stress_results.append({"protocol": name, "minimum_fisher_information": float(fi.min()),
                               "maximum_worst_input_leakage": float(np.sum(np.abs(u[:, 2, :2])**2, axis=1).max())})
        np.savez_compressed(output/f"stress_{name}.npz", detuning_cycles=sc,
                            fisher_information=fi, probability=p, dp_db=dp)

    result = {"protocol_id": cfg["id"], "mechanism_pass": mechanism_ok,
              "finite_coupling": finite_result, "engineering": metrics,
              "engineering_parameter_points_per_protocol": len(ec)*len(errors),
              "best_baseline_by_minimum_rate": robust_best["protocol"],
              "candidate_to_best_baseline_minimum_rate_ratio": ratio,
              "candidate_to_cp_ideal_fi_ratio": ideal_ratio,
              "engineering_screen_pass": screen_ok, "near_resonance_stress": stress_results,
              "verdict": ("REFUTED_MECHANISM" if not mechanism_ok else
                          "PROVISIONAL_LOCAL_CANDIDATE_ONLY" if screen_ok else
                          "LIMITED_THEORETICAL_RESULT_NOT_USEFUL_SENSOR_ADMITTED"),
              "novelty_gate": "UNKNOWN", "physical_gate": "NOT_TESTED",
              "mass_and_enterprise_gate": "NOT_TESTED", "mission_complete": False,
              "seconds": time.perf_counter()-start}
    json_write(output/"results.json", result)
    json_write(output/"checksums.json", {p.name: sha(p) for p in sorted(output.iterdir()) if p.is_file()})
    print(json.dumps({k:v for k,v in result.items() if k not in {"engineering", "near_resonance_stress"}}, indent=2), flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    run(parser.parse_args().output.resolve())
