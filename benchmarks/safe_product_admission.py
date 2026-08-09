from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from wavemind.safe_product_admission import (
    render_safe_product_markdown,
    run_safe_product_admission,
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--safe-retrieval", type=Path, required=True)
    parser.add_argument("--product-persistence", type=Path, required=True)
    parser.add_argument("--quickstarts", type=Path, required=True)
    parser.add_argument("--ci-matrix-passed", action="store_true")
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("benchmarks/safe_product_admission_results.json"),
    )
    parser.add_argument(
        "--markdown-output",
        type=Path,
        default=Path("benchmarks/SAFE_PRODUCT_ADMISSION.md"),
    )
    parser.add_argument("--require-admitted", action="store_true")
    args = parser.parse_args()
    report = run_safe_product_admission(
        project_root=PROJECT_ROOT,
        safe_retrieval_artifact=args.safe_retrieval,
        product_persistence_artifact=args.product_persistence,
        quickstart_artifact=args.quickstarts,
        ci_matrix_passed=args.ci_matrix_passed,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    args.markdown_output.parent.mkdir(parents=True, exist_ok=True)
    args.markdown_output.write_text(
        render_safe_product_markdown(report),
        encoding="utf-8",
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 2 if args.require_admitted and not report["admitted"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
