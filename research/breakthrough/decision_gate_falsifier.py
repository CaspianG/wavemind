"""Frozen R8 follow-up: exhaustive finite algebras and per-input graph orbits."""

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import platform
import subprocess
import time

from lc_graph_oracle import bipartite, complement_at, edges, graph_stabilizers
from lc_r8_corpus import span, subspaces
from lc_scalar_check import check
from lc_scalar_components import affine, solve

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
SOURCES = ("decision_gate_protocol.json", "SCIENTIFIC_DECISION_GATE.md",
           "decision_gate_falsifier.py", "test_decision_gate.py",
           "lc_graph_oracle.py", "lc_r8_corpus.py", "lc_scalar_components.py",
           "lc_scalar_check.py", "lc_certificate_check.py")


def digest_bytes(value):
    return hashlib.sha256(value).hexdigest()


def git(*args):
    return subprocess.check_output(["git", *args], cwd=ROOT)


def committed_hash(sha, name):
    return digest_bytes(git("show", f"{sha}:research/breakthrough/{name}"))


def multiply(left, right, n):
    """Literal 2x2 row-column arithmetic, independent of determinant code."""
    output = 0
    for site in range(n):
        for row in range(2):
            for col in range(2):
                value = 0
                for k in range(2):
                    value ^= ((left >> (4 * site + 2 * row + k)) & 1) & (
                        (right >> (4 * site + 2 * k + col)) & 1)
                output |= value << (4 * site + 2 * row + col)
    return output


def rank_one(block):
    return block not in (0, 9) and multiply(block, block, 1) == block


def trace_one(value, site):
    return ((value >> (4 * site)) ^ (value >> (4 * site + 3))) & 1 == 1


def scalar_word(mask, n):
    return sum(9 << (4 * i) for i in range(n) if mask >> i & 1)


def atoms(values, n):
    masks = [m for m in range(1 << n) if scalar_word(m, n) in values]
    groups = {}
    for i in range(n):
        groups.setdefault(tuple(m >> i & 1 for m in masks), []).append(i)
    return list(groups.values()), masks


def anchor_feasible(basis, sites, anchor):
    def coefficient(bit):
        return sum(((row >> bit) & 1) << k for k, row in enumerate(basis))
    equations = [(coefficient(4 * i) ^ coefficient(4 * i + 3), 1) for i in sites]
    equations += [(coefficient(4 * sites[0] + j), (anchor >> j) & 1) for j in range(4)]
    answer = affine(equations, len(basis))
    if not answer["consistent"]:
        left = right = 0
        for index in answer["contradiction"]:
            row, bit = equations[index]
            left ^= row
            right ^= bit
        assert left == 0 and right == 1
        return None
    value = 0
    for k, row in enumerate(basis):
        if answer["particular"] >> k & 1:
            value ^= row
    return value


def algebra_record(basis, n):
    values = span(basis)
    closed = all(multiply(a, b, n) in values for a in basis for b in basis)
    record = {"kind": "unital_space", "n": n, "basis": basis, "closed": closed}
    if not closed:
        return record
    groups, masks = atoms(values, n)
    assert len(masks) == 1 << len(groups)
    all_projectors = [v for v in values if all(rank_one(v >> (4 * i) & 15) for i in range(n))]
    assembled, possible, lemma_checks = 0, True, 0
    for sites in groups:
        for value in values:
            if all(trace_one(value, i) for i in sites):
                labels = [rank_one(value >> (4 * i) & 15) for i in sites]
                assert len(set(labels)) == 1, (basis, sites, value)
                lemma_checks += 1
        witnesses = [anchor_feasible(basis, sites, p) for p in range(16) if rank_one(p)]
        feasible = [v for v in witnesses if v is not None]
        local_truth = any(all(rank_one(v >> (4 * i) & 15) for i in sites) for v in values)
        assert bool(feasible) == local_truth
        for value in feasible:
            assert value in values and all(rank_one(value >> (4 * i) & 15) for i in sites)
        possible &= bool(feasible)
        if feasible:
            support = sum(15 << (4 * i) for i in sites)
            assembled ^= feasible[0] & support
    assert possible == bool(all_projectors)
    if possible:
        assert assembled in values and assembled in all_projectors
    return {**record, "atoms": groups, "possible": possible,
            "complete_element_projectors": len(all_projectors), "lemma_checks": lemma_checks}


def ablations():
    # T=(diag(1,0), [[0,1],[1,1]]); both traces one, only first rank one.
    identity, value = 0x99, 0xE1
    linear = span([identity, value])
    assert multiply(value, value, 2) not in linear
    assert atoms(linear, 2)[0] == [[0, 1]]
    assert all(trace_one(value, i) for i in range(2))
    assert rank_one(value & 15) and not rank_one(value >> 4)
    full = set(range(256))
    assert atoms(full, 2)[0] == [[0], [1]] and value in full
    return {"kind": "ablations", "value": value,
            "nonclosed_basis": [identity, value],
            "without_closure_implication_fails": True,
            "without_atom_restriction_implication_fails": True}


def graph_inputs(protocol):
    n = protocol["graph_sites"]
    links = edges(n)
    for index in range(protocol["graph_hash_cases"]):
        data = f'{protocol["graph_hash_seed"]}:{index}'.encode()
        yield f"hash-{index}", int(hashlib.sha256(data).hexdigest(), 16) & ((1 << len(links)) - 1)
    for name in protocol["graph_controls"]:
        if name == "cycle":
            pairs = {tuple(sorted((i, (i + 1) % n))) for i in range(n)}
        elif name == "star":
            pairs = {(0, i) for i in range(1, n)}
        else:
            raise ValueError(name)
        yield name, sum(1 << i for i, pair in enumerate(links) if pair in pairs)


def exact_orbit(word, n, limit, seconds):
    seen, pending = {word}, [word]
    start = time.monotonic()
    while pending:
        if time.monotonic() - start > seconds:
            return {"resolved": False, "reason": "time_limit", "visited": len(seen)}
        current = pending.pop()
        for site in range(n):
            other = complement_at(current, n, site)
            if other not in seen:
                if len(seen) >= limit:
                    return {"resolved": False, "reason": "state_limit", "visited": len(seen)}
                seen.add(other)
                pending.append(other)
    witnesses = [v for v in seen if bipartite(v, n)]
    return {"resolved": True, "size": len(seen), "representative": min(seen),
            "sorted_orbit_sha256": digest_bytes(json.dumps(sorted(seen)).encode()),
            "possible": bool(witnesses), "bipartite_witness": min(witnesses) if witnesses else None}


def graph_record(identifier, word, protocol):
    n = protocol["graph_sites"]
    rows = graph_stabilizers(word, n)
    witness = solve(rows, n)
    audited = check(rows, n, witness)
    truth = exact_orbit(word, n, protocol["max_orbit_states_per_input"],
                        protocol["max_seconds_per_orbit"])
    if truth["resolved"]:
        assert truth["possible"] == audited["possible"], (identifier, truth, witness)
    return {"kind": "graph", "id": identifier, "word": word, "n": n, "rows": rows,
            "witness": witness, "orbit": truth}


def records(protocol):
    yield ablations()
    for n in protocol["algebra_domain_sites"]:
        count = 0
        for rows in subspaces(4 * n - 1):
            yield algebra_record([scalar_word((1 << n) - 1, n), *rows], n)
            count += 1
        assert count == protocol["unital_linear_subspace_counts"][str(n)]
    for identifier, word in graph_inputs(protocol):
        yield graph_record(identifier, word, protocol)


def summarize(stored):
    algebras = [r for r in stored if r["kind"] == "unital_space" and r["closed"]]
    graphs = [r for r in stored if r["kind"] == "graph"]
    resolved = [r for r in graphs if r["orbit"]["resolved"]]
    negative = [r for r in resolved if not r["orbit"]["possible"]]
    return {"records": len(stored), "unital_linear_spaces": sum(r["kind"] == "unital_space" for r in stored),
            "actual_algebras": len(algebras), "algebra_negative": sum(not r["possible"] for r in algebras),
            "lemma_checks": sum(r["lemma_checks"] for r in algebras),
            "graphs": len(graphs), "resolved_graphs": len(resolved), "negative_graphs": len(negative),
            "distinct_resolved_orbits": len({r["orbit"]["representative"] for r in resolved}),
            "negative_component_sizes": {r["id"]: [len(c["sites"]) for c in r["witness"]["components"]]
                                         for r in negative}}


def run(output):
    if git("status", "--porcelain").strip():
        raise RuntimeError("freeze all sources in a clean worktree before main generation")
    sha = git("rev-parse", "HEAD").decode().strip()
    protocol = json.loads((HERE / "decision_gate_protocol.json").read_text())
    hashes = {name: digest_bytes((HERE / name).read_bytes()) for name in SOURCES}
    for name, expected in hashes.items():
        assert expected == committed_hash(sha, name)
        if name.startswith("lc_"):
            assert expected == committed_hash(protocol["source_r8"], name)
    output.mkdir(parents=True, exist_ok=False)
    receipt = {"source_sha": sha, "source_hashes": hashes, "python": platform.python_version(),
               "started_utc": datetime.now(timezone.utc).isoformat(), "platform": platform.platform()}
    (output / "receipt_start.json").write_text(json.dumps(receipt, indent=2) + "\n")
    stored, failure = [], None
    start = time.monotonic()
    try:
        with (output / "raw.jsonl").open("w", encoding="utf-8", newline="\n") as stream:
            for record in records(protocol):
                stored.append(record)
                stream.write(json.dumps(record, sort_keys=True) + "\n")
                if record["kind"] == "graph":
                    stream.flush()
                    print(json.dumps({"completed": record["id"], "orbit": record["orbit"]}), flush=True)
    except Exception as error:
        failure = {"type": type(error).__name__, "message": str(error)}
    summary = summarize(stored)
    passed = failure is None and summary["graphs"] == summary["resolved_graphs"] == 10
    result = {**receipt, "status": "finite_gate_pass" if passed else "failed_or_unresolved",
              "failure": failure, "summary": summary, "seconds": time.monotonic() - start,
              "raw_sha256": digest_bytes((output / "raw.jsonl").read_bytes()),
              "novelty_cleared": False, "real_workflows": 0}
    (output / "result.json").write_text(json.dumps(result, indent=2) + "\n")
    if not passed:
        raise RuntimeError(f"preserved incomplete or failed gate: {result}")
    return result


def verify(directory):
    receipt = json.loads((directory / "receipt_start.json").read_text())
    result = json.loads((directory / "result.json").read_text())
    assert all(result[key] == value for key, value in receipt.items())
    assert set(receipt["source_hashes"]) == set(SOURCES)
    protocol = json.loads((HERE / "decision_gate_protocol.json").read_text())
    for name, expected in receipt["source_hashes"].items():
        assert digest_bytes((HERE / name).read_bytes()) == committed_hash(receipt["source_sha"], name) == expected
        if name.startswith("lc_"):
            assert expected == committed_hash(protocol["source_r8"], name)
    raw = (directory / "raw.jsonl").read_bytes()
    assert digest_bytes(raw) == result["raw_sha256"]
    stored = [json.loads(line) for line in raw.splitlines()]
    regenerated = list(records(protocol))
    assert stored == regenerated
    assert summarize(stored) == result["summary"]
    assert result["status"] == "finite_gate_pass" and result["failure"] is None
    assert result["summary"]["graphs"] == result["summary"]["resolved_graphs"] == 10
    assert result["novelty_cleared"] is False and result["real_workflows"] == 0
    return {"status": "full_read_only_replay_pass", "source_sha": receipt["source_sha"], **result["summary"]}


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument("--output", type=Path)
    action.add_argument("--verify", type=Path)
    args = parser.parse_args()
    print(json.dumps(run(args.output) if args.output else verify(args.verify), indent=2))
