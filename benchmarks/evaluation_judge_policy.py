from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from wavemind.evaluation_judges import (
    build_evaluation_judge_policy,
    validate_evaluation_judge_policy,
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("benchmarks/evaluation_judge_policy_results.json"),
    )
    parser.add_argument("--require-valid", action="store_true")
    args = parser.parse_args()
    report = build_evaluation_judge_policy(project_root=PROJECT_ROOT)
    errors = validate_evaluation_judge_policy(
        report,
        project_root=PROJECT_ROOT,
        expected_source_sha=report["source_sha"],
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
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
