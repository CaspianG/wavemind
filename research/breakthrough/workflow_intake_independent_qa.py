"""Read-only pandas cross-check, independent of the frozen intake implementation.

No archive extraction, model fitting, scoring, network, or raw-record output.
Run with bundled Python; stdout is an aggregate QA receipt.
"""

import argparse
from collections import Counter
import hashlib
import io
import json
from pathlib import Path
import re
import unicodedata
import zipfile

import pandas as pd

HERE = Path(__file__).resolve().parent


def sha(blob):
    return hashlib.sha256(blob).hexdigest()


def audit(archive_dir, run_dir):
    result = json.loads((run_dir / "result.json").read_text())
    checks = []

    def equal(name, actual, expected):
        if actual != expected:
            raise AssertionError(name)
        checks.append(name)

    frames = {}
    for lane, member in (("sms", "SMSSpamCollection"), ("incidents", "incident_event_log.csv")):
        archive = (archive_dir / f"{lane}.zip").read_bytes()
        # Bound reads before decompression, independently of the main harness.
        assert len(archive) <= 5_000_000
        with zipfile.ZipFile(io.BytesIO(archive)) as z:
            assert sum(x.file_size for x in z.infolist()) <= 60_000_000
            blob = z.read(member)
        equal(f"{lane}.member_hash", sha(blob), result["lanes"][lane]["members"][member]["sha256"])
        provenance = json.loads((archive_dir / f"{lane}.provenance.json").read_text())
        equal(f"{lane}.archive_hash", sha(archive), provenance["archive_sha256"])
        if lane == "sms":
            lines = blob.decode("utf-8-sig").splitlines()
            fields = [line.split("\t", 1) for line in lines]
            frame = pd.DataFrame(fields, columns=["label", "message"])
            frame["key"] = frame.message.map(lambda x: " ".join(unicodedata.normalize("NFKC", x).casefold().split()))
            profile = result["lanes"][lane]["profile"]
            equal("sms.exact_duplicates", len(lines) - len(set(lines)), profile["exact_duplicate_excess"]["count"])
            equal("sms.normalized_duplicates", int(frame.key.duplicated().sum()), profile["normalized_duplicate_excess"]["count"])
            equal("sms.conflicting_labels", int((frame.groupby("key").label.nunique() > 1).sum()), profile["conflicting_label_groups"])
        else:
            frame = pd.read_csv(io.BytesIO(blob), dtype=str, keep_default_na=False)
            frame["key"] = frame.number
        frames[lane] = frame
        profile = result["lanes"][lane]["profile"]
        equal(f"{lane}.rows", len(frame), profile["rows"])
        split_blob = (run_dir / f"{lane}.split.jsonl").read_bytes()
        equal(f"{lane}.split_hash", sha(split_blob), result["lanes"][lane]["split_sha256"])
        manifest = [json.loads(line) for line in split_blob.splitlines()]
        equal(f"{lane}.group_count", len(manifest), int(frame.key.nunique()))
        groups = {item["group_sha256"]: item for item in manifest}
        equal(f"{lane}.unique_group_digests", len(groups), len(manifest))
        rows_seen = []
        partitions = {}
        for key, indices in frame.groupby("key", sort=False).groups.items():
            item = groups[sha(f"{lane}|{key}".encode())]
            bucket = int(sha(f"wavemind-public-intake-v1|{lane}|{key}".encode())[:16], 16) % 10000
            partition = "train" if bucket < 7000 else "development" if bucket < 8500 else "evaluation"
            assert item["partition"] == partition
            assert item["source_rows"] == [int(i) + 1 for i in indices]
            assert item["eligible"] is True
            rows_seen.extend(item["source_rows"])
            partitions[key] = partition
        equal(f"{lane}.exact_row_coverage", sorted(rows_seen), list(range(1, len(frame) + 1)))
        checks.append(f"{lane}.every_group_assignment_and_membership")
        frame["partition"] = frame.key.map(partitions)

    sms = frames["sms"]
    sp = result["lanes"]["sms"]["profile"]
    templates = sms.key.map(lambda s: re.sub(r"\d+", "<NUM>", s))
    crossed = sms.groupby(templates).partition.nunique()
    crossed = crossed[crossed > 1].index
    equal("sms.template_crossing_groups", len(crossed), sp["digit_template_cross_partition_groups"])
    equal("sms.template_crossing_rows", int(templates.isin(crossed).sum()), sp["digit_template_cross_partition_rows"])
    for part, balance in sp["class_balance_by_partition"].items():
        subset = sms[sms.partition == part]
        for label, metric in balance.items():
            equal(f"sms.{part}.{label}", int((subset.label == label).sum()), metric["count"])
            equal(f"sms.{part}.{label}.denominator", len(subset), metric["denominator"])

    incidents = frames["incidents"]
    ip = result["lanes"]["incidents"]["profile"]
    equal("incidents.unique_ids", int(incidents.number.nunique()), ip["incidents"])
    equal("incidents.exact_duplicates", int(incidents[ip["columns"]].duplicated().sum()), ip["exact_duplicate_excess"]["count"])
    missing = incidents[ip["columns"]].isin(["", "?"])
    for col, metric in ip["missingness"].items():
        equal(f"incidents.missing.{col}", int(missing[col].sum()), metric["count"])
        equal(f"incidents.missing.{col}.denominator", len(incidents), metric["denominator"])
    for part, metrics in ip["missingness_by_partition"].items():
        selector = incidents.partition == part
        for col, metric in metrics.items():
            equal(f"incidents.{part}.missing.{col}", int(missing.loc[selector, col].sum()), metric["count"])
            equal(f"incidents.{part}.missing.{col}.denominator", int(selector.sum()), metric["denominator"])
    dates = {}
    for col in ip["date_nonmissing_valid"]:
        dates[col] = pd.to_datetime(incidents[col].mask(missing[col]), format="mixed", dayfirst=True, errors="coerce")
        equal(f"incidents.valid_dates.{col}", int(dates[col].notna().sum()), ip["date_nonmissing_valid"][col])
    for label, left, right in (("closed_at_after_record_update", "closed_at", "sys_updated_at"), ("resolved_at_after_record_update", "resolved_at", "sys_updated_at"), ("update_before_opened", "opened_at", "sys_updated_at")):
        equal(f"incidents.{label}", int((dates[left] > dates[right]).sum()), ip["future_outcome_values"][label])
    for kind, values in (("timestamp", dates["sys_updated_at"]), ("update_counter", pd.to_numeric(incidents.sys_mod_count))):
        previous = values.groupby(incidents.number).ffill().groupby(incidents.number).shift()
        regresses = values < previous
        equal(f"incidents.regression.{kind}", int(regresses.sum()), ip["within_incident_file_order_regressions"][kind])
        equal(f"incidents.regression_entities.{kind}", int(incidents.loc[regresses, "number"].nunique()), ip["incidents_with_regressions"][kind])
    # Exact equal-key conflicts: distinct complete rows within each event key.
    unique_rows = incidents[ip["columns"]].drop_duplicates()
    sizes = unique_rows.groupby(["number", "sys_updated_at", "sys_mod_count"]).size()
    equal("incidents.equal_key_conflicts", int((sizes > 1).sum()), ip["conflicting_equal_event_keys"])
    return {"status": "independent_pandas_quality_crosscheck_pass", "pandas_version": pd.__version__,
            "checked_result_sha256": sha((run_dir / "result.json").read_bytes()),
            "qa_source_sha256": sha(Path(__file__).read_bytes()), "checks_passed": len(checks), "checks": checks,
            "partition_rows": {lane: dict(Counter(frame.partition)) for lane, frame in frames.items()},
            "limitations": ["same local source files; not independent source authentication or external investigator", "no actual human terms review", "no model scoring or scientific/product admission"],
            "baseline_admitted": False}


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--archive-dir", type=Path, required=True)
    parser.add_argument("--run-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    report = audit(args.archive_dir, args.run_dir)
    if args.output:
        with args.output.open("x", encoding="utf-8", newline="\n") as stream:
            stream.write(json.dumps(report, indent=2) + "\n")
    print(json.dumps({key: value for key, value in report.items() if key != "checks"}, indent=2))
