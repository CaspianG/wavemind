"""Read-only replay of exact known control and frozen source hashes."""

import json

from workflow_bridge_control import HERE, SOURCES, audit_case, committed_hash, digest


def verify(directory=HERE / "runs/workflow_bridge"):
    receipt = json.loads((directory / "receipt_start.json").read_text())
    result = json.loads((directory / "result.json").read_text())
    protocol = json.loads((HERE / "workflow_bridge_protocol.json").read_text())
    assert set(receipt["source_hashes"]) == set(SOURCES)
    assert all(result[key] == value for key, value in receipt.items())
    for name, expected in receipt["source_hashes"].items():
        assert digest(HERE / name) == committed_hash(receipt["source_sha"], name) == expected
    for name in ("lc_scalar_components.py", "lc_scalar_check.py", "lc_certificate_check.py"):
        assert receipt["source_hashes"][name] == committed_hash(protocol["source_r8"], name)
    assert digest(directory / "raw.jsonl") == result["raw_sha256"]
    stored = [json.loads(line) for line in (directory / "raw.jsonl").read_text().splitlines()]
    assert stored == [audit_case(case, protocol) for case in protocol["cases"]]
    assert len(stored) == result["completed_cases"] == 2
    assert result["status"] == "known_boundary_confirmed" and result["failure"] is None
    assert result["novel_discovery"] is False and result["real_workflows"] == 0
    return {"status": "exact_known_boundary_replayed", "source_sha": receipt["source_sha"],
            "ratios": {r["id"]: r["fixed_z_failure_ratio_after_over_before"] for r in stored},
            "novel_discovery": False, "real_workflows": 0}


if __name__ == "__main__":
    print(json.dumps(verify(), indent=2))
