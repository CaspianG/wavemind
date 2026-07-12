from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from wavemind.cloud_run_evidence import (  # noqa: E402
    CloudRunEvidenceError,
    collect_cloud_run_managed_telemetry,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Build provider-observed managed Cloud Run evidence"
    )
    parser.add_argument("--project-id", required=True)
    parser.add_argument("--region", required=True)
    parser.add_argument("--service-name", required=True)
    parser.add_argument("--load-result", type=Path, required=True)
    parser.add_argument("--metric-window-start", required=True)
    parser.add_argument("--metric-window-end", required=True)
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("deploy/serverless/observed-telemetry.remote.json"),
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        payload = collect_cloud_run_managed_telemetry(
            project_id=args.project_id,
            region=args.region,
            service_name=args.service_name,
            load_result_path=args.load_result,
            metric_window_start=args.metric_window_start,
            metric_window_end=args.metric_window_end,
        )
    except (CloudRunEvidenceError, OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"cloud-run-evidence: {exc}", file=sys.stderr)
        return 2
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(payload, indent=2))
    return 0 if payload.get("observed_slo_pass") else 1


if __name__ == "__main__":
    raise SystemExit(main())
