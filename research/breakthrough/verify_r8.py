"""Read-only exhaustive replay; hash and source pins, not just a verdict file."""

import json

from experiment_r1 import HERE, digest
from experiment_r8 import SOURCES, audit_case, summarize, validate_summary
from lc_r8_corpus import cases, span
from verify_evidence import committed_hash


def verify(directory=HERE / "runs/r8"):
    receipt = json.loads((directory / "receipt_start.json").read_text())
    result = json.loads((directory / "result.json").read_text())
    protocol = json.loads((HERE / "protocol_r8.json").read_text())
    assert all(result[key] == value for key, value in receipt.items())
    assert set(receipt["hashes"]) == set(SOURCES)
    for name, expected in receipt["hashes"].items():
        assert digest(HERE / name) == committed_hash(receipt["source_sha"], name) == expected
    for name in ("lc_projector.py", "lc_stitching.py", "lc_stitching_check.py", "lc_certificate_check.py"):
        assert receipt["hashes"][name] == committed_hash("90579911ad56ae2ef85e0c6f96c5c86d98cec178", name)
    assert receipt["hashes"]["runs/r7/inputs.jsonl"] == protocol["r7_inputs_sha256"]
    for name, expected in result["output_hashes"].items():
        assert digest(directory / name) == expected
    assert set(result["output_hashes"]) == {"inputs.jsonl", "raw.jsonl"}
    assert result["status"] == "completed_all_predictions_passed" and result["failure"] is None
    assert 0 <= result["elapsed_seconds"] <= protocol["wall_seconds"]
    inputs = [json.loads(line) for line in (directory / "inputs.jsonl").read_text().splitlines()]
    records = [json.loads(line) for line in (directory / "raw.jsonl").read_text().splitlines()]
    assert inputs == list(cases(protocol, HERE / "runs/r7/inputs.jsonl"))
    unique = set()
    for case, stored in zip(inputs, records, strict=True):
        assert stored == audit_case(case)
        if case["family"] == "all_linear_subspaces":
            identity = (case["n"], frozenset(span([int(v, 16) for v in case["rows_hex"]])))
            assert identity not in unique
            unique.add(identity)
    summary = summarize(records)
    validate_summary(summary, protocol)
    assert result["summary"] == summary
    return {"status": "R8_frozen_evidence_verified", "source_sha": receipt["source_sha"],
            "summary": summary, "novelty_clearance": False, "independent_investigator": False}


if __name__ == "__main__":
    print(json.dumps(verify(), indent=2))
