"""Read-only full replay of the bounded source-interpretation audit."""

import json

from experiment_r1 import HERE, digest
from prior_art_applicability import algebra_control, example_audit
from verify_evidence import committed_hash


def verify(directory=HERE / "runs/prior_art_applicability"):
    receipt = json.loads((directory / "receipt_start.json").read_text())
    result = json.loads((directory / "result.json").read_text())
    protocol = json.loads((HERE / "prior_art_applicability_protocol.json").read_text())
    assert all(result[k] == value for k, value in receipt.items())
    assert result["status"] == "applicability_checks_passed" and result["failure"] is None
    assert 0 <= result["elapsed_seconds"] <= protocol["wall_seconds"]
    for name, expected in receipt["hashes"].items():
        assert digest(HERE / name) == expected
        assert committed_hash(receipt["source_sha"], name) == expected
    assert receipt["hashes"]["lc_stitching.py"] == committed_hash(
        "90579911ad56ae2ef85e0c6f96c5c86d98cec178", "lc_stitching.py")
    assert result["algebra_control"] == algebra_control()
    for source, stored in zip(protocol["source_examples"], result["source_examples"], strict=True):
        regenerated = json.loads(json.dumps(example_audit(source)))
        assert stored["r6_result"]["elapsed_seconds"] >= 0
        # Wall-clock samples are metadata, not expected deterministic outputs.
        regenerated["r6_result"].pop("elapsed_seconds")
        stored["r6_result"].pop("elapsed_seconds")
        assert stored == regenerated
    return {"status": "prior_art_applicability_evidence_verified",
            "source_sha": receipt["source_sha"], "source_examples": len(result["source_examples"]),
            "local_assignments_replayed": sum(r["all_local_assignments_checked"]
                                               for r in result["source_examples"]),
            "arbitrary_idempotent_shortcut_refuted": True,
            "novelty_clearance": False, "external_investigator": False}


if __name__ == "__main__":
    print(json.dumps(verify(), indent=2))
