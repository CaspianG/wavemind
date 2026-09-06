from __future__ import annotations

import copy
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from wavemind.evidence import canonical_json_bytes, file_sha256, sha256_bytes


BASE = ROOT / "benchmarks" / "scientific_memory_protocol_v24.json"
V24_PREFLIGHT = ROOT / "benchmarks" / "scientific_v24_preflight_outcome.json"
OUTPUT = ROOT / "benchmarks" / "scientific_memory_protocol_v25.json"


MEMOPS_DEVELOPMENT = ["A06", "B30", "C02", "E07", "F16"]
MEMOPS_FILE_COUNTS = {"A06": 5, "B30": 4, "C02": 4, "E07": 4, "F16": 5}


def main() -> int:
    base = json.loads(BASE.read_text(encoding="utf-8"))
    preflight = json.loads(V24_PREFLIGHT.read_text(encoding="utf-8"))
    payload = copy.deepcopy(base)
    payload.update(
        {
            "schema": "wavemind.scientific_memory_protocol.v25",
            "protocol_id": "scientific-core-targeted-operation-application-2026-08-26-v25",
            "status": "preregistered",
            "preregistered_at": "2026-08-26",
            "supersedes_protocol_digest": base["protocol_digest"],
            "candidate": {
                **base["candidate"],
                "id": "targeted-operation-application-agent-v25",
                "frozen_before_first_v24_outcome": False,
                "frozen_before_first_v25_outcome": True,
            },
        }
    )
    payload["development_firewall"] = {
        "allowed": (
            "Only the ten listed never-executed MAB development contexts and the "
            "manifest-exhaustive operation files of five listed never-opened MemOps "
            "development subjects."
        ),
        "forbidden": [
            "all MAB contexts or duplicate context_sha256 values opened through v24",
            "all MAB validation and final units",
            "all MemOps subjects opened through v24 development or diagnostics",
            "all MemOps validation and final subjects",
            "all LongMemEval-V2 examples",
        ],
    }
    memops = payload["frozen_development_gate"]["families"][
        "memops_longitudinal_operation"
    ]
    memops.update(
        {
            "subjects": MEMOPS_DEVELOPMENT,
            "selection": (
                "Five never-opened development subjects selected without reading "
                "source content. Every operation file listed by the pinned manifest "
                "is required; missing operation types are structural upstream absence."
            ),
            "manifest_operation_file_counts": MEMOPS_FILE_COUNTS,
            "expected_case_count": sum(MEMOPS_FILE_COUNTS.values()),
            "required_operation_files_per_subject": None,
            "required_manifest_exhaustive_files": True,
            "previously_opened": False,
        }
    )
    payload["immutable_v24_preflight_evidence"] = {
        "status": preflight["status"],
        "outcome_path": "benchmarks/scientific_v24_preflight_outcome.json",
        "outcome_file_sha256": file_sha256(V24_PREFLIGHT),
        "outcome_payload_sha256": preflight["integrity"]["payload_sha256"],
        "benchmark_invocations": 0,
        "fresh_development_cases_executed": 0,
        "replacement_within_v24_forbidden": True,
    }
    payload["claim_boundary"] = (
        "Only full exact-SHA admission permits a bounded claim; 100%-pass, SOTA, "
        "universal, production, and revolutionary claims remain forbidden without "
        "separate evidence."
    )
    payload.pop("protocol_digest", None)
    payload["protocol_digest"] = sha256_bytes(canonical_json_bytes(payload))
    OUTPUT.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    print(json.dumps(payload, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
