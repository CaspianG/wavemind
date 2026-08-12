from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Sequence

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from wavemind.evaluation_development_protocol import (
    build_evaluation_development_protocol,
    validate_evaluation_development_protocol,
)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Freeze and validate the Goal 8 bounded development protocol"
    )
    parser.add_argument(
        "--dataset-manifest",
        type=Path,
        default=PROJECT_ROOT / "benchmarks/evaluation_dataset_manifest_v1.json",
    )
    parser.add_argument(
        "--split-manifest",
        type=Path,
        default=PROJECT_ROOT / "benchmarks/evaluation_split_manifest_results.json",
    )
    parser.add_argument(
        "--judge-policy",
        type=Path,
        default=PROJECT_ROOT / "benchmarks/evaluation_judge_policy_results.json",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=PROJECT_ROOT / "benchmarks/evaluation_development_protocol_v1.json",
    )
    args = parser.parse_args(argv)
    payload = build_evaluation_development_protocol(
        project_root=PROJECT_ROOT,
        dataset_manifest_path=args.dataset_manifest,
        split_manifest_path=args.split_manifest,
        judge_policy_path=args.judge_policy,
    )
    errors = validate_evaluation_development_protocol(
        payload,
        project_root=PROJECT_ROOT,
        dataset_manifest_path=args.dataset_manifest,
        split_manifest_path=args.split_manifest,
        judge_policy_path=args.judge_policy,
    )
    if errors:
        print(json.dumps({"status": "blocked", "errors": errors}, indent=2))
        return 2
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(payload, indent=2, ensure_ascii=True) + "\n", encoding="utf-8"
    )
    print(
        json.dumps(
            {
                "status": "frozen",
                "source_sha": payload["source_sha"],
                "unit_count": payload["bounded_sample"]["unit_count"],
                "heldout_access": payload["heldout_access"],
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
