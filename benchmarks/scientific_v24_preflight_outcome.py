from __future__ import annotations

import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from wavemind.evidence import attach_artifact_integrity


OUTPUT = ROOT / "benchmarks" / "scientific_v24_preflight_outcome.json"


def main() -> int:
    payload = attach_artifact_integrity(
        {
            "schema": "wavemind.scientific_v24_preflight_outcome.v1",
            "status": "invalid_before_execution",
            "candidate_id": "targeted-operation-application-agent-v24",
            "candidate_source_sha": "a8fb7c9a899d08e99ac436eba9dfd66611dcdae0",
            "protocol_digest": "a072744892d9d314ef92993f98cad148234211755df7ed168e3d97ae3e1165f2",
            "reason": (
                "The preregistered A04 subject has four official operation files and "
                "no A04_update.json, contradicting the frozen requirement of five "
                "operation files per subject."
            ),
            "missing_paths": ["2-evidence_conversation/A04_update.json"],
            "benchmark_invocations": 0,
            "fresh_development_cases_executed": 0,
            "model_calls": 0,
            "final_split_touched": False,
            "thresholds_changed": False,
            "replacement_within_v24_forbidden": True,
            "claim_boundary": "Preflight invalidity only; no performance evidence.",
        }
    )
    OUTPUT.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    print(json.dumps(payload, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
