from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from wavemind.quality_leadership_admission import (
    write_quality_leadership_development_results,
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--agent-memory",
        type=Path,
        default=Path("benchmarks/agent_memory_advantage_results.json"),
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("benchmarks/quality_leadership_results.json"),
    )
    parser.add_argument(
        "--admission-output",
        type=Path,
        default=Path("benchmarks/quality_leadership_admission_results.json"),
    )
    parser.add_argument(
        "--markdown-output",
        type=Path,
        default=Path("benchmarks/QUALITY_LEADERSHIP_ADMISSION.md"),
    )
    parser.add_argument("--expected-source-sha")
    parser.add_argument("--safe-product", type=Path, default=None)
    parser.add_argument("--workspace-experience", type=Path, default=None)
    parser.add_argument("--require-dev-gate", action="store_true")
    args = parser.parse_args()
    payload = write_quality_leadership_development_results(
        root=PROJECT_ROOT,
        agent_memory_path=args.agent_memory,
        results_output=args.output,
        admission_output=args.admission_output,
        markdown_output=args.markdown_output,
        expected_source_sha=args.expected_source_sha,
        safe_product_path=args.safe_product,
        workspace_experience_path=args.workspace_experience,
    )
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    rows = {str(row["id"]): row for row in payload["rows"]}
    dev_gate = rows.get("development-go-no-go", {})
    return 2 if args.require_dev_gate and dev_gate.get("status") != "implemented" else 0


if __name__ == "__main__":
    raise SystemExit(main())
