from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from wavemind.codeql_admission import (  # noqa: E402
    CodeQLAdmissionError,
    verify_codeql_results,
)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Verify exact-source CodeQL analyses and blocking alert state."
    )
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--deadline-seconds", type=float, default=120)
    parser.add_argument("--require-admitted", action="store_true")
    args = parser.parse_args()
    try:
        report = verify_codeql_results(
            repository=os.environ.get("GITHUB_REPOSITORY", ""),
            ref=os.environ.get("GITHUB_REF", ""),
            sha=os.environ.get("GITHUB_SHA", ""),
            token=os.environ.get("GITHUB_TOKEN", ""),
            deadline_seconds=args.deadline_seconds,
        )
    except CodeQLAdmissionError as error:
        print(
            json.dumps(
                {
                    "status": "blocked",
                    "error": {
                        "code": str(error),
                        "message": "CodeQL result verification failed closed.",
                    },
                }
            ),
            file=sys.stderr,
        )
        return 2
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(
        json.dumps(
            {
                "status": report["status"],
                "source": report["source"],
                "alerts": report["alerts"],
            },
            ensure_ascii=False,
        )
    )
    return 2 if args.require_admitted and not report["admitted"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
