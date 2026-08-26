from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from wavemind.evidence import attach_artifact_integrity, sha256_bytes


CANDIDATE_SHA = "a8fb7c9a899d08e99ac436eba9dfd66611dcdae0"
PROTOCOL_DIGEST = "a072744892d9d314ef92993f98cad148234211755df7ed168e3d97ae3e1165f2"
OUTPUT = ROOT / "benchmarks" / "scientific_v24_candidate_freeze.json"
FILES = (
    "wavemind/scientific_answer_transducer.py",
    "wavemind/scientific_runtime.py",
    "wavemind/scientific_memops.py",
    "wavemind/scientific_memoryagentbench.py",
    "wavemind/scientific_reconciliation.py",
    "benchmarks/scientific_mab_v11_development.py",
    "benchmarks/scientific_memops_v10_development.py",
    "benchmarks/scientific_memory_protocol_v24.json",
    "benchmarks/scientific_mab_v24_development.py",
    "benchmarks/scientific_memops_v24_development.py",
)


def _git_bytes(path: str) -> bytes:
    return subprocess.check_output(["git", "show", f"{CANDIDATE_SHA}:{path}"], cwd=ROOT)


def main() -> int:
    payload = attach_artifact_integrity(
        {
            "schema": "wavemind.scientific_v24_candidate_freeze.v1",
            "status": "frozen_before_fresh_development",
            "candidate_id": "targeted-operation-application-agent-v24",
            "candidate_source_sha": CANDIDATE_SHA,
            "protocol_digest": PROTOCOL_DIGEST,
            "files": [
                {"path": path, "sha256": sha256_bytes(_git_bytes(path))}
                for path in FILES
            ],
            "verification_before_freeze": {
                "passed": 179,
                "failed": 0,
                "deselected": 1134,
            },
            "fresh_v24_development_runs_executed": 0,
            "post_outcome_source_changes_forbidden": True,
        }
    )
    OUTPUT.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    print(json.dumps(payload, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
