"""Versioned header-only correction around the unchanged frozen intake profiler."""

import argparse
from copy import deepcopy
from datetime import datetime, timezone
import json
from pathlib import Path
import platform
import subprocess
import time

from workflow_intake_audit import (
    HERE, ROOT, SOURCES as BASE_SOURCES, canonical, digest, incidents_profile,
    license_profile, safe_members, sms_profile, verify_provenance,
)

SOURCES = (*BASE_SOURCES, "workflow_intake_amendment_v2.json", "workflow_intake_v2.py",
           "test_workflow_intake_v2.py", "WORKFLOW_INTAKE_AMENDMENT_V2.md")
FIRST = HERE / "runs/workflow_intake_v1"


def git(*args):
    return subprocess.check_output(["git", *args], cwd=ROOT)


def effective_protocol(base, amendment):
    updated = deepcopy(base)
    expected = deepcopy(base)
    expected["lanes"]["incidents"]["expected_columns"][32] = "closed_code"
    expected["lanes"]["incidents"]["future_sensitive_columns"][3] = "closed_code"
    if len(amendment["patches"]) != 2:
        raise ValueError("amendment must contain exactly the two field-name references")
    for patch in amendment["patches"]:
        target = updated
        for key in patch["path"][:-1]:
            target = target[key]
        key = patch["path"][-1]
        if target[key] != patch["old"] or patch["old"] != "close_code" or patch["new"] != "closed_code":
            raise ValueError("amendment precondition or scope mismatch")
        target[key] = patch["new"]
    if updated != expected:
        raise ValueError("change outside the single field alias")
    return updated


def original_integrity(amendment):
    pins = amendment["evidence"]
    expected = {"result.json": pins["first_result_sha256"], "sms.split.jsonl": pins["first_sms_split_sha256"],
                "incidents.split.jsonl": pins["first_incident_split_sha256"]}
    for name, value in expected.items():
        if digest((FIRST / name).read_bytes()) != value:
            raise ValueError("original failed audit was changed")
    result = json.loads((FIRST / "result.json").read_text())
    if result["lanes"]["incidents"]["profile"]["schema_accepted"] is not False:
        raise ValueError("original schema failure not preserved")
    for name in BASE_SOURCES:
        data = (HERE / name).read_bytes()
        committed = git("show", f'{amendment["base_source_sha"]}:research/breakthrough/{name}')
        if digest(data) != digest(committed) or digest(data) != result["source_hashes"][name]:
            raise ValueError("frozen v1 source changed")
    if digest((HERE / "workflow_intake_protocol.json").read_bytes()) != amendment["base_protocol_sha256"]:
        raise ValueError("base protocol digest mismatch")
    return result


def reconstruct(directory, protocol, amendment):
    original = original_integrity(amendment)
    output, splits = {}, {}
    for lane, config in protocol["lanes"].items():
        path = directory / config["archive_name"]
        if path.stat().st_size > protocol["limits"]["archive_bytes"]:
            raise ValueError("archive exceeds bound")
        blob = path.read_bytes()
        provenance = verify_provenance(directory, lane, protocol, blob)
        if provenance != original["lanes"][lane]["provenance"]:
            raise ValueError("different archive or provenance than original intake")
        members = safe_members(blob, lane, protocol)
        profiler = sms_profile if lane == "sms" else incidents_profile
        profile, split = profiler(members[config["data_member"]], protocol)
        splits[lane] = ("".join(canonical(record) + "\n" for record in split)).encode()
        output[lane] = {"status": "profiled_not_baseline_admitted", "provenance": provenance,
                        "members": {name: {"sha256": digest(data), "bytes": len(data)} for name, data in members.items()},
                        "license": license_profile(members, lane, protocol), "profile": profile,
                        "split_sha256": digest(splits[lane])}
    if output["sms"] != original["lanes"]["sms"] or splits["sms"] != (FIRST / "sms.split.jsonl").read_bytes():
        raise ValueError("SMS profile or immutable split changed under incident-only amendment")
    return output, splits


def run(directory, output):
    if git("status", "--porcelain").strip():
        raise RuntimeError("freeze a clean source commit before the amended profile")
    sha = git("rev-parse", "HEAD").decode().strip()
    hashes = {name: digest((HERE / name).read_bytes()) for name in SOURCES}
    for name, value in hashes.items():
        if digest(git("show", f"{sha}:research/breakthrough/{name}")) != value:
            raise ValueError("current source not frozen")
    amendment = json.loads((HERE / "workflow_intake_amendment_v2.json").read_text())
    base = json.loads((HERE / "workflow_intake_protocol.json").read_text())
    protocol = effective_protocol(base, amendment)
    original_integrity(amendment)
    output.mkdir(parents=True, exist_ok=False)
    receipt = {"source_sha": sha, "source_hashes": hashes, "effective_protocol_sha256": digest(canonical(protocol).encode()),
               "started_utc": datetime.now(timezone.utc).isoformat(), "python": platform.python_version(),
               "amendment": amendment["amendment_id"], "first_result_sha256": amendment["evidence"]["first_result_sha256"]}
    (output / "receipt_start.json").write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8", newline="\n")
    start = time.monotonic()
    try:
        lanes, splits = reconstruct(directory, protocol, amendment)
        for lane, data in splits.items():
            (output / f"{lane}.split.jsonl").write_bytes(data)
        result = {**receipt, "status": "amended_profile_completed_not_baseline_admitted", "lanes": lanes,
                  "seconds": time.monotonic() - start, "human_terms_review": "pending_actual_human_review",
                  "training_runs": 0, "scoring_runs": 0, "baseline_admitted": False,
                  "scientific_breakthrough_gate": False, "mass_indispensability_gate": False}
    except Exception as error:
        result = {**receipt, "status": "amended_intake_failed", "error_type": type(error).__name__,
                  "reason": "check local inputs or frozen amendment without disclosing raw records",
                  "seconds": time.monotonic() - start, "training_runs": 0, "scoring_runs": 0}
        (output / "result.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8", newline="\n")
        raise RuntimeError("amended intake failed; original and new failure preserved") from None
    (output / "result.json").write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n")
    return {"status": result["status"], "source_sha": sha, "seconds": result["seconds"],
            "lanes": {lane: {"rows": info["profile"]["rows"], "split_sha256": info["split_sha256"]}
                      for lane, info in lanes.items()}}


def verify(directory, output):
    receipt = json.loads((output / "receipt_start.json").read_text())
    result = json.loads((output / "result.json").read_text())
    if set(receipt["source_hashes"]) != set(SOURCES) or any(result[key] != value for key, value in receipt.items()):
        raise ValueError("receipt mismatch")
    for name, expected in receipt["source_hashes"].items():
        if digest((HERE / name).read_bytes()) != expected or digest(git("show", f'{receipt["source_sha"]}:research/breakthrough/{name}')) != expected:
            raise ValueError("frozen source mismatch")
    amendment = json.loads((HERE / "workflow_intake_amendment_v2.json").read_text())
    base = json.loads((HERE / "workflow_intake_protocol.json").read_text())
    protocol = effective_protocol(base, amendment)
    if digest(canonical(protocol).encode()) != receipt["effective_protocol_sha256"]:
        raise ValueError("effective protocol mismatch")
    lanes, splits = reconstruct(directory, protocol, amendment)
    if lanes != result["lanes"]:
        raise ValueError("profile reconstruction mismatch")
    for lane, data in splits.items():
        if (output / f"{lane}.split.jsonl").read_bytes() != data:
            raise ValueError("immutable split mismatch")
    if result["training_runs"] or result["scoring_runs"] or result["baseline_admitted"]:
        raise ValueError("scope violation")
    return {"status": "amended_intake_full_replay_pass", "source_sha": receipt["source_sha"], "baseline_admitted": False}


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--archive-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--verify", action="store_true")
    args = parser.parse_args()
    print(json.dumps(verify(args.archive_dir, args.output) if args.verify else run(args.archive_dir, args.output), indent=2))
