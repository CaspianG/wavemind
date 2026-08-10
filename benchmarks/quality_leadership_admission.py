from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from wavemind.quality_leadership_admission import write_quality_leadership_artifacts


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--expected-source-sha")
    parser.add_argument("--safe-product", type=Path, default=None)
    parser.add_argument("--workspace-experience", type=Path, default=None)
    parser.add_argument(
        "--protocol-output",
        type=Path,
        default=Path("benchmarks/quality_leadership_protocol.json"),
    )
    parser.add_argument(
        "--results-output",
        type=Path,
        default=Path("benchmarks/quality_leadership_results.json"),
    )
    parser.add_argument(
        "--per-query-output",
        type=Path,
        default=Path("benchmarks/quality_leadership_per_query.jsonl"),
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("benchmarks/quality_leadership_admission_results.json"),
    )
    parser.add_argument(
        "--markdown-output",
        type=Path,
        default=Path("benchmarks/QUALITY_LEADERSHIP_ADMISSION.md"),
    )
    parser.add_argument("--require-admitted", action="store_true")
    args = parser.parse_args()
    payload = write_quality_leadership_artifacts(
        root=PROJECT_ROOT,
        expected_source_sha=args.expected_source_sha,
        protocol_output=args.protocol_output,
        results_output=args.results_output,
        per_query_output=args.per_query_output,
        admission_output=args.output,
        markdown_output=args.markdown_output,
        safe_product_path=args.safe_product,
        workspace_experience_path=args.workspace_experience,
    )
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 2 if args.require_admitted and not payload["admitted"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
