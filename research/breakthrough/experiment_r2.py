"""Second registered falsifier: quotient equivalent channels for BOTH methods."""

import argparse
import hashlib
import json
import time
from pathlib import Path

import numpy as np

from experiment_r1 import (HERE, certified_decision, digest, dump, entropy,
                           exact_decision, likelihoods, scores, source_identity, timed)


def quotient(table):
    representatives, mapping = [], []
    for row in table:
        group = next((i for i, r in enumerate(representatives)
                      if np.allclose(row, r, rtol=0., atol=1e-14)
                      or np.allclose(row, 1. - r, rtol=0., atol=1e-14)), None)
        if group is None:
            group = len(representatives)
            representatives.append(row)
        mapping.append(group)
    return np.asarray(representatives), mapping


def run(output):
    started = time.perf_counter()
    protocol = json.loads((HERE / "protocol_r2.json").read_text())
    receipt = {"source_sha": source_identity(), "started_unix_ns": time.time_ns(),
               "hashes": {f: digest(HERE / f) for f in ["protocol_r2.json", "experiment_r1.py",
                                                       "experiment_r2.py"]},
               "numpy": np.__version__, "evidence_class": "local_generated_model_falsifier",
               "external_data_used": False, "longmemeval_runs": 0, "paid_calls": 0}
    output.mkdir(parents=True, exist_ok=False)
    dump(output / "receipt_start.json", receipt)
    families, row_count = {}, 0
    try:
        with (output / "raw_decisions.jsonl").open("x", encoding="utf-8", newline="\n") as raw:
            for family in protocol["model"]["families"]:
                grid, actions, full = likelihoods(protocol["model"], family)
                setup_start = time.perf_counter_ns()
                table, mapping = quotient(full)
                quotient_ns = time.perf_counter_ns() - setup_start
                conditional, full_conditional = entropy(table), entropy(full)
                seed_results = []
                for seed in protocol["seeds"]:
                    rng = np.random.default_rng(seed)
                    truth = int(rng.integers(len(grid)))
                    posterior = np.full(len(grid), 1. / len(grid))
                    anchor = None
                    recomputed_count = 0
                    baseline_times, candidate_times = [], []
                    for step in range(protocol["steps"]):
                        if time.perf_counter() - started > 120.:
                            raise TimeoutError("registered 120-second bound")

                        def baseline():
                            return exact_decision(posterior, table, conditional)

                        def candidate():
                            return certified_decision(posterior, table, conditional, anchor)

                        baseline()
                        candidate()
                        order = [("baseline", baseline), ("candidate", candidate)]
                        if step % 2:
                            order.reverse()
                        samples = {name: timed(fn, protocol["timing_repeats"]) for name, fn in order}
                        baseline_times.append(float(np.median(samples["baseline"])))
                        candidate_times.append(float(np.median(samples["candidate"])))
                        expected = baseline()
                        action, new_anchor, recomputed, distance, bound = candidate()
                        values = scores(posterior, table, conditional)
                        full_regret = float(np.max(scores(posterior, full, full_conditional)) - values[action])
                        outcome = int(rng.random() < table[expected, truth])
                        raw.write(json.dumps({"family": family, "seed": seed, "step": step,
                                              "truth_index": truth, "posterior": posterior.tolist(),
                                              "baseline_action": expected, "candidate_action": action,
                                              "recomputed": recomputed, "distance": distance,
                                              "bound": bound, "anchor_gap": anchor.gap if anchor else None,
                                              "full_table_regret_nats": full_regret,
                                              "outcome": outcome, "timing_ns": samples}, allow_nan=False) + "\n")
                        row_count += 1
                        if expected != action or abs(full_regret) > 1e-12:
                            raise AssertionError("quotient or certificate changed optimal EIG")
                        recomputed_count += int(recomputed)
                        anchor = new_anchor
                        posterior *= table[expected] if outcome else 1. - table[expected]
                        posterior /= posterior.sum()
                        if not np.all(np.isfinite(posterior)):
                            raise ValueError("invalid posterior")
                    p95_base = float(np.quantile(baseline_times, .95))
                    p95_candidate = float(np.quantile(candidate_times, .95))
                    seed_results.append({"seed": seed, "score_call_fraction": recomputed_count / protocol["steps"],
                                         "baseline_p95_ns": p95_base, "candidate_p95_ns": p95_candidate,
                                         "p95_speedup": p95_base / p95_candidate})
                ratios = np.array([s["p95_speedup"] for s in seed_results])
                rng_boot = np.random.default_rng(protocol["statistics"]["bootstrap_seed"])
                boot = rng_boot.choice(ratios, size=(2000, len(ratios))).mean(axis=1)
                lower, upper = np.quantile(boot, [.025, .975]).tolist()
                fraction = float(np.mean([s["score_call_fraction"] for s in seed_results]))
                families[family] = {"seeds": seed_results, "full_actions": len(full),
                                    "quotient_actions": len(table), "quotient_map": mapping,
                                    "actions": actions, "grid": grid.tolist(), "quotient_setup_ns": quotient_ns,
                                    "full_likelihood_sha256": hashlib.sha256(full.astype("<f8").tobytes()).hexdigest(),
                                    "quotient_likelihood_sha256": hashlib.sha256(table.astype("<f8").tobytes()).hexdigest(),
                                    "score_call_fraction": fraction, "mean_seed_p95_speedup": float(ratios.mean()),
                                    "speedup_95ci": [lower, upper],
                                    "passed": bool(fraction <= .1 and ratios.mean() >= 10. and lower >= 10.)}
        result = {**receipt, "families": families, "raw_rows": row_count,
                  "status": "survived_local_falsifier" if all(f["passed"] for f in families.values()) else "rejected_h4_r2",
                  "raw_sha256": digest(output / "raw_decisions.jsonl"),
                  "elapsed_seconds": time.perf_counter() - started,
                  "scientific_breakthrough_gate": False, "mass_indispensability_gate": False}
        dump(output / "result.json", result)
        print(json.dumps({"status": result["status"], "raw_rows": row_count,
                          "families": {f: {k: v[k] for k in ["full_actions", "quotient_actions",
                                        "score_call_fraction", "mean_seed_p95_speedup", "speedup_95ci"]}
                                       for f, v in families.items()}}, indent=2))
    except Exception as error:
        dump(output / "failure.json", {**receipt, "status": "execution_failed", "error": repr(error),
                                      "raw_rows": row_count})
        raise


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    run(parser.parse_args().output.resolve())
