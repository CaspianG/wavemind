from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from wavemind.evaluation_validity_controls import run_evaluation_validity_controls


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("benchmarks/evaluation_validity_controls_results.json"),
    )
    parser.add_argument("--require-passed", action="store_true")
    args = parser.parse_args()
    report = run_evaluation_validity_controls(project_root=PROJECT_ROOT)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    required = (
        "positive_controls",
        "negative_controls",
        "control_ordering",
        "deterministic_verdict",
        "per_case_completeness",
    )
    passed = all(report[key]["passed"] for key in required)
    print(
        json.dumps(
            {
                "passed": passed,
                "source_sha": report["source_sha"],
                "output": str(args.output),
            }
        )
    )
    return 2 if args.require_passed and not passed else 0


if __name__ == "__main__":
    raise SystemExit(main())
