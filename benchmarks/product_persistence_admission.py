from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from wavemind.product_persistence_admission import run_product_persistence_admission


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--image", required=True)
    parser.add_argument("--state-root", type=Path)
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("benchmarks/product_persistence_admission_results.json"),
    )
    args = parser.parse_args()
    report = run_product_persistence_admission(
        image=args.image,
        project_root=PROJECT_ROOT,
        state_root=args.state_root,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["status"] == "admitted" else 2


if __name__ == "__main__":
    raise SystemExit(main())
