"""Read-only independent certificate and provenance audit of frozen R5."""

from collections import Counter
import hashlib
import json
import time

from experiment_r1 import HERE, digest
from lc_certificate_check import dense_pbb, verify_certificate
from verify_evidence import committed_hash


def verify():
    started = time.perf_counter()
    directory = HERE / "runs/r5"
    receipt = json.loads((directory / "receipt_start.json").read_text())
    result = json.loads((directory / "result.json").read_text())
    assert all(result[k] == v for k, v in receipt.items())
    for path, expected in receipt["hashes"].items():
        assert committed_hash(receipt["source_sha"], path) == expected, path
        assert digest(HERE / path) == expected, "audit must use frozen inputs and checker"
    assert digest(directory / "raw.jsonl") == result["raw_sha256"]
    protocol = json.loads((HERE / "protocol_r5.json").read_text())
    data = (HERE / "external/qcode_catalog.jsonl").read_bytes()
    blob = hashlib.sha1(b"blob " + str(len(data)).encode() + b"\0" + data).hexdigest()
    assert blob == protocol["catalog_git_blob"]
    catalog = [json.loads(line) for line in data.decode().splitlines()]
    raw = [json.loads(line) for line in (directory / "raw.jsonl").read_text().splitlines()]
    expected_order = sorted(range(1, len(catalog) + 1), key=lambda i: (catalog[i - 1]["n"], i))
    assert [r["source_line"] for r in raw] == expected_order
    assert len(raw) == len(catalog) == protocol["catalog_records"] == 368
    counts, certificates, sizes = Counter(), Counter(), Counter()
    hidden, uniform_positive, max_pairs = [], 0, 0
    for row in raw:
        source = catalog[row["source_line"] - 1]
        assert row["record_key"] == f"line-{row['source_line']:04d}"
        assert row["upstream_code_id"] == source.get("code_id")
        assert row["upstream_lc_any"] == source["lc_any"]
        assert row["n"] == source["n"] == 2 * source["ell"] * source["m"]
        assert row["k"] == source["k"] == row["n"] - row["candidate"]["stabilizer_rank"]
        matrix = dense_pbb(source)
        checked = verify_certificate(matrix, row["candidate"])
        assert checked == row["independent_check"]
        status = row["candidate"]["status"]
        counts[status] += 1
        sizes[row["n"]] += 1
        certificates[checked] += 1
        max_pairs = max(max_pairs, len(row["candidate"].get("constraints", [])))
        if status == "css_equivalent" and not source["lc_any"]:
            hidden.append(row["record_key"])
        if source["lc_any"]:
            assert status == "css_equivalent"
        if row["uniform_baseline"]["status"] == "css_equivalent":
            uniform_positive += 1
            verify_certificate(matrix, {**row["candidate"], **row["uniform_baseline"]})
    assert counts == result["counts"] == {"not_lc_css": 357, "css_equivalent": 11}
    assert sum(certificates.values()) == 368 and result["coverage"] == 1.
    assert hidden == result["hidden_css_ids"] == []
    assert result["practical_coverage_prediction"] is True
    assert result["hidden_css_prediction"] == "rejected"
    assert result["status"] == "complete_catalog_audit"
    assert result["records_attempted"] == result["records_total"] == 368
    assert result["scientific_breakthrough_gate"] is False and result["mass_indispensability_gate"] is False
    print(json.dumps({"status": "R5_all_certificates_and_provenance_verified",
                      "source_sha": receipt["source_sha"], "records": len(raw),
                      "certificates": dict(certificates), "sizes": dict(sizes),
                      "uniform_two_block_positives": uniform_positive,
                      "maximum_negative_certificate_pairs": max_pairs,
                      "elapsed_seconds": time.perf_counter() - started,
                      "independent_investigator_or_novelty_clearance": False}, indent=2))


if __name__ == "__main__":
    verify()
