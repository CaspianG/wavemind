"""Exact known boundary control; not a simulator benchmark or novelty claim."""

import argparse
from datetime import datetime, timezone
from fractions import Fraction
import hashlib
from itertools import product
import json
from pathlib import Path
import platform
import subprocess

from lc_certificate_check import transformed, unpack
from lc_scalar_check import check
from lc_scalar_components import solve

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
SOURCES = (
    "workflow_bridge_protocol.json", "workflow_bridge_control.py",
    "verify_workflow_bridge.py", "test_workflow_bridge.py",
    "lc_scalar_components.py", "lc_scalar_check.py", "lc_certificate_check.py",
)


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def git(*args):
    return subprocess.check_output(["git", *args], cwd=ROOT)


def committed_hash(sha, name):
    return hashlib.sha256(git("show", f"{sha}:research/breakthrough/{name}")).hexdigest()


def span(rows):
    values = {0}
    for row in rows:
        values |= {value ^ row for value in values}
    return values


def packed(words):
    n = len(words[0])
    return [sum(((c in "XY") << i) | ((c in "ZY") << (n + i))
                for i, c in enumerate(word)) for word in words]


def syndrome(error, rows, n):
    mask = (1 << n) - 1
    return sum(((((error & mask) & (row >> n)).bit_count()
                 + ((error >> n) & (row & mask)).bit_count()) % 2) << i
               for i, row in enumerate(rows))


def parameters(rows, n):
    stabilizer = span(rows)
    if any(syndrome(row, rows, n) for row in rows):
        raise ValueError("noncommuting generators")
    logicals = [e for e in range(1, 1 << (2 * n))
                if e not in stabilizer and syndrome(e, rows, n) == 0]
    return {"n": n, "k": n - (len(stabilizer).bit_length() - 1),
            "d": min((((e | (e >> n)) & ((1 << n) - 1)).bit_count()
                      for e in logicals), default=None)}


def local_image(label, gate):
    x, z = label & 1, label >> 1
    a, b, c, d = gate
    if any(v not in (0, 1) for v in gate) or a * d ^ b * c != 1:
        raise ValueError("not a binary invertible gate")
    return (a * x ^ c * z) | ((b * x ^ d * z) << 1)


def image(error, gates):
    n = len(gates)
    labels = [local_image((error >> i & 1) | ((error >> (n + i) & 1) << 1), gate)
              for i, gate in enumerate(gates)]
    return sum(((label & 1) << i) | ((label >> 1) << (n + i))
               for i, label in enumerate(labels))


def transport(channel, gates):
    output = []
    for distribution, gate in zip(channel, gates, strict=True):
        new = [Fraction(0)] * 4
        for label, probability in enumerate(distribution):
            new[local_image(label, gate)] = probability
        output.append(new)
    return output


def exact_decode(rows, channel):
    n = len(channel)
    params = parameters(rows, n)
    if any(len(p) != 4 or any(v < 0 for v in p) or sum(p) != 1 for p in channel):
        raise ValueError("invalid probability distribution")
    stabilizer, groups, errors = span(rows), {}, []
    for labels in product(range(4), repeat=n):
        error = sum(((label & 1) << i) | ((label >> 1) << (n + i))
                    for i, label in enumerate(labels))
        probability = Fraction(1)
        for i, label in enumerate(labels):
            probability *= channel[i][label]
        syn = syndrome(error, rows, n)
        coset = min(error ^ s for s in stabilizer)
        masses = groups.setdefault(syn, {})
        masses[coset] = masses.get(coset, Fraction(0)) + probability
        errors.append({"error": error, "syndrome": syn, "coset": coset,
                       "probability": str(probability)})
    assert sum(Fraction(e["probability"]) for e in errors) == 1
    success = sum(max(masses.values()) for masses in groups.values())
    return {"parameters": params, "failure": str(1 - success), "errors": errors,
            "coset_masses": [{"syndrome": s, "coset": c, "probability": str(p)}
                             for s, masses in sorted(groups.items())
                             for c, p in sorted(masses.items())]}


def audit_case(case, protocol):
    rows = packed(case["generators"])
    n = len(case["generators"][0])
    witness = solve(rows, n)
    assert check(rows, n, witness)["possible"]
    gates = witness["gates"]
    assert gates == [protocol["predicted_gate_each_site"]] * n
    output = [image(row, gates) for row in rows]
    # Separate dense implementation cross-checks the row action convention.
    assert (unpack(output, 2 * n) == transformed(unpack(rows, 2 * n), gates)).all()
    space, mask = span(output), (1 << n) - 1
    assert all((row & mask) in space and (row & ~mask) in space for row in output)
    z_noise = [[Fraction(v) for v in protocol["pure_z_channel"]] for _ in range(n)]
    depol = [[Fraction(v) for v in protocol["depolarizing_channel"]] for _ in range(n)]
    settings = {
        "fixed_z_before": (rows, z_noise), "fixed_z_after": (output, z_noise),
        "depol_before": (rows, depol), "depol_after": (output, depol),
        "transported_z_after": (output, transport(z_noise, gates)),
    }
    outcomes = {key: exact_decode(code, noise) for key, (code, noise) in settings.items()}
    for result in outcomes.values():
        assert result["parameters"] == protocol["predicted_parameters_each_code"]
        assert len(result["errors"]) == 64
    assert outcomes["fixed_z_before"]["failure"] == case["pure_z_before"]
    assert outcomes["fixed_z_after"]["failure"] == case["pure_z_after"]
    assert outcomes["depol_before"]["failure"] == outcomes["depol_after"]["failure"]
    assert outcomes["fixed_z_before"]["failure"] == outcomes["transported_z_after"]["failure"]
    ratio = Fraction(outcomes["fixed_z_after"]["failure"]) / Fraction(outcomes["fixed_z_before"]["failure"])
    return {"id": case["id"], "rows": rows, "output_rows": output, "witness": witness,
            "outcomes": outcomes, "fixed_z_failure_ratio_after_over_before": str(ratio)}


def run(output):
    if git("status", "--porcelain").strip():
        raise RuntimeError("freeze sources in a clean worktree before control")
    protocol = json.loads((HERE / "workflow_bridge_protocol.json").read_text())
    sha = git("rev-parse", "HEAD").decode().strip()
    hashes = {name: digest(HERE / name) for name in SOURCES}
    for name, expected in hashes.items():
        assert committed_hash(sha, name) == expected
    for name in ("lc_scalar_components.py", "lc_scalar_check.py", "lc_certificate_check.py"):
        assert hashes[name] == committed_hash(protocol["source_r8"], name)
    output.mkdir(parents=True, exist_ok=False)
    receipt = {"source_sha": sha, "source_hashes": hashes,
               "started_utc": datetime.now(timezone.utc).isoformat(),
               "python": platform.python_version(), "platform": platform.platform()}
    (output / "receipt_start.json").write_text(json.dumps(receipt, indent=2) + "\n")
    records, failure = [], None
    with (output / "raw.jsonl").open("w", encoding="utf-8", newline="\n") as stream:
        for case in protocol["cases"]:
            try:
                record = audit_case(case, protocol)
            except Exception as error:
                failure = {"case": case["id"], "type": type(error).__name__, "message": str(error)}
                break
            records.append(record)
            stream.write(json.dumps(record, sort_keys=True) + "\n")
            stream.flush()
    result = {**receipt, "status": "known_boundary_confirmed" if failure is None else "failed",
              "failure": failure, "completed_cases": len(records),
              "raw_sha256": digest(output / "raw.jsonl"),
              "novel_discovery": False, "real_workflows": 0}
    (output / "result.json").write_text(json.dumps(result, indent=2) + "\n")
    if failure:
        raise RuntimeError(f"control failed, preserved at {output}: {failure}")
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True, type=Path)
    print(json.dumps(run(parser.parse_args().output), indent=2))
