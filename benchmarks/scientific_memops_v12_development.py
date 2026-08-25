from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from benchmarks import scientific_memops_v10_development as runner
from wavemind.scientific_runtime import ScientificCandidateMode


runner.PROTOCOL_PATH = ROOT / "benchmarks" / "scientific_memory_protocol_v12.json"
runner.CANDIDATE_MODE = ScientificCandidateMode.EVIDENCE_CONTRACTED_QUERY_AGENT
runner.ARTIFACT_SCHEMA = "wavemind.scientific_memops_v12_development.v1"
runner.CLUSTER_GATE_KEY = "minimum_independent_clusters_per_family"


def main(argv: list[str] | None = None) -> int:
    return runner.main(argv)


if __name__ == "__main__":
    raise SystemExit(main())
