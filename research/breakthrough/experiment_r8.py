"""Frozen scalar-component falsifier, all small subspaces plus reused R7 codes."""

import argparse
from collections import Counter
import json
from pathlib import Path
import platform
import time

import numpy as np

from experiment_r1 import HERE, digest, dump, source_identity
from lc_certificate_check import unpack
from lc_projector import affine_solution, equation, nullspace
from lc_r8_corpus import brute_css, cases, isotropic, span
from lc_scalar_check import check
from lc_scalar_components import solve
from lc_stitching import solve as r6_solve, stitch
from lc_stitching_check import verify as verify_r6


SOURCES = ["LC_SCALAR_COMPONENTS.md", "protocol_r8.json", "lc_scalar_components.py",
           "lc_scalar_check.py", "lc_r8_corpus.py", "experiment_r8.py", "test_lc_r8.py",
           "verify_r8.py", "experiment_r1.py", "lc_projector.py", "lc_stitching.py",
           "lc_certificate_check.py", "lc_stitching_check.py", "verify_evidence.py",
           "runs/r7/inputs.jsonl"]


def r6_theorem(rows, n):
    """Apply frozen R6 stitching to general linear S, without claiming a code."""
    pivots = {}
    for g in rows:
        for w in nullspace(rows, 2 * n):
            value, bit = equation(g, w, n)
            while value:
                pivot = value.bit_length() - 1
                if pivot not in pivots:
                    pivots[pivot] = (value, bit)
                    break
                old, rhs = pivots[pivot]
                value, bit = value ^ old, bit ^ rhs
            else:
                if bit:
                    return {"possible": False, "linear_contradiction": True}
    particular, basis = affine_solution(pivots, 3 * n)
    projector, remaining, pieces, considered = stitch(particular, basis, n)
    return {"possible": not remaining, "linear_contradiction": False,
            "affine_dimension": len(basis), "candidates_considered": considered,
            "projector_hex": hex(projector), "cover_pieces": len(pieces)}


def audit_case(case):
    rows, n = [int(v, 16) for v in case["rows_hex"]], case["n"]
    alternative = solve(rows, n)
    verified = check(rows, n, alternative)
    original = r6_theorem(rows, n)
    assert verified["possible"] == original["possible"]
    record = {"key": case["key"], "family": case["family"], "n": n,
              "alternative": alternative, "verification": verified, "r6_theorem": original}
    if case["family"] == "all_linear_subspaces":
        assert len(span(rows)) == 1 << len(rows)
        oracle = brute_css(rows, n)
        assert verified["possible"] == (oracle["positive_frames"] > 0)
        record["oracle"] = oracle
        record["isotropic"] = isotropic(rows, n)
        if record["isotropic"]:
            result = r6_solve(rows, n)
            assert result["status"] != "unresolved"
            assert (result["status"] == "css_equivalent") == verified["possible"]
            record["r6_public_certificate"] = verify_r6(unpack(rows, 2 * n), result)
    else:
        assert case["family"] == "reused_r7_hard"
        assert verified["possible"]
        assert verified["components"] == case["expected_components"]
        assert verified["component_sizes"] == [case["expected_component_size"]] * case["expected_components"]
    return record


def summarize(records):
    small = [r for r in records if r["family"] == "all_linear_subspaces"]
    reused = [r for r in records if r["family"] == "reused_r7_hard"]
    return {"records": len(records), "small_subspaces": len(small), "reused_r7_hard": len(reused),
            "small_counts_by_n": dict(Counter(str(r["n"]) for r in small)),
            "small_isotropic": sum(r["isotropic"] for r in small),
            "small_oracle_assignments": sum(r["oracle"]["assignments"] for r in small),
            "small_positive": sum(r["verification"]["possible"] for r in small),
            "small_negative": sum(not r["verification"]["possible"] for r in small),
            "small_isotropic_positive": sum(r["isotropic"] and r["verification"]["possible"] for r in small),
            "reused_r7_positive": sum(r["verification"]["possible"] for r in reused),
            "maximum_anchor_systems": max((r["alternative"]["anchor_systems"] for r in records), default=0),
            "maximum_component_size": max((max(r["verification"]["component_sizes"]) for r in records), default=0)}


def validate_summary(summary, protocol):
    assert summary["records"] == protocol["records_total"]
    assert summary["small_subspaces"] == protocol["small_subspaces"]
    assert summary["small_counts_by_n"] == protocol["subspace_counts_by_n"]
    assert summary["small_isotropic"] == protocol["isotropic_small_subspaces"]
    assert summary["small_oracle_assignments"] == protocol["small_oracle_local_assignments"]
    assert summary["reused_r7_hard"] == summary["reused_r7_positive"] == protocol["reused_r7_hard_cases"]


def run(output):
    protocol = json.loads((HERE / "protocol_r8.json").read_text())
    assert digest(HERE / "runs/r7/inputs.jsonl") == protocol["r7_inputs_sha256"]
    receipt = {"source_sha": source_identity(), "started_unix_ns": time.time_ns(),
               "hashes": {name: digest(HERE / name) for name in SOURCES},
               "python": platform.python_version(), "numpy": np.__version__, "platform": platform.platform(),
               "evidence_class": "exhaustive_small_subspaces_and_reused_structural_cases",
               "scientific_breakthrough_gate": False, "mass_indispensability_gate": False}
    output.mkdir(parents=True, exist_ok=False)
    dump(output / "receipt_start.json", receipt)
    records, unique, active, failure = [], set(), None, None
    started = time.perf_counter()
    try:
        with (output / "inputs.jsonl").open("x", encoding="utf-8", newline="\n") as inputs, \
                (output / "raw.jsonl").open("x", encoding="utf-8", newline="\n") as raw:
            for case in cases(protocol, HERE / "runs/r7/inputs.jsonl"):
                active = case["key"]
                if time.perf_counter() - started > protocol["wall_seconds"]:
                    raise TimeoutError("registered wall bound")
                inputs.write(json.dumps(case, separators=(",", ":")) + "\n")
                inputs.flush()
                if case["family"] == "all_linear_subspaces":
                    identity = (case["n"], frozenset(span([int(v, 16) for v in case["rows_hex"]])))
                    assert identity not in unique
                    unique.add(identity)
                record = audit_case(case)
                raw.write(json.dumps(record, separators=(",", ":")) + "\n")
                raw.flush()
                records.append(record)
        validate_summary(summarize(records), protocol)
        assert time.perf_counter() - started <= protocol["wall_seconds"]
    except Exception as exc:
        failure = {"type": type(exc).__name__, "message": str(exc), "active_key": active}
    result = {**receipt, "status": "failed_preserved" if failure else "completed_all_predictions_passed",
              "failure": failure, "elapsed_seconds": time.perf_counter() - started,
              "summary": summarize(records), "output_hashes": {
                  name: digest(output / name) for name in ("inputs.jsonl", "raw.jsonl")}}
    dump(output / "result.json", result)
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    result = run(parser.parse_args().output)
    print(json.dumps(result, indent=2))
    raise SystemExit(1 if result["failure"] else 0)
