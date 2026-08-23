from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from wavemind.scientific_preflight import (
    evaluate_scientific_memory_preflight,
    render_scientific_memory_preflight_markdown,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Check exact-SHA scientific memory experiment prerequisites"
    )
    parser.add_argument(
        "--protocol",
        type=Path,
        default=ROOT / "benchmarks" / "scientific_memory_protocol_v1.json",
    )
    parser.add_argument(
        "--dataset-manifest",
        type=Path,
        default=ROOT / "benchmarks" / "evaluation_dataset_manifest_v1.json",
    )
    parser.add_argument(
        "--run-dir",
        type=Path,
        default=ROOT / "benchmarks" / "scientific_memory_runs",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=ROOT / "benchmarks" / "scientific_memory_preflight_results.json",
    )
    parser.add_argument(
        "--markdown",
        type=Path,
        default=ROOT / "benchmarks" / "SCIENTIFIC_MEMORY_PREFLIGHT.md",
    )
    parser.add_argument("--fail-on-action-required", action="store_true")
    args = parser.parse_args(argv)
    payload = evaluate_scientific_memory_preflight(
        project_root=ROOT,
        protocol_path=args.protocol,
        dataset_manifest_path=args.dataset_manifest,
        run_dir=args.run_dir,
    )
    args.output.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    args.markdown.write_text(
        render_scientific_memory_preflight_markdown(payload), encoding="utf-8"
    )
    print(json.dumps(payload, indent=2, ensure_ascii=False))
    return int(args.fail_on_action_required and not payload["ready"])


if __name__ == "__main__":
    raise SystemExit(main())
