from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Sequence

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from wavemind.evaluation_candidate_admission import build_candidate_admission


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Validate the preregistered Goal 8 correction candidate"
    )
    parser.add_argument("--raw", type=Path, required=True)
    parser.add_argument("--temp-root", type=Path, required=True)
    parser.add_argument(
        "--output",
        type=Path,
        default=PROJECT_ROOT
        / "benchmarks/evaluation_candidate1_admission_results.json",
    )
    args = parser.parse_args(argv)
    payload = build_candidate_admission(
        project_root=PROJECT_ROOT,
        hypothesis_path=PROJECT_ROOT
        / "benchmarks/evaluation_hypothesis_stateful_correction_v1.json",
        result_path=PROJECT_ROOT
        / "benchmarks/evaluation_lifecycle_candidate1_results.json",
        raw_path=args.raw,
        temp_root=args.temp_root,
    )
    args.output.write_text(
        json.dumps(payload, indent=2, ensure_ascii=True) + "\n", encoding="utf-8"
    )
    print(
        json.dumps(
            {
                "status": payload["status"],
                "admitted": payload["admitted"],
                "source_sha": payload["source_sha"],
                "candidate_source_sha": payload["candidate_source_sha"],
                "checks": len(payload["checks"]),
                "output": str(args.output),
            },
            indent=2,
        )
    )
    return 0 if payload["admitted"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
