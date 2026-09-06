from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from wavemind.scientific_splits import build_memoryagentbench_split_manifest


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Freeze whole-context MemoryAgentBench development splits"
    )
    parser.add_argument("--dataset-root", type=Path, required=True)
    parser.add_argument(
        "--output",
        type=Path,
        default=ROOT / "benchmarks" / "memoryagentbench_split_manifest_results.json",
    )
    args = parser.parse_args()
    payload = build_memoryagentbench_split_manifest(
        project_root=ROOT,
        dataset_root=args.dataset_root,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    print(json.dumps(payload, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
