from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

_SPEC = importlib.util.spec_from_file_location(
    "wavemind_scientific_mab_v12_base",
    ROOT / "benchmarks" / "scientific_mab_v11_development.py",
)
if _SPEC is None or _SPEC.loader is None:
    raise RuntimeError("unable to load isolated v12 MAB runner")
runner = importlib.util.module_from_spec(_SPEC)
sys.modules[_SPEC.name] = runner
_SPEC.loader.exec_module(runner)


runner.PROTOCOL_PATH = ROOT / "benchmarks" / "scientific_memory_protocol_v12.json"
runner.ARTIFACT_SCHEMA = "wavemind.memoryagentbench_development.v12"


def main(argv: list[str] | None = None) -> int:
    return runner.main(argv)


if __name__ == "__main__":
    raise SystemExit(main())
