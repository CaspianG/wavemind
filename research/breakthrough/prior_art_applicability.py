"""Exact source-example audit and counterexample to a tempting invalid reduction."""

import argparse
from itertools import product
import json
from pathlib import Path
import platform
import time

import numpy as np

from experiment_r1 import HERE, digest, dump, source_identity
from lc_certificate_check import dense_css, dense_rank, transformed
from lc_stitching import solve
from lc_stitching_check import verify


SOURCES = ["prior_art_applicability_protocol.json", "prior_art_applicability.py",
           "experiment_r1.py", "lc_certificate_check.py", "lc_stitching.py",
           "lc_stitching_check.py", "lc_projector.py"]


def algebra_control():
    identity = np.eye(2, dtype=np.uint8)
    f = np.array([[0, 1], [1, 1]], dtype=np.uint8)
    members = [np.zeros((2, 2), dtype=np.uint8), identity, f, identity ^ f]
    def encode(a):
        return tuple(int(v) for v in a.reshape(-1))
    keys = {encode(a) for a in members}
    assert len(keys) == 4
    assert all(encode(a ^ b) in keys and encode((a @ b) % 2) in keys
               for a in members for b in members)
    idempotents = [a for a in members if np.array_equal((a @ a) % 2, a)]
    ranks = [dense_rank(a) for a in idempotents]
    assert sorted(ranks) == [0, 2]
    return {"algebra": "F4_embedded_in_M2_F2", "members": [list(encode(a)) for a in members],
            "idempotent_ranks": ranks, "has_nonzero_idempotent": True,
            "has_rank_one_idempotent": False,
            "conclusion": "arbitrary_nonzero_idempotent_is_not_the_required_witness"}


def example_audit(example):
    n = len(example["paulis"][0])
    labels = {"I": (0, 0), "X": (1, 0), "Y": (1, 1), "Z": (0, 1)}
    pairs = np.array([[labels[p] for p in word] for word in example["paulis"]], dtype=np.uint8)
    matrix = np.concatenate((pairs[:, :, 0], pairs[:, :, 1]), axis=1)
    assert n == 4 and dense_rank(matrix) == 3
    assert not np.any((matrix[:, :n] @ matrix[:, n:].T ^ matrix[:, n:] @ matrix[:, :n].T) % 2)
    cliffords = [g for g in product((0, 1), repeat=4) if (g[0] * g[3] ^ g[1] * g[2]) == 1]
    local_count, first = 0, None
    for gates in product(cliffords, repeat=n):
        if dense_css(transformed(matrix, gates)):
            local_count += 1
            if first is None:
                first = gates
    uniform_count = sum(dense_css(transformed(matrix, [g] * n)) for g in cliffords)
    assert bool(local_count) == example["expected_local_css"]
    assert bool(uniform_count) == example["expected_uniform_css"]
    rows = [sum(int(bit) << i for i, bit in enumerate(row)) for row in matrix]
    candidate = solve(rows, n)
    assert candidate["status"] != "unresolved"
    assert (candidate["status"] == "css_equivalent") == bool(local_count)
    certificate = verify(matrix, candidate)
    return {"name": example["name"], "paulis": example["paulis"], "n": n,
            "all_local_assignments_checked": len(cliffords) ** n,
            "local_css_assignments": local_count, "uniform_assignments_checked": len(cliffords),
            "uniform_css_assignments": uniform_count, "first_local_witness": first,
            "r6_result": candidate, "certificate_audit": certificate}


def audit(output):
    protocol = json.loads((HERE / "prior_art_applicability_protocol.json").read_text())
    receipt = {"source_sha": source_identity(), "started_unix_ns": time.time_ns(),
               "python": platform.python_version(), "numpy": np.__version__,
               "hashes": {name: digest(HERE / name) for name in SOURCES},
               "evidence_class": "source_examples_and_exact_reduction_counterexample",
               "scientific_breakthrough_gate": False, "mass_indispensability_gate": False}
    output.mkdir(parents=True, exist_ok=False)
    dump(output / "receipt_start.json", receipt)
    started = time.perf_counter()
    records, control, failure = [], None, None
    try:
        control = algebra_control()
        for example in protocol["source_examples"]:
            records.append(example_audit(example))
        assert time.perf_counter() - started <= protocol["wall_seconds"]
    except Exception as exc:
        failure = {"type": type(exc).__name__, "message": str(exc)}
    result = {**receipt, "status": "failed_preserved" if failure else "applicability_checks_passed",
              "failure": failure, "algebra_control": control, "source_examples": records,
              "elapsed_seconds": time.perf_counter() - started}
    dump(output / "result.json", result)
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    result = audit(parser.parse_args().output)
    print(json.dumps(result, indent=2))
    raise SystemExit(1 if result["failure"] else 0)
