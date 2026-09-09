"""Frozen public-catalog audit; no network, model endpoint or hardware access."""

import argparse
from collections import Counter
import hashlib
import json
import platform
from pathlib import Path
import time

import numpy as np

from experiment_r1 import HERE, digest, dump, source_identity
from lc_certificate_check import dense_pbb, unpack, verify_certificate
from lc_projector import pbb_rows, solve, uniform_block_baseline


SOURCES = ["protocol_r5.json", "LC_PROJECTOR.md", "lc_projector.py", "lc_certificate_check.py",
           "test_lc_projector.py", "experiment_r5.py", "experiment_r1.py",
           "external/qcode_catalog.jsonl", "external/qcode_source.json", "external/QCODE_LICENSE.txt"]


def ordered_catalog(catalog):
    # Optional upstream IDs are not record identity. Preserve immutable source lines.
    return sorted(({**record, "source_line": i, "record_key": f"line-{i:04d}"}
                   for i, record in enumerate(catalog, start=1)), key=lambda r: (r["n"], r["source_line"]))


def run(output):
    protocol = json.loads((HERE / "protocol_r5.json").read_text())
    catalog_bytes = (HERE / "external/qcode_catalog.jsonl").read_bytes()
    blob = hashlib.sha1(b"blob " + str(len(catalog_bytes)).encode() + b"\0" + catalog_bytes).hexdigest()
    assert blob == protocol["catalog_git_blob"]
    catalog = [json.loads(line) for line in catalog_bytes.decode().splitlines()]
    assert len(catalog) == protocol["catalog_records"]
    catalog = ordered_catalog(catalog)
    receipt = {"source_sha": source_identity(), "started_unix_ns": time.time_ns(),
               "hashes": {f: digest(HERE / f) for f in SOURCES}, "python": platform.python_version(),
               "numpy": np.__version__, "platform": platform.platform(),
               "evidence_class": "public_catalog_exact_algebraic_audit",
               "scientific_breakthrough_gate": False, "mass_indispensability_gate": False}
    output.mkdir(parents=True, exist_ok=False)
    dump(output / "receipt_start.json", receipt)
    started, results = time.perf_counter(), []
    try:
        with (output / "raw.jsonl").open("x", encoding="utf-8", newline="\n") as stream:
            for record in catalog:
                if time.perf_counter() - started > protocol["limits"]["sweep_wall_seconds"]:
                    break
                tick = time.perf_counter()
                n = record["n"]
                assert n == 2 * record["ell"] * record["m"]
                packed, matrix = pbb_rows(record), dense_pbb(record)
                assert np.array_equal(unpack(packed, 2 * n), matrix)
                candidate = solve(packed, n, max_dimension=protocol["limits"]["max_affine_dimension"],
                                  seconds=protocol["limits"]["candidate_seconds_per_code"])
                assert candidate["stabilizer_rank"] == n - record["k"]
                checked = verify_certificate(matrix, candidate)
                base_started = time.perf_counter()
                baseline = uniform_block_baseline(packed, n)
                baseline["elapsed_seconds"] = time.perf_counter() - base_started
                if baseline["status"] == "css_equivalent":
                    verify_certificate(matrix, {**candidate, **baseline})
                    assert candidate["status"] != "not_lc_css"
                if record["lc_any"]:
                    assert candidate["status"] != "not_lc_css", "contradicts published positive"
                row = {"record_key": record["record_key"], "source_line": record["source_line"],
                       "upstream_code_id": record.get("code_id"), "n": n, "k": record["k"],
                       "upstream_lc_any": record["lc_any"], "candidate": candidate,
                       "independent_check": checked, "uniform_baseline": baseline,
                       "total_seconds": time.perf_counter() - tick}
                stream.write(json.dumps(row, separators=(",", ":")) + "\n")
                stream.flush()
                results.append(row)
                if len(results) % 20 == 0:
                    print(json.dumps({"completed": len(results), "seconds": time.perf_counter() - started,
                                      "counts": dict(Counter(r["candidate"]["status"] for r in results))}), flush=True)
        counts = Counter(r["candidate"]["status"] for r in results)
        certified = counts["css_equivalent"] + counts["not_lc_css"]
        hidden = [r["record_key"] for r in results if not r["upstream_lc_any"]
                  and r["candidate"]["status"] == "css_equivalent"]
        complete = len(results) == len(catalog) and counts["unresolved"] == 0
        summary = {**receipt, "status": "complete_catalog_audit" if complete else "partial_catalog_audit",
                   "records_attempted": len(results), "records_total": len(catalog), "counts": dict(counts),
                   "coverage": certified / len(catalog), "hidden_css_ids": hidden,
                   "practical_coverage_prediction": certified / len(catalog) >= .95,
                   "hidden_css_prediction": "confirmed" if hidden else "rejected" if complete else "unresolved",
                   "elapsed_seconds": time.perf_counter() - started, "raw_sha256": digest(output / "raw.jsonl")}
        dump(output / "result.json", summary)
        print(json.dumps({k: v for k, v in summary.items() if k != "hashes"}, indent=2), flush=True)
    except Exception as error:
        dump(output / "failure.json", {**receipt, "status": "execution_failed", "error": repr(error),
                                      "completed_records": len(results), "raw_sha256": digest(output / "raw.jsonl")})
        raise


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True, type=Path)
    run(parser.parse_args().output.resolve())
