"""Read-only audit of the stored R4 baseline; never overwrite run evidence."""

import json
from fractions import Fraction as F
from itertools import product

from diagnostic_oracle import dot, enumerate_policy_vectors, sign_problem, solve
from experiment_r1 import HERE, digest
from verify_evidence import committed_hash


def verify():
    directory = HERE / "runs/r4"
    result = json.loads((directory / "result.json").read_text())
    receipt = json.loads((directory / "receipt_start.json").read_text())
    assert all(result[key] == value for key, value in receipt.items())
    assert digest(directory / "raw.json") == result["raw_sha256"]
    for name, expected_hash in result["hashes"].items():
        assert committed_hash(result["source_sha"], name) == expected_hash
        assert digest(HERE / name) == expected_hash, "Replay must use frozen R4 sources"
    protocol = json.loads((HERE / "protocol_r4.json").read_text())
    rows = json.loads((directory / "raw.json").read_text())
    expected = set(product(protocol["noises"], protocol["probe_costs"],
                           protocol["positive_sign_priors"], protocol["horizons"]))
    seen, risks, gains = set(), {}, []
    brute_checks = 0
    for row in rows:
        key = (row["noise"], row["probe_cost"], row["positive_prior"], row["horizon"])
        assert key not in seen
        seen.add(key)
        problem = sign_problem(F(key[0]), F(key[1]))
        belief = (1 - F(key[2]), F(key[2]))
        replay = solve(problem, belief, key[3])
        assert str(replay["risk"]) == row["risk"]
        assert str(replay["expected_probes"]) == row["expected_probes"]
        assert list(replay["root_action"]) == row["root_action"]
        assert replay["cached_states"] == row["cached_states"]
        if key[3] == 2:
            assert replay["risk"] == min(dot(belief, p) for p in enumerate_policy_vectors(problem, 2))
            brute_checks += 1
        risks[key] = replay["risk"]
    assert seen == expected and len(rows) == result["rows"] == 315
    assert brute_checks == result["depth_two_scenarios_verified"] == 45
    for noise, cost, prior in product(protocol["noises"], protocol["probe_costs"],
                                      protocol["positive_sign_priors"]):
        key = (noise, cost, prior)
        for horizon in range(1, 7):
            assert risks[(*key, horizon)] <= risks[(*key, horizon - 1)]
        one, adaptive = risks[(*key, 1)], risks[(*key, 6)]
        if adaptive < one:
            gains.append({"noise": noise, "cost": cost, "prior": prior,
                          "one_probe_risk": str(one), "adaptive_risk": str(adaptive),
                          "risk_ratio": str(one / adaptive) if adaptive else None})
    assert gains == result["gains"]
    assert len(gains) == result["one_probe_suboptimal_scenarios"] == 15
    assert result["scientific_breakthrough_gate"] is False
    assert result["mass_indispensability_gate"] is False
    print(json.dumps({"status": "R4_integrity_verified", "exact_rows_replayed": len(rows),
                      "independent_depth_two_enumerations": brute_checks,
                      "new_mechanism_or_external_validation": False}, indent=2))


if __name__ == "__main__":
    verify()
