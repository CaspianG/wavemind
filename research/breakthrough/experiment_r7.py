"""Frozen, finite adversarial affine-frame test; never an external admission."""

import argparse
from collections import Counter
import json
from pathlib import Path
import platform
import time

import numpy as np

from experiment_r1 import HERE, digest, dump, source_identity
from lc_r7_check import check, non_algebra_control
from lc_r7_frames import generate


SOURCES = ["protocol_r7.json", "LC_ADVERSARIAL_FRAMES.md", "lc_r7_frames.py",
           "lc_r7_check.py", "test_lc_r7.py", "experiment_r7.py", "lc_stitching.py",
           "lc_projector.py", "lc_certificate_check.py", "experiment_r1.py"]


def configurations(protocol):
    for length in protocol["block_lengths"]:
        for blocks in protocol["block_counts"]:
            for repeat in range(protocol["seed_repeats"]):
                seed = protocol["base_seed"] + 10000 * length + 100 * blocks + repeat
                for basis in protocol["basis_modes"]:
                    for particular in protocol["particular_modes"]:
                        yield {"key": f"L{length}-B{blocks}-R{repeat}-{basis}-{particular}",
                               "length": length, "blocks": blocks, "seed": seed,
                               "basis_mode": basis, "particular_mode": particular}


def summarize(records):
    by_arm = Counter()
    for row in records:
        by_arm[row["basis_mode"] + "/" + row["particular_mode"]] += 1
    checked = [row["verification"] for row in records]
    return {
        "records": len(records), "by_arm": dict(by_arm),
        "hard_arm_records": sum(v["hard_arm"] for v in checked),
        "multi_piece_records": sum(len(v["pieces"]) > 1 for v in checked),
        "no_global_single_candidate_records": sum(v["global_single_candidates"] == 0 for v in checked),
        "unpartitioned_sum_failures": sum(not v["unpartitioned_sum_is_projector"] for v in checked),
        "max_pieces": max((len(v["pieces"]) for v in checked), default=0),
        "max_candidates_considered": max((v["candidates_considered"] for v in checked), default=0),
        "max_affine_dimension": max((v["affine_dimension"] for v in checked), default=0),
        "max_qubits": max((v["n"] for v in checked), default=0),
        "matrix_unit_products_checked": sum(v["matrix_unit_products_checked"] for v in checked),
        "preserving_maps_checked": sum(v["preserving_maps_checked"] for v in checked),
    }


def run(output):
    protocol = json.loads((HERE / "protocol_r7.json").read_text())
    receipt = {"source_sha": source_identity(), "started_unix_ns": time.time_ns(),
               "hashes": {name: digest(HERE / name) for name in SOURCES},
               "python": platform.python_version(), "numpy": np.__version__,
               "platform": platform.platform(), "evidence_class": "constructed_affine_frame_mechanism_test",
               "scientific_breakthrough_gate": False, "mass_indispensability_gate": False}
    output.mkdir(parents=True, exist_ok=False)
    dump(output / "receipt_start.json", receipt)
    records, active_key, failure = [], None, None
    started = time.perf_counter()
    try:
        control = non_algebra_control()
        dump(output / "assumption_control.json", control)
        with (output / "inputs.jsonl").open("x", encoding="utf-8", newline="\n") as inputs, \
                (output / "raw.jsonl").open("x", encoding="utf-8", newline="\n") as raw:
            for config in configurations(protocol):
                active_key = config["key"]
                if time.perf_counter() - started > protocol["wall_seconds"]:
                    raise TimeoutError("registered wall-time bound")
                case = generate(**{k: v for k, v in config.items() if k != "key"})
                inputs.write(json.dumps({"key": active_key, "case": case}, separators=(",", ":")) + "\n")
                inputs.flush()
                case_started = time.perf_counter()
                record = {**config, "verification": check(case),
                          "elapsed_seconds": time.perf_counter() - case_started}
                raw.write(json.dumps(record, separators=(",", ":")) + "\n")
                raw.flush()
                records.append(record)
        summary = summarize(records)
        assert summary["records"] == protocol["records_total"]
        assert summary["hard_arm_records"] == protocol["hard_arm_records"]
        assert summary["unpartitioned_sum_failures"] > 0
        assert time.perf_counter() - started <= protocol["wall_seconds"]
    except Exception as exc:
        failure = {"type": type(exc).__name__, "message": str(exc), "active_key": active_key}
    result = {**receipt, "status": "failed_preserved" if failure else "completed_all_predictions_passed",
              "failure": failure, "elapsed_seconds": time.perf_counter() - started,
              "summary": summarize(records),
              "output_hashes": {name: digest(output / name) for name in
                                ("inputs.jsonl", "raw.jsonl", "assumption_control.json")
                                if (output / name).exists()}}
    dump(output / "result.json", result)
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    result = run(parser.parse_args().output)
    print(json.dumps(result, indent=2))
    raise SystemExit(1 if result["failure"] else 0)
