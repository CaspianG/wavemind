"""Offline H4 falsifier; generated Born-rule evidence, never external admission."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import platform
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
AXES = {"x": np.array([1., 0., 0.]), "y": np.array([0., 1., 0.]),
        "z": np.array([0., 0., 1.])}
FAMILIES = {"x_rotation": AXES["x"], "z_rotation": AXES["z"],
            "tilted_rotation": np.array([1., 0., 1.]) / np.sqrt(2.)}


def entropy(p):
    p = np.asarray(p, dtype=float)
    safe = np.clip(p, 1e-300, 1. - 1e-16)
    value = -p * np.log(safe) - (1. - p) * np.log1p(-safe)
    return np.where((p <= 0.) | (p >= 1.), 0., value)


def born_probability(omega, axis, initial, measurement, t):
    angle = np.asarray(omega) * t
    evolved = (np.cos(angle)[..., None] * initial
               + np.sin(angle)[..., None] * np.cross(axis, initial)
               + (1. - np.cos(angle))[..., None] * axis * np.dot(axis, initial))
    return (1. + evolved @ measurement) / 2.


def likelihoods(model, family):
    lo, hi, count = model["omega_grid"]
    grid = np.linspace(lo, hi, count)
    lo, hi, count = model["times"]
    actions, rows = [], []
    for prep in model["preparations"]:
        for measurement in model["measurements"]:
            for t in np.linspace(lo, hi, count):
                probability = born_probability(grid, FAMILIES[family],
                                               AXES[prep], AXES[measurement], t)
                visibility = math.exp(-t / model["visibility_decay_time"])
                probability = .5 + visibility * (probability - .5)
                error = model["readout_error"]
                rows.append(error + (1. - 2. * error) * probability)
                actions.append({"preparation": prep, "measurement": measurement,
                                "time": float(t)})
    table = np.asarray(rows)
    if not np.all(np.isfinite(table)) or np.any((table <= 0.) | (table >= 1.)):
        raise ValueError("invalid likelihood")
    return grid, actions, table


def scores(posterior, table, conditional_entropy):
    return entropy(table @ posterior) - conditional_entropy @ posterior


def exact_decision(posterior, table, conditional_entropy):
    return int(np.argmax(scores(posterior, table, conditional_entropy)))


def continuity_bound(distance):
    d = min(max(float(distance), 0.), 1.)
    return float(entropy(min(d, .5))) + d * math.log(2.)


@dataclass
class Anchor:
    posterior: np.ndarray
    action: int
    gap: float


def certified_decision(posterior, table, conditional_entropy, anchor):
    if anchor is not None:
        distance = float(np.sum(np.abs(posterior - anchor.posterior))) / 2.
        bound = continuity_bound(distance)
        if distance == 0. or anchor.gap > 2. * bound + 1e-12:
            return anchor.action, anchor, False, distance, bound
    else:
        distance, bound = None, None
    values = scores(posterior, table, conditional_entropy)
    action = int(np.argmax(values))
    gap = float(values[action] - np.partition(values, -2)[-2])
    return action, Anchor(posterior.copy(), action, gap), True, distance, bound


def memoized_decision(posterior, table, conditional_entropy, previous):
    if previous is not None and np.array_equal(previous.posterior, posterior):
        return previous.action
    return exact_decision(posterior, table, conditional_entropy)


def timed(function, repeats):
    samples = []
    for _ in range(repeats):
        start = time.perf_counter_ns()
        function()
        samples.append(time.perf_counter_ns() - start)
    return samples


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def dump(path, value):
    with path.open("x", encoding="utf-8", newline="\n") as stream:
        json.dump(value, stream, indent=2, allow_nan=False)
        stream.write("\n")


def source_identity():
    repo = HERE.parent.parent
    sha = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=repo,
                                  text=True).strip()
    changed = subprocess.check_output(
        ["git", "status", "--porcelain", "--untracked-files=no"],
        cwd=repo, text=True).strip()
    if changed:
        raise RuntimeError("Commit tracked changes before the registered run")
    return sha


def run(output):
    started = time.perf_counter()
    protocol = json.loads((HERE / "protocol_r1.json").read_text(encoding="utf-8"))
    source_sha = source_identity()
    output.mkdir(parents=True, exist_ok=False)
    receipt = {"source_sha": source_sha, "protocol_sha256": digest(HERE / "protocol_r1.json"),
               "implementation_sha256": digest(Path(__file__)), "python": platform.python_version(),
               "numpy": np.__version__, "platform": platform.platform(),
               "started_unix_ns": time.time_ns(), "evidence_class": protocol["evidence_class"],
               "external_data_used": False, "paid_calls": 0, "longmemeval_runs": 0}
    dump(output / "receipt_start.json", receipt)
    family_summaries, model_receipts = {}, {}
    n_repeats = protocol["timing_inner_repeats"]
    raw_count = 0
    try:
        with (output / "raw_decisions.jsonl").open("x", encoding="utf-8", newline="\n") as raw:
            for family in protocol["model"]["families"]:
                setup_start = time.perf_counter_ns()
                grid, actions, table = likelihoods(protocol["model"], family)
                conditional = entropy(table)
                setup_ns = time.perf_counter_ns() - setup_start
                model_receipts[family] = {
                    "likelihood_sha256": hashlib.sha256(table.astype("<f8").tobytes()).hexdigest(),
                    "actions": actions, "omega_grid": grid.tolist(),
                    "setup_ns": setup_ns, "shared_likelihood_bytes": table.nbytes + conditional.nbytes}
                seeds = []
                for seed in protocol["seeds"]:
                    rng = np.random.default_rng(seed)
                    truth = int(rng.integers(len(grid)))
                    posterior = np.full(len(grid), 1. / len(grid))
                    anchor = previous = None
                    exact_times, candidate_times, memo_times = [], [], []
                    recomputations = disagreements = unsafe_disagreements = 0
                    max_regret = 0.
                    naive_start = time.perf_counter_ns()
                    _, _, naive_table = likelihoods(protocol["model"], family)
                    exact_decision(posterior, naive_table, entropy(naive_table))
                    naive_ns = time.perf_counter_ns() - naive_start
                    for step in range(protocol["steps_per_seed"]):
                        if time.perf_counter() - started > 120.:
                            raise TimeoutError("registered 120-second bound")
                        def exact():
                            return exact_decision(posterior, table, conditional)

                        def candidate():
                            return certified_decision(posterior, table, conditional, anchor)
                        # Warm each operation on the same input; do not mutate the anchor.
                        exact()
                        candidate()
                        operations = [("exact", exact), ("candidate", candidate)]
                        if step % 2:
                            operations.reverse()
                        measurements = {name: timed(fn, n_repeats) for name, fn in operations}
                        memo_samples = timed(lambda: memoized_decision(
                            posterior, table, conditional, previous), n_repeats)
                        exact_times.append(float(np.median(measurements["exact"])))
                        candidate_times.append(float(np.median(measurements["candidate"])))
                        memo_times.append(float(np.median(memo_samples)))
                        values = scores(posterior, table, conditional)
                        reference = int(np.argmax(values))
                        action, new_anchor, recomputed, distance, bound = candidate()
                        regret = float(values[reference] - values[action])
                        unsafe = previous.action if previous is not None else reference
                        row = {"family": family, "seed": seed, "step": step,
                               "truth_index": truth, "posterior": posterior.tolist(),
                               "reference_action": reference, "candidate_action": action,
                               "recomputed": recomputed, "anchor_distance": distance,
                               "bound": bound, "anchor_gap": anchor.gap if anchor else None,
                               "reference_eig": float(values[reference]), "regret_nats": regret,
                               "uncertified_action": unsafe,
                               "uncertified_regret_nats": float(values[reference] - values[unsafe]),
                               "timing_ns": measurements, "memo_timing_ns": memo_samples}
                        recomputations += int(recomputed)
                        disagreements += int(reference != action)
                        unsafe_disagreements += int(reference != unsafe)
                        max_regret = max(max_regret, regret)
                        outcome = int(rng.random() < table[reference, truth])
                        row["outcome"] = outcome
                        raw.write(json.dumps(row, allow_nan=False) + "\n")
                        raw_count += 1
                        if action != reference or regret > 1e-12:
                            raise AssertionError("certificate disagreed with exact action")
                        previous = Anchor(posterior.copy(), reference, 0.)
                        anchor = new_anchor
                        posterior *= table[reference] if outcome else 1. - table[reference]
                        posterior /= posterior.sum()
                        if not np.all(np.isfinite(posterior)) or np.any(posterior < 0.):
                            raise ValueError("invalid posterior")
                    exact_p95 = float(np.quantile(exact_times, .95))
                    candidate_p95 = float(np.quantile(candidate_times, .95))
                    seeds.append({"seed": seed, "truth_index": truth,
                                  "score_call_fraction": recomputations / protocol["steps_per_seed"],
                                  "disagreements": disagreements, "max_regret_nats": max_regret,
                                  "uncertified_disagreements": unsafe_disagreements,
                                  "exact_p95_ns": exact_p95, "candidate_p95_ns": candidate_p95,
                                  "memo_p95_ns": float(np.quantile(memo_times, .95)),
                                  "p95_speedup": exact_p95 / candidate_p95,
                                  "naive_initial_setup_plus_score_ns": naive_ns,
                                  "final_truth_probability": float(posterior[truth]),
                                  "anchor_array_bytes": anchor.posterior.nbytes})
                ratios = np.array([s["p95_speedup"] for s in seeds])
                bootstrap_rng = np.random.default_rng(protocol["statistics"]["bootstrap_seed"])
                boot = bootstrap_rng.choice(ratios, size=(2000, len(ratios))).mean(axis=1)
                lower, upper = np.quantile(boot, [.025, .975]).tolist()
                fraction = float(np.mean([s["score_call_fraction"] for s in seeds]))
                passed = fraction <= .1 and ratios.mean() >= 10. and lower >= 10.
                family_summaries[family] = {"seeds": seeds, "mean_score_call_fraction": fraction,
                                           "mean_seed_p95_speedup": float(ratios.mean()),
                                           "speedup_95ci": [lower, upper],
                                           "passed_local_screen": bool(passed)}
        result = {**receipt, "status": "survived_local_falsifier" if all(
            f["passed_local_screen"] for f in family_summaries.values()) else "rejected_h4_r1",
                  "families": family_summaries, "models": model_receipts,
                  "raw_rows": raw_count, "raw_sha256": digest(output / "raw_decisions.jsonl"),
                  "elapsed_seconds": time.perf_counter() - started,
                  "scientific_breakthrough_gate": False, "mass_indispensability_gate": False}
        dump(output / "result.json", result)
        print(json.dumps({"status": result["status"], "raw_rows": raw_count,
                          "families": {k: {a: v[a] for a in ["mean_score_call_fraction",
                                        "mean_seed_p95_speedup", "speedup_95ci"]}
                                       for k, v in family_summaries.items()}}, indent=2))
    except Exception as error:
        dump(output / "failure.json", {**receipt, "status": "execution_failed",
                                      "error": repr(error), "raw_rows": raw_count})
        raise


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    run(args.output.resolve())
