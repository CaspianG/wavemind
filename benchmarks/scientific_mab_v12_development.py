from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from benchmarks import scientific_mab_v11_development as runner


runner.PROTOCOL_PATH = ROOT / "benchmarks" / "scientific_memory_protocol_v12.json"
runner.ARTIFACT_SCHEMA = "wavemind.memoryagentbench_development.v12"


def main(argv: list[str] | None = None) -> int:
    return runner.main(argv)


if __name__ == "__main__":
    raise SystemExit(main())
