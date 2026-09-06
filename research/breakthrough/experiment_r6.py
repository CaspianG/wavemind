"""Preregistered finite graph universe and proper-code stitching falsifier."""

import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import platform
import time

import numpy as np

from experiment_r1 import HERE, digest, dump, source_identity
from lc_certificate_check import brute_lc_css, unpack
from lc_graph_oracle import graph_stabilizers, orbit_table
from lc_projector import solve as old_solve
from lc_r6_corpus import proper_cases
from lc_stitching import solve
from lc_stitching_check import verify


SOURCES = ["protocol_r6.json", "LC_STITCHING.md", "lc_stitching.py", "lc_stitching_check.py",
           "lc_graph_oracle.py", "lc_r6_corpus.py", "experiment_r6.py", "test_lc_stitching.py",
           "lc_projector.py", "lc_certificate_check.py", "experiment_r1.py"]


def oracle_digest(table):
    data = [[word, row["css_equivalent"], row["orbit_representative"], row["orbit_size"],
             row["bipartite_witness"]] for word, row in sorted(table.items())]
    return hashlib.sha256(json.dumps(data, separators=(",", ":")).encode()).hexdigest()


def run(output):
    protocol = json.loads((HERE / "protocol_r6.json").read_text())
    receipt = {"source_sha": source_identity(), "started_unix_ns": time.time_ns(),
               "hashes": {name: digest(HERE / name) for name in SOURCES},
               "python": platform.python_version(), "numpy": np.__version__, "platform": platform.platform(),
               "evidence_class": "exhaustive_small_graph_orbits_and_seeded_constructed_codes",
               "scientific_breakthrough_gate": False, "mass_indispensability_gate": False}
    output.mkdir(parents=True, exist_ok=False)
    dump(output / "receipt_start.json", receipt)
    started = time.perf_counter()
    counts, families, certificates = Counter(), Counter(), Counter()
    comparisons, lifted, ablation_false_positives, max_candidates, brute_checks = 0, 0, 0, 0, 0
    oracle_hashes = {}
    active_key = None
    try:
        cases = proper_cases(protocol["seed"])
        dump(output / "proper_cases.json", cases)
        with (output / "raw.jsonl").open("x", encoding="utf-8", newline="\n") as stream:
            def evaluate(case, oracle=None):
                nonlocal comparisons, lifted, ablation_false_positives, max_candidates, brute_checks, active_key
                active_key = case["key"]
                if time.perf_counter() - started > protocol["resource_limits"]["sweep_seconds"]:
                    raise TimeoutError("registered sweep wall budget")
                rows, n = case["rows"], case["n"]
                candidate = solve(rows, n, seconds=protocol["resource_limits"]["candidate_seconds_per_instance"])
                matrix = unpack(rows, 2 * n)
                checked = verify(matrix, candidate)
                previous = old_solve(rows, n, seconds=protocol["resource_limits"]["r5_seconds_per_instance"])
                verify(matrix, previous)
                truth = case.get("expected") if oracle is None else oracle["css_equivalent"]
                brute = None
                if case["family"] == "random_clifford" and n <= 5:
                    brute = brute_lc_css(matrix)
                    brute_checks += 1
                    truth = brute
                decided = candidate["status"] != "unresolved"
                if truth is not None and decided:
                    assert (candidate["status"] == "css_equivalent") == truth, "external-form oracle disagreement"
                    comparisons += 1
                if decided and previous["status"] != "unresolved":
                    assert candidate["status"] == previous["status"], "R5 disagreement"
                if decided and previous["status"] == "unresolved":
                    lifted += 1
                if candidate["status"] == "not_lc_css" and candidate.get("affine_dimension") is not None:
                    ablation_false_positives += 1
                if "candidates_considered" in candidate:
                    assert candidate["candidates_considered"] <= candidate["affine_dimension"] + 1
                    max_candidates = max(max_candidates, candidate["candidates_considered"])
                if case["family"] == "toric":
                    assert candidate["stabilizer_rank"] == n - 2
                if case["family"] == "bell_products":
                    assert candidate["stabilizer_rank"] == n
                if case["family"] == "five_with_spectators":
                    assert candidate["stabilizer_rank"] == 4
                row = {"key": case["key"], "family": case["family"], "n": n,
                       "graph_word": case.get("graph_word"), "oracle": oracle, "expected": truth,
                       "brute_enumeration": brute, "candidate": candidate, "independent_check": checked,
                       "r5_status": previous["status"], "r5_reason": previous.get("reason"),
                       "r5_seconds": previous["elapsed_seconds"]}
                stream.write(json.dumps(row, separators=(",", ":")) + "\n")
                stream.flush()
                counts[candidate["status"]] += 1
                certificates[checked] += 1
                families[case["family"]] += 1
                if sum(counts.values()) % 2000 == 0:
                    print(json.dumps({"completed": sum(counts.values()), "counts": dict(counts),
                                      "seconds": time.perf_counter() - started}), flush=True)

            for n in range(1, 7):
                table = orbit_table(n)
                oracle_hashes[str(n)] = oracle_digest(table)
                for word in sorted(table):
                    evaluate({"key": f"graph-{n}-{word}", "family": "graph_state", "n": n,
                              "graph_word": word, "rows": graph_stabilizers(word, n)}, table[word])
            for case in cases:
                evaluate(case)
        complete = sum(counts.values()) == protocol["records_total"] and counts["unresolved"] == 0
        summary = {**receipt, "status": "complete_falsifier" if complete else "partial_falsifier",
                   "records": sum(counts.values()), "counts": dict(counts), "families": dict(families),
                   "certificate_counts": dict(certificates), "oracle_comparisons": comparisons,
                   "proper_code_brute_enumerations": brute_checks, "previously_unresolved_certified": lifted,
                   "trace_only_ablation_false_positives": ablation_false_positives,
                   "maximum_candidate_maps_considered": max_candidates, "oracle_table_hashes": oracle_hashes,
                   "raw_sha256": digest(output / "raw.jsonl"), "cases_sha256": digest(output / "proper_cases.json"),
                   "elapsed_seconds": time.perf_counter() - started,
                   "predictions": {"no_disagreement_or_invalid_certificate": True,
                                   "complete_within_budget": complete and time.perf_counter() - started <= 600,
                                   "at_least_twelve_r5_unresolved_certified": lifted >= 12,
                                   "trace_only_ablation_refuted": ablation_false_positives > 0}}
        dump(output / "result.json", summary)
        print(json.dumps({k: v for k, v in summary.items() if k != "hashes"}, indent=2), flush=True)
    except Exception as error:
        dump(output / "failure.json", {**receipt, "error": repr(error), "completed_records": sum(counts.values()),
                                      "active_case_key": active_key,
                                      "raw_sha256": digest(output / "raw.jsonl") if (output / "raw.jsonl").exists() else None})
        raise


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True, type=Path)
    run(parser.parse_args().output.resolve())
