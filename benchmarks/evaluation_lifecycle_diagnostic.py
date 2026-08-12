from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Sequence

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from wavemind.evaluation_lifecycle_diagnostic import (
    run_memops_lifecycle_diagnostic,
)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Run the frozen Goal 8 MemOps development diagnostic"
    )
    parser.add_argument("--memops-root", type=Path, required=True)
    parser.add_argument("--temp-root", type=Path, required=True)
    parser.add_argument(
        "--protocol",
        type=Path,
        default=PROJECT_ROOT / "benchmarks/evaluation_development_protocol_v1.json",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=PROJECT_ROOT / "benchmarks/evaluation_lifecycle_diagnostic_results.json",
    )
    args = parser.parse_args(argv)
    payload = run_memops_lifecycle_diagnostic(
        project_root=PROJECT_ROOT,
        memops_root=args.memops_root,
        protocol_path=args.protocol,
        dataset_manifest_path=PROJECT_ROOT
        / "benchmarks/evaluation_dataset_manifest_v1.json",
        split_manifest_path=PROJECT_ROOT
        / "benchmarks/evaluation_split_manifest_results.json",
        judge_policy_path=PROJECT_ROOT
        / "benchmarks/evaluation_judge_policy_results.json",
        temp_root=args.temp_root,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(payload, indent=2, ensure_ascii=True) + "\n", encoding="utf-8"
    )
    print(
        json.dumps(
            {
                "status": payload["status"],
                "source_sha": payload["source_sha"],
                "scope": payload["scope"],
                "summary": payload["summary"],
                "wavemind_error_taxonomy": payload["wavemind_error_taxonomy"],
                "output": str(args.output),
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
