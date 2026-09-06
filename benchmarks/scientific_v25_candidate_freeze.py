from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from wavemind.evidence import attach_artifact_integrity, sha256_bytes


CANDIDATE_SHA = "7a22e4cfe1d9d49d509c269439b3c6a06f5b4ab9"
PROTOCOL_DIGEST = "02b458cd3c4da6b575b2ab6f088836f5d16a3f4a1cb662e8573fdcb555aeaf4e"
OUTPUT = ROOT / "benchmarks" / "scientific_v25_candidate_freeze.json"
FILES = (
    "wavemind/scientific_answer_transducer.py",
    "wavemind/scientific_runtime.py",
    "wavemind/scientific_memops.py",
    "wavemind/scientific_memoryagentbench.py",
    "wavemind/scientific_reconciliation.py",
    "benchmarks/scientific_mab_v11_development.py",
    "benchmarks/scientific_memops_v10_development.py",
    "benchmarks/scientific_memory_protocol_v25.json",
    "benchmarks/scientific_mab_v25_development.py",
    "benchmarks/scientific_memops_v25_development.py",
)


def _git_bytes(path: str) -> bytes:
    return subprocess.check_output(["git", "show", f"{CANDIDATE_SHA}:{path}"], cwd=ROOT)


def main() -> int:
    payload = attach_artifact_integrity(
        {
            "schema": "wavemind.scientific_v25_candidate_freeze.v1",
            "status": "frozen_before_fresh_development",
            "candidate_id": "targeted-operation-application-agent-v25",
            "candidate_source_sha": CANDIDATE_SHA,
            "protocol_digest": PROTOCOL_DIGEST,
            "files": [
                {"path": path, "sha256": sha256_bytes(_git_bytes(path))}
                for path in FILES
            ],
            "verification_before_freeze": {
                "passed": 183,
                "failed": 0,
                "deselected": 1134,
            },
            "fresh_v25_development_runs_executed": 0,
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
