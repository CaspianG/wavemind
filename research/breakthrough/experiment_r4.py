"""Frozen exact diagnostic baseline sweep, with no external endpoints."""

import argparse
import json
import time
from fractions import Fraction as F
from pathlib import Path

from diagnostic_oracle import dot, enumerate_policy_vectors, sign_problem, solve
from experiment_r1 import HERE, digest, dump, source_identity


def run(output):
    protocol = json.loads((HERE / "protocol_r4.json").read_text())
    receipt = {"source_sha": source_identity(), "started_unix_ns": time.time_ns(),
               "hashes": {f: digest(HERE / f) for f in ["protocol_r4.json", "diagnostic_oracle.py",
                                                       "experiment_r4.py", "experiment_r1.py"]},
               "evidence_class": "exact_generated_model_baseline", "external_data_used": False,
               "scientific_breakthrough_gate": False, "mass_indispensability_gate": False}
    output.mkdir(parents=True, exist_ok=False)
    dump(output / "receipt_start.json", receipt)
    rows, start = [], time.perf_counter()
    try:
        for noise in protocol["noises"]:
            for cost in protocol["probe_costs"]:
                problem = sign_problem(F(noise), F(cost))
                policy_vectors = enumerate_policy_vectors(problem, 2)
                for prior in protocol["positive_sign_priors"]:
                    belief = (1 - F(prior), F(prior))
                    previous_risk = None
                    for horizon in protocol["horizons"]:
                        if time.perf_counter() - start > 120.:
                            raise TimeoutError("registered wall bound")
                        result = solve(problem, belief, horizon)
                        if horizon == 2:
                            assert result["risk"] == min(dot(belief, p) for p in policy_vectors)
                        if previous_risk is not None:
                            assert result["risk"] <= previous_risk
                        previous_risk = result["risk"]
                        rows.append({"noise": noise, "probe_cost": cost, "positive_prior": prior,
                                     "horizon": horizon, "risk": str(result["risk"]),
                                     "expected_probes": str(result["expected_probes"]),
                                     "root_action": result["root_action"],
                                     "cached_states": result["cached_states"]})
        dump(output / "raw.json", rows)
        one_step, final = {}, {}
        for row in rows:
            key = (row["noise"], row["probe_cost"], row["positive_prior"])
            if row["horizon"] == 1:
                one_step[key] = F(row["risk"])
            if row["horizon"] == 6:
                final[key] = F(row["risk"])
        gains = [{"noise": k[0], "cost": k[1], "prior": k[2],
                  "one_probe_risk": str(one_step[k]), "adaptive_risk": str(v),
                  "risk_ratio": str(one_step[k] / v) if v else None}
                 for k, v in final.items() if v < one_step[k]]
        result = {**receipt, "status": "optimal_baseline_verified", "rows": len(rows),
                  "depth_two_scenarios_verified": len(final), "one_probe_suboptimal_scenarios": len(gains),
                  "gains": gains, "raw_sha256": digest(output / "raw.json"),
                  "elapsed_seconds": time.perf_counter() - start}
        dump(output / "result.json", result)
        print(json.dumps({k: result[k] for k in ["status", "rows", "depth_two_scenarios_verified",
                                               "one_probe_suboptimal_scenarios", "gains", "elapsed_seconds"]}, indent=2))
    except Exception as error:
        dump(output / "failure.json", {**receipt, "status": "execution_failed", "error": repr(error)})
        raise


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    run(parser.parse_args().output.resolve())
