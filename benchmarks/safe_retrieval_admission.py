from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from wavemind.safe_retrieval_admission import evaluate_safe_retrieval_admission


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--dataset",
        type=Path,
        default=Path("benchmarks/data/safe_product_retrieval_v3_holdout.json"),
    )
    parser.add_argument(
        "--protocol",
        type=Path,
        default=Path("benchmarks/data/safe_product_retrieval_v3_protocol.json"),
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("benchmarks/safe_retrieval_admission_results.json"),
    )
    parser.add_argument("--require-admitted", action="store_true")
    args = parser.parse_args()
    report = evaluate_safe_retrieval_admission(
        args.dataset,
        protocol_path=args.protocol,
        project_root=PROJECT_ROOT,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 2 if args.require_admitted and report["status"] != "admitted" else 0


if __name__ == "__main__":
    raise SystemExit(main())
