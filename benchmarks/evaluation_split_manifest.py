from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from wavemind.evaluation_splits import (
    build_evaluation_split_manifest,
    validate_evaluation_split_manifest,
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--state-bench-root", type=Path, required=True)
    parser.add_argument("--memops-root", type=Path, required=True)
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("benchmarks/evaluation_split_manifest_results.json"),
    )
    parser.add_argument("--require-valid", action="store_true")
    args = parser.parse_args()
    report = build_evaluation_split_manifest(
        project_root=PROJECT_ROOT,
        state_bench_root=args.state_bench_root,
        memops_root=args.memops_root,
    )
    errors = validate_evaluation_split_manifest(
        report,
        project_root=PROJECT_ROOT,
        expected_source_sha=report["source_sha"],
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(report, separators=(",", ":")) + "\n", encoding="utf-8"
    )
    print(
        json.dumps(
            {
                "valid": not errors,
                "errors": errors,
                "source_sha": report["source_sha"],
                "output": str(args.output),
            }
        )
    )
    return 2 if args.require_valid and errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
