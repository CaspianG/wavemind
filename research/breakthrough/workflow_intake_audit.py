"""Offline, bounded public-archive intake. Never downloads or trains a model."""

import argparse
from collections import Counter, defaultdict
import csv
from datetime import datetime
import hashlib
import io
import json
from pathlib import Path, PurePosixPath
import re
import stat
import subprocess
import sys
import unicodedata
from urllib.parse import urlsplit
from zipfile import BadZipFile, ZipFile

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
SOURCES = ("workflow_intake_protocol.json", "workflow_intake_audit.py", "test_workflow_intake.py")


def digest(data):
    return hashlib.sha256(data).hexdigest()


def canonical(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=True, separators=(",", ":"))


def ratio(count, total):
    return {"count": count, "denominator": total, "rate": count / total if total else None}


def normalize(message):
    return " ".join(unicodedata.normalize("NFKC", message).casefold().split())


def assignment(lane, key, protocol):
    rules = protocol["split"]
    token = digest(f'{rules["seed"]}|{lane}|{key}'.encode())
    bucket = int(token[:16], 16) % 10000
    partition = next(name for name, (start, end) in rules["partitions"].items() if start <= bucket < end)
    return digest(f"{lane}|{key}".encode()), partition


def manifest(groups, lane, protocol, excluded=None):
    excluded = excluded or set()
    result = []
    for key, rows in groups.items():
        group, partition = assignment(lane, key, protocol)
        result.append({"group_sha256": group, "partition": partition,
                       "source_rows": rows, "eligible": key not in excluded})
    return sorted(result, key=lambda row: row["group_sha256"])


def safe_members(blob, lane, protocol):
    limits, config = protocol["limits"], protocol["lanes"][lane]
    if len(blob) > limits["archive_bytes"]:
        raise ValueError("archive exceeds compressed byte limit")
    with ZipFile(io.BytesIO(blob)) as archive:
        infos = archive.infolist()
        if len(infos) > limits["member_count"] or len({i.filename for i in infos}) != len(infos):
            raise ValueError("too many or duplicate archive members")
        if sum(i.file_size for i in infos) > limits["total_uncompressed_bytes"]:
            raise ValueError("archive exceeds uncompressed byte limit")
        members = {}
        for info in infos:
            name = info.filename
            path = PurePosixPath(name)
            if (path.is_absolute() or ".." in path.parts or "\\" in name or ":" in name
                    or name not in config["allowed_members"] or info.flag_bits & 1
                    or stat.S_ISLNK(info.external_attr >> 16)):
                raise ValueError("unsafe, encrypted or unexpected archive member")
            limit = limits["total_uncompressed_bytes"] if name == config["data_member"] else limits["readme_bytes"]
            if info.file_size > limit:
                raise ValueError("archive member exceeds its byte limit")
            with archive.open(info) as stream:
                data = stream.read(limit + 1)
            if len(data) != info.file_size or len(data) > limit:
                raise ValueError("invalid member size")
            members[name] = data
    if config["data_member"] not in members:
        raise ValueError("required data member absent")
    if config["required_readme"] and "readme" not in members:
        raise ValueError("required bundled readme absent")
    return members


def license_profile(members, lane, protocol):
    data_member = protocol["lanes"][lane]["data_member"]
    terms = []
    for name, blob in members.items():
        if name == data_member:
            continue
        text = blob.decode("utf-8", errors="replace").casefold()
        flags = [term for term in ("research only", "non-commercial", "noncommercial",
                                  "permission", "copyright", "license", "licence") if term in text]
        terms.append({"member": name, "sha256": digest(blob), "bytes": len(blob), "review_flags": flags})
    return {"source_license": "CC-BY-4.0", "bundled_terms": terms,
            "human_terms_review": "pending", "baseline_admitted": False}


def sms_profile(blob, protocol):
    rules = protocol["lanes"]["sms"]
    lines = blob.decode("utf-8-sig").splitlines()
    if len(lines) > protocol["limits"]["max_rows"]:
        raise ValueError("too many SMS rows")
    groups, labels, raw_counts, templates = defaultdict(list), defaultdict(set), Counter(), defaultdict(set)
    partitions = defaultdict(Counter)
    invalid, empty = [], 0
    lengths = []
    for number, line in enumerate(lines, 1):
        raw_counts[digest(line.encode())] += 1
        label, separator, message = line.partition("\t")
        if not separator or label not in rules["allowed_labels"]:
            invalid.append(number)
            continue
        key = normalize(message)
        empty += not bool(key)
        lengths.append(len(message))
        groups[key].append(number)
        labels[key].add(label)
        partition = assignment("sms", key, protocol)[1]
        partitions[partition][label] += 1
        templates[re.sub(r"\d+", "<NUM>", key)].add(key)
    conflicts = {key for key in groups if len(labels[key]) > 1}
    excluded = conflicts | ({""} if "" in groups else set())
    split = manifest(groups, "sms", protocol, excluded)
    template_cross = [keys for keys in templates.values()
                      if len({assignment("sms", key, protocol)[1] for key in keys}) > 1]
    normalization_cross = sum(len({assignment("sms", key, protocol)[1] for _ in rows}) > 1
                              for key, rows in groups.items())
    balance = {p: {label: ratio(counts[label], sum(counts.values())) for label in rules["allowed_labels"]}
               for p, counts in sorted(partitions.items())}
    return {"rows": len(lines), "source_reported_rows": rules["published_rows"],
            "source_count_delta": len(lines) - rules["published_rows"],
            "valid_labelled_rows": sum(map(len, groups.values())), "malformed_rows": invalid,
            "empty_message": ratio(empty, len(lines)), "message_length_min_max": [min(lengths), max(lengths)] if lengths else None,
            "exact_duplicate_excess": ratio(sum(v - 1 for v in raw_counts.values()), len(lines)),
            "normalized_groups": len(groups), "normalized_duplicate_excess": ratio(sum(len(v) - 1 for v in groups.values()), len(lines)),
            "conflicting_label_groups": len(conflicts), "quarantined_group_rows": sum(len(groups[k]) for k in excluded),
            "class_balance_by_partition": balance, "group_partition_overlap": normalization_cross,
            "digit_template_cross_partition_groups": len(template_cross),
            "digit_template_cross_partition_rows": sum(len(groups[k]) for keys in template_cross for k in keys),
            "temporal_leakage_assessment": "unavailable: no reliable timestamps/sender/source-member labels",
            "schema_drift": "single archive only; line-shape validity measured, cross-version drift unavailable",
            "baseline_scoring_admitted": False}, split


def parse_time(value, rules):
    if value in rules["missing_markers"]:
        return None
    for template in rules["timestamp_formats"]:
        try:
            return datetime.strptime(value, template)
        except ValueError:
            pass
    raise ValueError("timestamp does not match the frozen formats")


def incidents_profile(blob, protocol):
    rules = protocol["lanes"]["incidents"]
    reader = csv.reader(io.StringIO(blob.decode("utf-8-sig"), newline=""))
    header = next(reader, [])
    if header != rules["expected_columns"]:
        return {"schema_accepted": False, "observed_column_count": len(header),
                "header_sha256": digest(canonical(header).encode()),
                "missing_expected_columns": [name for name in rules["expected_columns"] if name not in header],
                "reason": "header differs from frozen ordered contract", "baseline_scoring_admitted": False}, []
    groups, states, missing, invalid = defaultdict(list), defaultdict(Counter), Counter(), Counter()
    monthly, partition_missing = defaultdict(Counter), defaultdict(Counter)
    exact, keys, previous, ranges = Counter(), defaultdict(set), {}, {}
    regressions, impacted, future = Counter(), defaultdict(set), Counter()
    shape_errors, missing_ids, total, dates_present = [], [], 0, Counter()
    for number, values in enumerate(reader, 1):
        total = number
        if total > protocol["limits"]["max_rows"]:
            raise ValueError("too many incident rows")
        if len(values) != len(header):
            shape_errors.append(number)
            continue
        row = dict(zip(header, values, strict=True))
        identity = row["number"]
        if identity in rules["missing_markers"]:
            missing_ids.append(number)
            partition = "unassigned"
        else:
            groups[identity].append(number)
            partition = assignment("incidents", identity, protocol)[1]
        state_value = row["incident_state"]
        allowed_states = {"New", "Active", "Resolved", "Closed", "Canceled", "Awaiting User Info",
                          "Awaiting Problem", "Awaiting Evidence", "Awaiting Vendor", "Awaiting Change"}
        state_label = state_value if state_value in allowed_states else "unrecognized:" + digest(state_value.encode())[:16]
        states[partition][state_label] += 1
        row_digest = digest(canonical(values).encode())
        exact[row_digest] += 1
        for name, value in row.items():
            if value in rules["missing_markers"]:
                missing[name] += 1
                partition_missing[partition][name] += 1
        for name in rules["integer_columns"]:
            if row[name] not in rules["missing_markers"] and not re.fullmatch(r"\d+", row[name]):
                invalid[name] += 1
        for name in rules["boolean_columns"]:
            if row[name] not in rules["missing_markers"] and row[name].casefold() not in ("true", "false"):
                invalid[name] += 1
        dates = {}
        for name in rules["timestamp_columns"]:
            try:
                dates[name] = parse_time(row[name], rules)
            except ValueError:
                dates[name] = None
                invalid[name] += 1
            value = dates[name]
            if value is not None:
                dates_present[name] += 1
                low, high = ranges.get(name, (value, value))
                ranges[name] = min(low, value), max(high, value)
        update = dates["sys_updated_at"]
        count = int(row["sys_mod_count"]) if re.fullmatch(r"\d+", row["sys_mod_count"]) else None
        if update is not None:
            month = update.strftime("%Y-%m")
            monthly[month]["rows"] += 1
            monthly[month]["state:" + state_label] += 1
            for name in rules["timestamp_columns"]:
                if row[name] in rules["missing_markers"]:
                    monthly[month]["missing:" + name] += 1
            for name in ("resolved_at", "closed_at"):
                if dates[name] is not None and dates[name] > update:
                    future[name + "_after_record_update"] += 1
            if dates["opened_at"] is not None and update < dates["opened_at"]:
                future["update_before_opened"] += 1
        if identity not in rules["missing_markers"]:
            keys[(identity, row["sys_updated_at"], row["sys_mod_count"])].add(row_digest)
            old_time, old_count = previous.get(identity, (None, None))
            for name, condition in (("timestamp", update is not None and old_time is not None and update < old_time),
                                    ("update_counter", count is not None and old_count is not None and count < old_count)):
                if condition:
                    regressions[name] += 1
                    impacted[name].add(identity)
            previous[identity] = update if update is not None else old_time, count if count is not None else old_count
    split = manifest(groups, "incidents", protocol)
    partition_rows = {p: sum(counter.values()) for p, counter in states.items()}
    parsed_rows = sum(partition_rows.values())
    return {"schema_accepted": True, "columns": header, "rows": total,
            "source_reported_rows": rules["published_rows"], "source_count_delta": total - rules["published_rows"],
            "incidents": len(groups), "source_reported_incidents": rules["published_incidents"],
            "row_width_errors": shape_errors, "missing_identifier_rows": missing_ids,
            "parsed_rows": parsed_rows,
            "missingness": {name: ratio(missing[name], parsed_rows) for name in header},
            "missingness_by_partition": {p: {name: ratio(counter[name], partition_rows[p]) for name in header}
                                         for p, counter in partition_missing.items()},
            "invalid_values": dict(invalid),
            "exact_duplicate_excess": ratio(sum(v - 1 for v in exact.values()), total),
            "conflicting_equal_event_keys": sum(len(values) > 1 for values in keys.values()),
            "within_incident_file_order_regressions": dict(regressions),
            "incidents_with_regressions": {k: len(v) for k, v in impacted.items()},
            "future_outcome_values": dict(future), "date_nonmissing_valid": dict(dates_present),
            "timestamp_ranges_naive_source_timezone_unknown": {k: [v.isoformat() for v in pair] for k, pair in ranges.items()},
            "state_balance_by_partition": {p: {state: ratio(count, partition_rows[p]) for state, count in sorted(counter.items())}
                                           for p, counter in sorted(states.items())},
            "monthly_profile": {month: dict(counts) for month, counts in sorted(monthly.items())},
            "schema_drift": "single snapshot; header/row shape checked, cross-version drift unavailable",
            "online_feature_availability": "not established; enriched fields are not proof of event-time observability",
            "baseline_scoring_admitted": False}, split


def verify_provenance(directory, lane, protocol, archive_blob):
    config = protocol["lanes"][lane]
    record = json.loads((directory / f"{lane}.provenance.json").read_text(encoding="utf-8"))
    if record["source_page"] != config["source_page"] or record["archive_sha256"] != digest(archive_blob):
        raise ValueError("source/archive provenance mismatch")
    parsed = urlsplit(record["archive_url"])
    if parsed.scheme != "https" or parsed.hostname != "archive.ics.uci.edu" or not parsed.path.endswith(".zip"):
        raise ValueError("archive URL is not the official HTTPS ZIP origin")
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ValueError("unexpected credentials/query in archive URL")
    timestamp = datetime.fromisoformat(record["retrieved_utc"].replace("Z", "+00:00"))
    if timestamp.utcoffset() is None or timestamp.utcoffset().total_seconds() != 0:
        raise ValueError("retrieval time must carry UTC offset")
    if not record["retrieval_method"] or record["license"] != config["documented_license"]:
        raise ValueError("missing retrieval method or license mismatch")
    snapshot_path = directory / f"{lane}.source.html"
    if snapshot_path.stat().st_size > 5000000:
        raise ValueError("source snapshot exceeds limit")
    snapshot = snapshot_path.read_bytes()
    if len(snapshot) > 5000000 or digest(snapshot) != record["source_snapshot_sha256"]:
        raise ValueError("source snapshot mismatch or limit exceeded")
    if b"creativecommons.org/licenses/by/4.0" not in snapshot:
        raise ValueError("expected official license link absent from snapshot")
    if record["archive_url"].encode() not in snapshot and parsed.path.encode() not in snapshot:
        raise ValueError("archive link not present in official source snapshot")
    return {key: record[key] for key in ("source_page", "archive_url", "archive_sha256", "retrieved_utc",
                                        "retrieval_method", "license", "source_snapshot_sha256")}


def source_pins():
    if subprocess.check_output(["git", "status", "--porcelain"], cwd=ROOT).strip():
        raise RuntimeError("freeze source changes before intake")
    sha = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT).decode().strip()
    hashes = {name: digest((HERE / name).read_bytes()) for name in SOURCES}
    for name, expected in hashes.items():
        committed = subprocess.check_output(["git", "show", f"{sha}:research/breakthrough/{name}"], cwd=ROOT)
        if digest(committed) != expected:
            raise RuntimeError("frozen source differs from current bytes")
    return {"source_sha": sha, "source_hashes": hashes}


def audit(directory, output):
    pins = source_pins()
    protocol = json.loads((HERE / "workflow_intake_protocol.json").read_text())
    output.mkdir(parents=True, exist_ok=False)
    results = {}
    for lane, config in protocol["lanes"].items():
        try:
            path = directory / config["archive_name"]
            if path.stat().st_size > protocol["limits"]["archive_bytes"]:
                raise ValueError("archive exceeds compressed limit")
            archive_blob = path.read_bytes()
            provenance = verify_provenance(directory, lane, protocol, archive_blob)
            members = safe_members(archive_blob, lane, protocol)
            profiler = sms_profile if lane == "sms" else incidents_profile
            profile, split = profiler(members[config["data_member"]], protocol)
            split_blob = ("".join(canonical(row) + "\n" for row in split)).encode()
            (output / f"{lane}.split.jsonl").write_bytes(split_blob)
            results[lane] = {"status": "profiled_not_baseline_admitted", "provenance": provenance,
                             "members": {name: {"sha256": digest(blob), "bytes": len(blob)} for name, blob in members.items()},
                             "license": license_profile(members, lane, protocol),
                             "profile": profile, "split_sha256": digest(split_blob)}
        except (OSError, ValueError, KeyError, BadZipFile) as error:
            # Do not expose raw CSV/message content through exceptions.
            results[lane] = {"status": "intake_not_completed", "error_type": type(error).__name__,
                             "reason": "missing/incompatible local intake or provenance; inspect local prerequisites without printing raw records"}
    result = {**pins, "lanes": results, "training_runs": 0, "scoring_runs": 0,
              "scientific_breakthrough_gate": False, "mass_indispensability_gate": False}
    (output / "result.json").write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    return result


def verify_run(directory, output):
    """Read-only full reconstruction; no network, source writes or model scores."""
    result = json.loads((output / "result.json").read_text())
    protocol = json.loads((HERE / "workflow_intake_protocol.json").read_text())
    if set(result["source_hashes"]) != set(SOURCES):
        raise ValueError("source manifest mismatch")
    for name, expected in result["source_hashes"].items():
        committed = subprocess.check_output(["git", "show", f'{result["source_sha"]}:research/breakthrough/{name}'], cwd=ROOT)
        if digest(committed) != expected or digest((HERE / name).read_bytes()) != expected:
            raise ValueError("source hash mismatch")
    for lane, stored in result["lanes"].items():
        if stored["status"] != "profiled_not_baseline_admitted":
            raise ValueError("cannot certify an uncompleted intake")
        config = protocol["lanes"][lane]
        path = directory / config["archive_name"]
        if path.stat().st_size > protocol["limits"]["archive_bytes"]:
            raise ValueError("archive size limit")
        archive_blob = path.read_bytes()
        if verify_provenance(directory, lane, protocol, archive_blob) != stored["provenance"]:
            raise ValueError("provenance mismatch")
        members = safe_members(archive_blob, lane, protocol)
        member_hashes = {name: {"sha256": digest(blob), "bytes": len(blob)} for name, blob in members.items()}
        if member_hashes != stored["members"] or license_profile(members, lane, protocol) != stored["license"]:
            raise ValueError("member or license record mismatch")
        profiler = sms_profile if lane == "sms" else incidents_profile
        profile, split = profiler(members[config["data_member"]], protocol)
        expected_split = ("".join(canonical(row) + "\n" for row in split)).encode()
        if profile != stored["profile"] or (output / f"{lane}.split.jsonl").read_bytes() != expected_split:
            raise ValueError("profile or exact split changed")
        if digest(expected_split) != stored["split_sha256"]:
            raise ValueError("split hash mismatch")
    if set(result["lanes"]) != set(protocol["lanes"]) or result["training_runs"] != 0 or result["scoring_runs"] != 0:
        raise ValueError("run scope mismatch")
    return {"status": "intake_read_only_replay_pass", "baseline_admitted": False}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--verify", action="store_true")
    args = parser.parse_args()
    if args.verify:
        print(json.dumps(verify_run(args.archive_dir, args.output)))
        sys.exit(0)
    outcome = audit(args.archive_dir, args.output)
    print(json.dumps(outcome, indent=2))
    if any(value["status"] != "profiled_not_baseline_admitted" for value in outcome["lanes"].values()):
        sys.exit(2)
