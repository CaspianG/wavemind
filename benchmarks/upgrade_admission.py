from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from wavemind.upgrade_admission import (
    evaluate_upgrade_admission,
    render_upgrade_admission_markdown,
)


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--operational", type=Path, required=True)
    parser.add_argument("--cross-version", type=Path, required=True)
    parser.add_argument("--docker-compose", type=Path, required=True)
    parser.add_argument("--expected-source-sha", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--markdown-output", type=Path, required=True)
    parser.add_argument("--require-admitted", action="store_true")
    args = parser.parse_args()
    report = evaluate_upgrade_admission(
        operational=_load(args.operational),
        cross_version=_load(args.cross_version),
        docker_compose=_load(args.docker_compose),
        project_root=PROJECT_ROOT,
        expected_source_sha=args.expected_source_sha,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.markdown_output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    args.markdown_output.write_text(render_upgrade_admission_markdown(report), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 2 if args.require_admitted and report["status"] != "admitted" else 0


if __name__ == "__main__":
    raise SystemExit(main())
