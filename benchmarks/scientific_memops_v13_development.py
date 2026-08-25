from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

_SPEC = importlib.util.spec_from_file_location(
    "wavemind_scientific_memops_v13_base",
    ROOT / "benchmarks" / "scientific_memops_v10_development.py",
)
if _SPEC is None or _SPEC.loader is None:
    raise RuntimeError("unable to load isolated v13 MemOps runner")
runner = importlib.util.module_from_spec(_SPEC)
sys.modules[_SPEC.name] = runner
_SPEC.loader.exec_module(runner)

from wavemind.scientific_runtime import ScientificCandidateMode

runner.PROTOCOL_PATH = ROOT / "benchmarks" / "scientific_memory_protocol_v13.json"
runner.CANDIDATE_MODE = ScientificCandidateMode.EVIDENCE_CONTRACTED_QUERY_AGENT
runner.ARTIFACT_SCHEMA = "wavemind.scientific_memops_v13_development.v1"
runner.CLUSTER_GATE_KEY = "minimum_independent_clusters_per_family"


def main(argv: list[str] | None = None) -> int:
    return runner.main(argv)


if __name__ == "__main__":
    raise SystemExit(main())
