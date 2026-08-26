from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from wavemind.evidence import attach_artifact_integrity, sha256_bytes


CANDIDATE_SHA = "5c21ef40481d23665b4e0aef07fbcdfffac63259"
PROTOCOL_DIGEST = "074368ce7227505f8e0fc9f666067a17f08b540804b307b2f5487106b572b761"
OUTPUT = ROOT / "benchmarks" / "scientific_v20_candidate_freeze.json"
FILES = (
    "wavemind/scientific_answer_transducer.py",
    "wavemind/scientific_runtime.py",
    "wavemind/scientific_memops.py",
    "wavemind/scientific_memoryagentbench.py",
    "wavemind/scientific_reconciliation.py",
    "benchmarks/scientific_mab_v11_development.py",
    "benchmarks/scientific_memops_v10_development.py",
    "benchmarks/scientific_memory_protocol_v20.json",
    "benchmarks/scientific_mab_v20_development.py",
    "benchmarks/scientific_memops_v20_development.py",
)


def _git_bytes(path: str) -> bytes:
    return subprocess.check_output(["git", "show", f"{CANDIDATE_SHA}:{path}"], cwd=ROOT)


def main() -> int:
    payload = attach_artifact_integrity(
        {
            "schema": "wavemind.scientific_v20_candidate_freeze.v1",
            "status": "frozen_before_fresh_development",
            "candidate_id": "operation-trace-dual-coverage-agent-v20",
            "candidate_source_sha": CANDIDATE_SHA,
            "protocol_digest": PROTOCOL_DIGEST,
            "files": [
                {"path": path, "sha256": sha256_bytes(_git_bytes(path))}
                for path in FILES
            ],
            "verification_before_freeze": {
                "passed": 171,
                "failed": 0,
                "deselected": 1134,
            },
            "fresh_v20_development_runs_executed": 0,
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
