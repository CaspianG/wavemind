from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
TARGET_RECALL_FLOOR = 0.95
TARGET_P99_CEILING_MS = 100.0
ACCEPTED_SLO_STATUSES = {"pass", "scale_required"}
ACCEPTED_COST_STATUSES = {"valid_slo"}


@dataclass(frozen=True)
class ExpectedArtifact:
    filename: str
    engine: str
    vectors: int
    description: str


EXPECTED_ARTIFACTS: dict[str, ExpectedArtifact] = {
    "production_streaming_load_qdrant_10m_results.json": ExpectedArtifact(
        filename="production_streaming_load_qdrant_10m_results.json",
        engine="Qdrant service streaming",
        vectors=10_000_000,
        description="single-service Qdrant 10M production streaming result",
    ),
    "production_streaming_load_qdrant_sharded_10m_results.json": ExpectedArtifact(
        filename="production_streaming_load_qdrant_sharded_10m_results.json",
        engine="Qdrant sharded service streaming",
        vectors=10_000_000,
        description="horizontally sharded Qdrant 10M production streaming result",
    ),
    "production_streaming_load_qdrant_sharded_100m_results.json": ExpectedArtifact(
        filename="production_streaming_load_qdrant_sharded_100m_results.json",
        engine="Qdrant sharded service streaming",
        vectors=100_000_000,
        description="horizontally sharded Qdrant 100M production streaming result",
    ),
    "production_streaming_load_pgvector_10m_results.json": ExpectedArtifact(
        filename="production_streaming_load_pgvector_10m_results.json",
        engine="WaveMind pgvector streaming",
        vectors=10_000_000,
        description="PostgreSQL pgvector 10M production streaming result",
    ),
    "production_streaming_load_ivfpq_50m_results.json": ExpectedArtifact(
        filename="production_streaming_load_ivfpq_50m_results.json",
        engine="WaveMind faiss-ivfpq-persisted streaming",
        vectors=50_000_000,
        description="compressed FAISS IVF-PQ 50M production streaming result",
    ),
}


class ArtifactValidationError(ValueError):
    pass


def load_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ArtifactValidationError(f"{path.name}: invalid JSON: {exc}") from exc
    if not isinstance(payload, dict):
        raise ArtifactValidationError(f"{path.name}: expected a JSON object")
    return payload


def result_rows(payload: dict[str, Any]) -> list[tuple[dict[str, Any], dict[str, Any]]]:
    rows: list[tuple[dict[str, Any], dict[str, Any]]] = []
    for group in payload.get("results", []):
        if not isinstance(group, dict):
            continue
        for row in group.get("results", []):
            if isinstance(row, dict):
                rows.append((group, row))
    return rows


def _require_number(row: dict[str, Any], key: str, filename: str) -> float:
    value = row.get(key)
    if not isinstance(value, int | float):
        raise ArtifactValidationError(f"{filename}: result row missing numeric {key}")
    return float(value)


def validate_artifact(path: Path, expected: ExpectedArtifact) -> dict[str, Any]:
    payload = load_json(path)
    scenario = payload.get("scenario")
    if not isinstance(scenario, dict) or scenario.get("name") != "production_streaming_load_profile":
        raise ArtifactValidationError(
            f"{path.name}: scenario.name must be production_streaming_load_profile"
        )

    matches = [
        (group, row)
        for group, row in result_rows(payload)
        if row.get("engine") == expected.engine
    ]
    if not matches:
        engines = sorted({str(row.get("engine")) for _, row in result_rows(payload)})
        raise ArtifactValidationError(
            f"{path.name}: expected engine {expected.engine!r}; found {engines or 'none'}"
        )

    group, row = matches[0]
    group_vectors = group.get("vectors")
    row_vectors = row.get("vectors")
    if group_vectors != expected.vectors or row_vectors != expected.vectors:
        raise ArtifactValidationError(
            f"{path.name}: expected {expected.vectors} vectors; "
            f"group has {group_vectors!r}, row has {row_vectors!r}"
        )
    if row.get("skipped"):
        raise ArtifactValidationError(f"{path.name}: production proof row is skipped")

    recall = _require_number(row, "target_recall_at_k", path.name)
    p99_ms = _require_number(row, "p99_latency_ms", path.name)
    if recall < TARGET_RECALL_FLOOR:
        raise ArtifactValidationError(
            f"{path.name}: target_recall_at_k {recall:.3f} is below {TARGET_RECALL_FLOOR:.3f}"
        )
    if p99_ms > TARGET_P99_CEILING_MS:
        raise ArtifactValidationError(
            f"{path.name}: p99_latency_ms {p99_ms:.2f} exceeds {TARGET_P99_CEILING_MS:.2f}"
        )

    slo_status = str(row.get("slo_status", ""))
    if slo_status not in ACCEPTED_SLO_STATUSES:
        raise ArtifactValidationError(
            f"{path.name}: slo_status {slo_status!r} is not one of "
            f"{sorted(ACCEPTED_SLO_STATUSES)}"
        )
    cost_status = str(row.get("cost_status", ""))
    if cost_status not in ACCEPTED_COST_STATUSES:
        raise ArtifactValidationError(
            f"{path.name}: cost_status {cost_status!r} is not one of "
            f"{sorted(ACCEPTED_COST_STATUSES)}"
        )

    return {
        "filename": path.name,
        "description": expected.description,
        "engine": expected.engine,
        "vectors": expected.vectors,
        "target_recall_at_k": recall,
        "p99_latency_ms": p99_ms,
        "slo_status": slo_status,
        "cost_status": cost_status,
    }


def discover_expected_artifacts(artifact_dir: Path) -> list[tuple[Path, ExpectedArtifact]]:
    discovered: list[tuple[Path, ExpectedArtifact]] = []
    for path in sorted(artifact_dir.rglob("production_streaming_load_*_results.json")):
        expected = EXPECTED_ARTIFACTS.get(path.name)
        if expected:
            discovered.append((path, expected))
    return discovered


def refresh_commands() -> list[list[str]]:
    python = sys.executable
    return [
        [python, "benchmarks/benchmark_registry.py", "--output", "benchmarks/benchmark_matrix_results.json"],
        [python, "benchmarks/render_benchmark_report.py"],
        [python, "benchmarks/render_benchmark_leaderboard.py"],
        [
            python,
            "benchmarks/render_benchmark_charts.py",
            "--output",
            "docs/assets/benchmark-summary.svg",
        ],
        [
            python,
            "benchmarks/render_benchmark_dashboard.py",
            "--output",
            "docs/benchmark-dashboard.html",
        ],
        [
            python,
            "benchmarks/validate_benchmark_artifacts.py",
            "--max-age-days",
            "8",
            "--output",
            "benchmarks/benchmark_artifact_audit.json",
        ],
        [
            python,
            "benchmarks/production_readiness_gate.py",
            "--output",
            "benchmarks/production_readiness_results.json",
            "--markdown-output",
            "benchmarks/PRODUCTION_READINESS.md",
        ],
        [
            python,
            "benchmarks/production_evidence_gate.py",
            "--output",
            "benchmarks/production_evidence_results.json",
            "--markdown-output",
            "benchmarks/PRODUCTION_EVIDENCE.md",
        ],
        [
            python,
            "benchmarks/render_leaderboard_status.py",
            "--output",
            "docs/data/leaderboard-status.json",
        ],
    ]


def run_refresh(output_root: Path) -> None:
    for command in refresh_commands():
        subprocess.run(command, cwd=output_root, check=True)


def _copy_atomic(source: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    temp = destination.with_suffix(destination.suffix + ".tmp")
    shutil.copy2(source, temp)
    temp.replace(destination)


def ingest_artifacts(
    artifact_dir: Path,
    output_root: Path = PROJECT_ROOT,
    *,
    dry_run: bool = False,
    refresh: bool = False,
    manifest_path: Path | None = None,
) -> dict[str, Any]:
    if not artifact_dir.exists():
        raise FileNotFoundError(f"artifact directory does not exist: {artifact_dir}")
    if not artifact_dir.is_dir():
        raise NotADirectoryError(f"artifact path is not a directory: {artifact_dir}")

    artifacts = discover_expected_artifacts(artifact_dir)
    if not artifacts:
        expected = ", ".join(sorted(EXPECTED_ARTIFACTS))
        raise ArtifactValidationError(
            f"no recognized production streaming result artifacts found under {artifact_dir}; "
            f"expected one of: {expected}"
        )

    ingested: list[dict[str, Any]] = []
    for source, expected in artifacts:
        summary = validate_artifact(source, expected)
        destination = output_root / "benchmarks" / source.name
        summary["source"] = str(source)
        summary["destination"] = str(destination)
        summary["copied"] = not dry_run
        ingested.append(summary)
        if not dry_run:
            _copy_atomic(source, destination)

    manifest = {
        "schema": "wavemind.production_streaming_artifact_ingest.v1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "artifact_dir": str(artifact_dir),
        "output_root": str(output_root),
        "dry_run": dry_run,
        "refresh_requested": refresh,
        "ingested": ingested,
        "refresh_commands": refresh_commands(),
        "next_step": (
            "Review git diff, run tests, then commit from a maintainer account."
            if not dry_run
            else "Dry run only; rerun without --dry-run to copy validated artifacts."
        ),
    }

    if manifest_path is not None and not dry_run:
        manifest_path.parent.mkdir(parents=True, exist_ok=True)
        manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")

    if refresh and not dry_run:
        run_refresh(output_root)

    return manifest


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Validate and ingest production-streaming-load GitHub Actions artifacts "
            "into checked-in benchmark evidence."
        )
    )
    parser.add_argument("--artifact-dir", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, default=PROJECT_ROOT)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--refresh", action="store_true")
    parser.add_argument(
        "--manifest",
        type=Path,
        default=Path("benchmarks/production_streaming_artifact_ingest.json"),
        help="Optional ingest manifest path, relative to output root unless absolute.",
    )
    args = parser.parse_args(argv)

    manifest_path = args.manifest
    if manifest_path is not None and not manifest_path.is_absolute():
        manifest_path = args.output_root / manifest_path

    try:
        manifest = ingest_artifacts(
            artifact_dir=args.artifact_dir,
            output_root=args.output_root,
            dry_run=args.dry_run,
            refresh=args.refresh,
            manifest_path=manifest_path,
        )
    except (ArtifactValidationError, FileNotFoundError, NotADirectoryError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    print(json.dumps(manifest, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
