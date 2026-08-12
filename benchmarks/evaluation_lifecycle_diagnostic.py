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
    compact_lifecycle_diagnostic,
    run_memops_lifecycle_diagnostic,
)
from wavemind.evidence import file_sha256


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Run the frozen Goal 8 MemOps development diagnostic"
    )
    parser.add_argument("--memops-root", type=Path, required=True)
    parser.add_argument("--temp-root", type=Path, required=True)
    parser.add_argument("--raw-output", type=Path, required=True)
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
    args.raw_output.parent.mkdir(parents=True, exist_ok=True)
    args.raw_output.write_text(
        json.dumps(payload, indent=2, ensure_ascii=True) + "\n", encoding="utf-8"
    )
    compact = compact_lifecycle_diagnostic(
        payload,
        raw_filename=args.raw_output.name,
        raw_sha256=file_sha256(args.raw_output),
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(compact, indent=2, ensure_ascii=True) + "\n", encoding="utf-8"
    )
    print(
        json.dumps(
            {
                "status": compact["status"],
                "source_sha": compact["source_sha"],
                "scope": compact["scope"],
                "summary": compact["summary"],
                "by_operation_type": compact["by_operation_type"],
                "wavemind_error_taxonomy": compact["wavemind_error_taxonomy"],
                "raw_output": str(args.raw_output),
                "output": str(args.output),
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
