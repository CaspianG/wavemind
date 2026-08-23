from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from wavemind.evidence import repository_commit
from wavemind.scientific_admission import (
    evaluate_scientific_memory_admission,
    render_scientific_memory_admission_markdown,
)


DEFAULT_PROTOCOL = ROOT / "benchmarks" / "scientific_memory_protocol_v1.json"
DEFAULT_RUN_DIR = ROOT / "benchmarks" / "scientific_memory_runs"
DEFAULT_JSON = ROOT / "benchmarks" / "scientific_memory_admission_results.json"
DEFAULT_MARKDOWN = ROOT / "benchmarks" / "SCIENTIFIC_MEMORY_ADMISSION.md"


def _load_runs(run_dir: Path) -> list[dict[str, Any]]:
    payloads: list[dict[str, Any]] = []
    if not run_dir.is_dir():
        return payloads
    for path in sorted(run_dir.glob("*.json")):
        value = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(value, dict):
            raise ValueError(f"scientific run artifact must be an object: {path}")
        payloads.append(value)
    return payloads


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Fail-closed exact-SHA scientific memory admission"
    )
    parser.add_argument("--protocol", type=Path, default=DEFAULT_PROTOCOL)
    parser.add_argument("--run-dir", type=Path, default=DEFAULT_RUN_DIR)
    parser.add_argument("--output", type=Path, default=DEFAULT_JSON)
    parser.add_argument("--markdown", type=Path, default=DEFAULT_MARKDOWN)
    parser.add_argument("--source-sha")
    parser.add_argument("--fail-on-failed-experiment", action="store_true")
    args = parser.parse_args(argv)

    source_sha = args.source_sha or repository_commit(ROOT)
    payload = evaluate_scientific_memory_admission(
        _load_runs(args.run_dir),
        protocol_path=args.protocol,
        project_root=ROOT,
        expected_source_sha=source_sha,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.markdown.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    args.markdown.write_text(
        render_scientific_memory_admission_markdown(payload),
        encoding="utf-8",
    )
    print(json.dumps(payload, indent=2, ensure_ascii=False))
    return int(args.fail_on_failed_experiment and not payload["admitted"])


if __name__ == "__main__":
    raise SystemExit(main())
