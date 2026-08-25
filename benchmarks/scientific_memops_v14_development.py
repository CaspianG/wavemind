from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from wavemind.scientific_runtime import ScientificCandidateMode


_SPEC = importlib.util.spec_from_file_location(
    "wavemind_scientific_memops_v14_base",
    ROOT / "benchmarks" / "scientific_memops_v10_development.py",
)
if _SPEC is None or _SPEC.loader is None:
    raise RuntimeError("unable to load isolated v14 MemOps runner")
runner = importlib.util.module_from_spec(_SPEC)
sys.modules[_SPEC.name] = runner
_SPEC.loader.exec_module(runner)

runner.PROTOCOL_PATH = ROOT / "benchmarks" / "scientific_memory_protocol_v14.json"
runner.CANDIDATE_MODE = ScientificCandidateMode.TASK_AWARE_SEQUENCE_COVERAGE_AGENT
runner.ARTIFACT_SCHEMA = "wavemind.scientific_memops_v14_development.v1"


def main(argv: list[str] | None = None) -> int:
    return runner.main(argv)


if __name__ == "__main__":
    raise SystemExit(main())
