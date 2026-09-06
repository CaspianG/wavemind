from __future__ import annotations

import argparse
import json
import os
import subprocess
from pathlib import Path

from wavemind.scientific_state_bench import (
    prepare_state_bench_development_store,
    validate_prepared_state_bench_artifact,
)


def _source_sha(project_root: Path) -> str:
    return subprocess.check_output(
        ["git", "rev-parse", "HEAD"],
        cwd=project_root,
        text=True,
        encoding="utf-8",
    ).strip()


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Prepare leak-free STATE-Bench bounded-development memory store."
    )
    parser.add_argument("--project-root", type=Path, default=Path.cwd())
    parser.add_argument("--state-bench-root", type=Path, required=True)
    parser.add_argument("--split-manifest", type=Path, required=True)
    parser.add_argument("--protocol", type=Path, required=True)
    parser.add_argument("--domain", default="travel")
    parser.add_argument("--database", type=Path, required=True)
    parser.add_argument("--learning-manifest", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    if args.output.exists():
        raise FileExistsError(f"prepared artifact is retained: {args.output}")
    split_manifest = json.loads(args.split_manifest.read_text(encoding="utf-8"))
    protocol = json.loads(args.protocol.read_text(encoding="utf-8"))
    protocol_digest = str(protocol.get("protocol_digest") or "")
    if not protocol_digest:
        raise ValueError("frozen protocol digest is missing")
    payload = prepare_state_bench_development_store(
        project_root=args.project_root.resolve(),
        state_bench_root=args.state_bench_root.resolve(),
        split_manifest=split_manifest,
        protocol_digest=protocol_digest,
        source_sha=_source_sha(args.project_root.resolve()),
        domain=args.domain,
        database_path=args.database.resolve(),
        learning_manifest_path=args.learning_manifest.resolve(),
        environment=os.environ,
    )
    errors = validate_prepared_state_bench_artifact(payload)
    if errors:
        raise RuntimeError(
            "prepared STATE-Bench artifact invalid: " + "; ".join(errors)
        )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(payload, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
