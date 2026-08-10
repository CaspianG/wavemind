from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from wavemind.workspace_experience_admission import (
    write_workspace_experience_admission_artifacts,
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--safe-product", type=Path, default=None)
    parser.add_argument("--operational-evidence", type=Path, default=None)
    parser.add_argument(
        "--matrix-output",
        type=Path,
        default=Path("benchmarks/workspace_experience_admission_matrix.json"),
    )
    parser.add_argument(
        "--matrix-markdown-output",
        type=Path,
        default=Path("benchmarks/WORKSPACE_EXPERIENCE_ADMISSION_MATRIX.md"),
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("benchmarks/workspace_experience_admission_results.json"),
    )
    parser.add_argument(
        "--markdown-output",
        type=Path,
        default=Path("benchmarks/WORKSPACE_EXPERIENCE_ADMISSION.md"),
    )
    parser.add_argument("--baseline-source-sha", default=None)
    parser.add_argument("--require-admitted", action="store_true")
    args = parser.parse_args()
    payload = write_workspace_experience_admission_artifacts(
        root=PROJECT_ROOT,
        matrix_output=args.matrix_output,
        matrix_markdown_output=args.matrix_markdown_output,
        result_output=args.output,
        report_output=args.markdown_output,
        baseline_source_sha=args.baseline_source_sha,
        safe_product_path=args.safe_product,
        operational_evidence_path=args.operational_evidence,
    )
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 2 if args.require_admitted and not payload["admitted"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
