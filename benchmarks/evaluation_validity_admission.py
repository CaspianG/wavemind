from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from wavemind.evaluation_validity_admission import (
    render_evaluation_validity_markdown,
    run_evaluation_validity_admission,
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--dataset-manifest",
        type=Path,
        default=Path("benchmarks/evaluation_dataset_manifest_v1.json"),
    )
    parser.add_argument("--validity-evidence", type=Path)
    parser.add_argument("--expected-source-sha")
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("benchmarks/evaluation_validity_admission_results.json"),
    )
    parser.add_argument(
        "--markdown-output",
        type=Path,
        default=Path("benchmarks/EVALUATION_VALIDITY_ADMISSION.md"),
    )
    parser.add_argument("--require-admitted", action="store_true")
    args = parser.parse_args()
    report = run_evaluation_validity_admission(
        project_root=PROJECT_ROOT,
        dataset_manifest_path=args.dataset_manifest,
        validity_evidence_path=args.validity_evidence,
        expected_source_sha=args.expected_source_sha,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    args.markdown_output.parent.mkdir(parents=True, exist_ok=True)
    args.markdown_output.write_text(
        render_evaluation_validity_markdown(report), encoding="utf-8"
    )
    summary = {
        "status": report["status"],
        "source_sha": report["source_sha"],
        "implemented_rows": report["implemented_rows"],
        "required_rows": report["required_rows"],
        "output": str(args.output),
    }
    print(json.dumps(summary))
    return 2 if args.require_admitted and not report["admitted"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
