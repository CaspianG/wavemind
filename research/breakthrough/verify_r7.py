"""Read-only replay of R7 inputs, algebra invariants, certificates and hashes."""

from collections import Counter
from itertools import product
import json
import time

from experiment_r1 import HERE, digest
from lc_r7_check import check, non_algebra_control
from lc_r7_frames import generate
from verify_evidence import committed_hash


def verify():
    started = time.perf_counter()
    directory = HERE / "runs/r7"
    receipt = json.loads((directory / "receipt_start.json").read_text())
    result = json.loads((directory / "result.json").read_text())
    protocol = json.loads((HERE / "protocol_r7.json").read_text())
    assert all(result[k] == v for k, v in receipt.items())
    assert result["status"] == "completed_all_predictions_passed" and result["failure"] is None
    assert result["elapsed_seconds"] <= protocol["wall_seconds"]
    for name, expected in receipt["hashes"].items():
        assert committed_hash(receipt["source_sha"], name) == expected
        assert digest(HERE / name) == expected, "frozen R7 source changed"
    assert receipt["hashes"]["lc_stitching.py"] == committed_hash(
        "90579911ad56ae2ef85e0c6f96c5c86d98cec178", "lc_stitching.py")
    assert set(result["output_hashes"]) == {"inputs.jsonl", "raw.jsonl", "assumption_control.json"}
    for name, expected in result["output_hashes"].items():
        assert digest(directory / name) == expected
    control = json.loads((directory / "assumption_control.json").read_text())
    assert control == non_algebra_control()
    counts, by_arm = Counter(), Counter()
    maxima = Counter()
    inputs = [json.loads(line) for line in (directory / "inputs.jsonl").read_text().splitlines()]
    records = [json.loads(line) for line in (directory / "raw.jsonl").read_text().splitlines()]
    configurations = product(protocol["block_lengths"], protocol["block_counts"],
                             range(protocol["seed_repeats"]), protocol["basis_modes"],
                             protocol["particular_modes"])
    for config, stored, row in zip(configurations, inputs, records, strict=True):
        length, blocks, repeat, basis, particular = config
        seed = protocol["base_seed"] + 10000 * length + 100 * blocks + repeat
        key = f"L{length}-B{blocks}-R{repeat}-{basis}-{particular}"
        assert row["key"] == stored["key"] == key
        case = generate(length, blocks, seed, basis, particular)
        assert stored["case"] == case
        for field in ("length", "blocks", "seed", "basis_mode", "particular_mode"):
            assert row[field] == case[field]
        checked = json.loads(json.dumps(check(case)))
        assert checked == row["verification"]
        assert row["elapsed_seconds"] >= 0
        counts["records"] += 1
        counts["hard_arm_records"] += checked["hard_arm"]
        counts["multi_piece_records"] += len(checked["pieces"]) > 1
        counts["no_global_single_candidate_records"] += checked["global_single_candidates"] == 0
        counts["unpartitioned_sum_failures"] += not checked["unpartitioned_sum_is_projector"]
        counts["matrix_unit_products_checked"] += checked["matrix_unit_products_checked"]
        counts["preserving_maps_checked"] += checked["preserving_maps_checked"]
        for name, value in {
            "max_pieces": len(checked["pieces"]),
            "max_candidates_considered": checked["candidates_considered"],
            "max_affine_dimension": checked["affine_dimension"], "max_qubits": checked["n"],
        }.items():
            maxima[name] = max(maxima[name], value)
        by_arm[basis + "/" + particular] += 1
    summary = {**dict(counts), **dict(maxima), "by_arm": dict(by_arm)}
    assert summary == result["summary"]
    assert counts["records"] == protocol["records_total"]
    assert counts["hard_arm_records"] == protocol["hard_arm_records"]
    assert counts["unpartitioned_sum_failures"] > 0
    return {"status": "R7_frozen_evidence_verified", "source_sha": receipt["source_sha"],
            "summary": summary, "assumption_control": control["status"],
            "elapsed_seconds": time.perf_counter() - started,
            "independent_investigator_or_novelty_clearance": False}


if __name__ == "__main__":
    print(json.dumps(verify(), indent=2))
