"""Compare a fresh v2 reproduction with the preserved run, without rewriting it."""

import argparse
import json
from pathlib import Path
import subprocess

import numpy as np

from experiment import HERE, REPO, sha


def read(path):
    return json.loads(path.read_text(encoding="utf-8"))


def manifest_check(directory):
    manifest = read(directory / "checksums.json")
    assert set(manifest) == {p.name for p in directory.iterdir() if p.is_file()} - {"checksums.json"}
    for name, expected in manifest.items():
        assert sha(directory / name) == expected, f"Checksum mismatch: {directory / name}"
    for name, expected in read(directory / "provenance.json")["sources"].items():
        assert sha(HERE / name) == expected, f"Source mismatch: {name}"


def compare_json(left, right, path="result"):
    if isinstance(left, dict):
        assert set(left) == set(right), path
        for key in left:
            if path == "result" and key == "seconds":
                continue
            compare_json(left[key], right[key], f"{path}.{key}")
    elif isinstance(left, list):
        assert len(left) == len(right), path
        for i, (a, b) in enumerate(zip(left, right)):
            compare_json(a, b, f"{path}[{i}]")
    elif isinstance(left, float):
        assert np.isclose(left, right, rtol=1e-9, atol=1e-11), path
    else:
        assert left == right, path


def verify(fresh, check_git=False):
    original = HERE / "runs" / "readout_v2"
    manifest_check(original)
    manifest_check(fresh)
    old_provenance, new_provenance = read(original / "provenance.json"), read(fresh / "provenance.json")
    for key in ("sources", "old_roots_sha256", "original_source_commit"):
        assert old_provenance[key] == new_provenance[key], key
    arrays_checked = 0
    for path in sorted(original.glob("*.npz")):
        with np.load(path, allow_pickle=False) as left, np.load(fresh / path.name, allow_pickle=False) as right:
            assert set(left.files) == set(right.files), path.name
            for name in left.files:
                assert left[name].shape == right[name].shape, (path.name, name)
                np.testing.assert_allclose(left[name], right[name], rtol=1e-11, atol=1e-12,
                                           err_msg=f"{path.name}:{name}")
                arrays_checked += 1
    compare_json(read(original / "results.json"), read(fresh / "results.json"))
    compare_json(read(original / "schedule.json"), read(fresh / "schedule.json"), "schedule")
    blobs_checked = 0
    if check_git:
        for path in sorted(original.iterdir()):
            if path.is_file():
                blob = subprocess.check_output(["git", "-c", f"safe.directory={REPO.as_posix()}",
                                                "show", f"HEAD:{path.relative_to(REPO).as_posix()}"], cwd=REPO)
                assert blob == path.read_bytes(), f"Git byte mismatch: {path.name}"
                blobs_checked += 1
    return {"result":"REPLAY_MATCH", "npz_arrays":arrays_checked,
            "scientific_json_records":2, "exact_git_blob_comparisons":blobs_checked,
            "replay_source_commit":new_provenance["source_commit"],
            "fresh_directory":fresh.as_posix(), "different_investigator":False,
            "original_advantage_gate":read(original / "results.json")["advantage_gate_pass"]}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("fresh", type=Path)
    parser.add_argument("--check-git", action="store_true")
    args = parser.parse_args()
    print(json.dumps(verify(args.fresh.resolve(), args.check_git), indent=2))
