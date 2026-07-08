from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from wavemind.production_evidence_ingest import (
    ProductionEvidenceIngestError,
    ingest_production_evidence_artifacts,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Validate and ingest strict production evidence artifacts from "
            "GitHub Actions or remote benchmark runs."
        )
    )
    parser.add_argument("--artifact-dir", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, default=PROJECT_ROOT)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--refresh", action="store_true")
    parser.add_argument(
        "--manifest",
        type=Path,
        default=Path("benchmarks/production_evidence_artifact_ingest.json"),
        help="Optional ingest manifest path, relative to output root unless absolute.",
    )
    args = parser.parse_args(argv)

    manifest_path = args.manifest
    if manifest_path is not None and not manifest_path.is_absolute():
        manifest_path = args.output_root / manifest_path

    try:
        manifest = ingest_production_evidence_artifacts(
            artifact_dir=args.artifact_dir,
            output_root=args.output_root,
            dry_run=args.dry_run,
            refresh=args.refresh,
            manifest_path=manifest_path,
        )
    except (ProductionEvidenceIngestError, FileNotFoundError, NotADirectoryError) as exc:
        print(f"error: {exc}")
        return 2

    print(json.dumps(manifest, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
