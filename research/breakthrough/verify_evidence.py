"""Audit saved outcomes via independent posterior-KL EIG; not QInfer execution."""

import hashlib
import json
import subprocess

import numpy as np

from experiment_r1 import HERE, digest, entropy, likelihoods, scores
from experiment_r2 import quotient


def independent_kl_information(prior, table):
    answer = np.zeros(len(table))
    for likelihood in (table, 1. - table):
        predictive = likelihood @ prior
        posterior = likelihood * prior / predictive[:, None]
        log_ratio = np.log(likelihood / predictive[:, None])
        answer += predictive * (posterior * log_ratio).sum(axis=1)
    return answer


def committed_hash(sha, name):
    content = subprocess.check_output(
        ["git", "show", f"{sha}:research/breakthrough/{name}"], cwd=HERE)
    return hashlib.sha256(content).hexdigest()


def verify():
    audit = {}
    for run in ["r1", "r2"]:
        directory = HERE / "runs" / run
        result = json.loads((directory / "result.json").read_text())
        protocol = json.loads((HERE / f"protocol_{run}.json").read_text())
        assert digest(directory / "raw_decisions.jsonl") == result["raw_sha256"]
        hashes = ({"protocol_r1.json": result["protocol_sha256"],
                   "experiment_r1.py": result["implementation_sha256"]}
                  if run == "r1" else result["hashes"])
        for name, expected in hashes.items():
            assert committed_hash(result["source_sha"], name) == expected, name
        tables = {}
        for family in protocol["model"]["families"]:
            _, _, full = likelihoods(protocol["model"], family)
            tables[family] = full if run == "r1" else quotient(full)[0]
            recorded_hash = (result["models"][family]["likelihood_sha256"] if run == "r1"
                             else result["families"][family]["quotient_likelihood_sha256"])
            assert hashlib.sha256(tables[family].astype("<f8").tobytes()).hexdigest() == recorded_hash
        maximum_difference = 0.
        count = mismatches = recomputations = 0
        last_posteriors, seen = {}, set()
        with (directory / "raw_decisions.jsonl").open(encoding="utf-8") as stream:
            for line in stream:
                row = json.loads(line)
                identity = (row["family"], row["seed"], row["step"])
                assert identity not in seen
                seen.add(identity)
                p, table = np.asarray(row["posterior"]), tables[row["family"]]
                kl = independent_kl_information(p, table)
                entropic = scores(p, table, entropy(table))
                delta = float(np.max(np.abs(kl - entropic)))
                maximum_difference = max(maximum_difference, delta)
                assert delta < 1e-12
                reference = row["reference_action"] if run == "r1" else row["baseline_action"]
                assert int(np.argmax(entropic)) == reference
                assert float(kl.max() - kl[reference]) < 1e-12
                mismatches += int(row["candidate_action"] != reference)
                recomputations += int(row["recomputed"])
                key = (row["family"], row["seed"])
                expected_p = (np.full(len(p), 1. / len(p)) if row["step"] == 0
                              else last_posteriors[key])
                np.testing.assert_allclose(p, expected_p, rtol=0., atol=1e-14)
                next_p = p * (table[reference] if row["outcome"] else 1. - table[reference])
                last_posteriors[key] = next_p / next_p.sum()
                assert all(t > 0 for values in row["timing_ns"].values() for t in values)
                count += 1
        steps = protocol["steps_per_seed"] if run == "r1" else protocol["steps"]
        assert seen == {(f, s, t) for f in tables for s in protocol["seeds"] for t in range(steps)}
        assert count == result["raw_rows"] and mismatches == 0
        audit[run] = {"rows": count, "source_and_raw_hashes_match": True,
                      "posterior_recurrence_matches": True, "action_disagreements": mismatches,
                      "recomputed_calls": recomputations, "max_eig_vs_independent_kl_error": maximum_difference}
    result = json.loads((HERE / "runs/r3/result.json").read_text())
    assert digest(HERE / "runs/r3/raw.json") == result["raw_sha256"]
    for name, expected in result["hashes"].items():
        assert committed_hash(result["source_sha"], name) == expected
    audit["r3"] = {"source_and_raw_hashes_match": True, "external_physics_validation": False}
    print(json.dumps({"status": "evidence_integrity_verified", "runs": audit}, indent=2))


if __name__ == "__main__":
    verify()
