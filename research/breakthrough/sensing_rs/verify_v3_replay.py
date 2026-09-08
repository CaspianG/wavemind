"""Compare every saved v3 array with a fresh run; never replace the first run."""

import argparse
import json
from pathlib import Path
import subprocess

import numpy as np

from experiment import HERE, REPO
from verify_v2_replay import compare_json, manifest_check, read


def verify(fresh, check_git=False):
    original = HERE / "runs" / "pulse_v3"
    manifest_check(original)
    manifest_check(fresh)
    old, new = read(original / "provenance.json"), read(fresh / "provenance.json")
    for key in ("sources", "v2_results_sha256"):
        assert old[key] == new[key], key
    names = {p.name for p in original.glob("*.npz")}
    assert names == {p.name for p in fresh.glob("*.npz")}
    arrays_checked = 0
    for name in sorted(names):
        with np.load(original / name, allow_pickle=False) as left, np.load(fresh / name, allow_pickle=False) as right:
            assert set(left.files) == set(right.files), name
            for key in left.files:
                assert left[key].shape == right[key].shape, (name, key)
                np.testing.assert_allclose(left[key], right[key], rtol=1e-11, atol=1e-12,
                                           err_msg=f"{name}:{key}")
                arrays_checked += 1
    compare_json(read(original / "results.json"), read(fresh / "results.json"))
    blobs = 0
    if check_git:
        for path in sorted(original.iterdir()):
            if path.is_file():
                blob = subprocess.check_output(["git", "-c", f"safe.directory={REPO.as_posix()}",
                    "show", f"HEAD:{path.relative_to(REPO).as_posix()}"], cwd=REPO)
                assert blob == path.read_bytes(), f"Git byte mismatch: {path.name}"
                blobs += 1
    return {"result": "REPLAY_MATCH", "npz_files": len(names), "npz_arrays": arrays_checked,
            "scientific_json_records": 1, "exact_git_blob_comparisons": blobs,
            "replay_source_commit": new["source_commit"], "fresh_directory": fresh.as_posix(),
            "different_investigator": False, "original_advantage_gate": read(original / "results.json")["advantage_gate_pass"]}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("fresh", type=Path)
    parser.add_argument("--check-git", action="store_true")
    args = parser.parse_args()
    print(json.dumps(verify(args.fresh.resolve(), args.check_git), indent=2))
