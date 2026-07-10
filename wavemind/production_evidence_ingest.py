from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .production_evidence import evaluate_production_evidence


PROJECT_ROOT = Path.cwd()


class ProductionEvidenceIngestError(ValueError):
    pass


@dataclass(frozen=True)
class ExpectedEvidenceArtifact:
    filename: str
    destination: str
    requirement_id: str
    description: str
    optional_dependencies: tuple[str, ...] = ()


EXPECTED_EVIDENCE_ARTIFACTS: dict[str, ExpectedEvidenceArtifact] = {
    "http_cluster_load_results.json": ExpectedEvidenceArtifact(
        filename="http_cluster_load_results.json",
        destination="benchmarks/http_cluster_load_results.json",
        requirement_id="external_http_cluster",
        description="non-loopback Kubernetes/staging/production HTTP service-node load result",
        optional_dependencies=("kubernetes_cluster_network_smoke_results.json",),
    ),
    "external_http_active_active_results.json": ExpectedEvidenceArtifact(
        filename="external_http_active_active_results.json",
        destination="benchmarks/external_http_active_active_results.json",
        requirement_id="external_http_active_active",
        description="remote/staging/production active-active API-region result",
    ),
    "observed-telemetry.remote.json": ExpectedEvidenceArtifact(
        filename="observed-telemetry.remote.json",
        destination="deploy/serverless/observed-telemetry.remote.json",
        requirement_id="serverless_remote_telemetry",
        description="managed/serverless remote telemetry result",
    ),
    "production_streaming_load_qdrant_10m_results.json": ExpectedEvidenceArtifact(
        filename="production_streaming_load_qdrant_10m_results.json",
        destination="benchmarks/production_streaming_load_qdrant_10m_results.json",
        requirement_id="qdrant_10m_service",
        description="single-service Qdrant 10M production streaming result",
    ),
    "production_streaming_load_qdrant_sharded_10m_results.json": ExpectedEvidenceArtifact(
        filename="production_streaming_load_qdrant_sharded_10m_results.json",
        destination="benchmarks/production_streaming_load_qdrant_sharded_10m_results.json",
        requirement_id="qdrant_sharded_10m_service",
        description="horizontally sharded Qdrant 10M production streaming result",
    ),
    "production_streaming_load_pgvector_10m_results.json": ExpectedEvidenceArtifact(
        filename="production_streaming_load_pgvector_10m_results.json",
        destination="benchmarks/production_streaming_load_pgvector_10m_results.json",
        requirement_id="pgvector_10m_service",
        description="PostgreSQL pgvector 10M production streaming result",
    ),
    "production_streaming_load_ivfpq_50m_results.json": ExpectedEvidenceArtifact(
        filename="production_streaming_load_ivfpq_50m_results.json",
        destination="benchmarks/production_streaming_load_ivfpq_50m_results.json",
        requirement_id="faiss_ivfpq_50m",
        description="compressed FAISS IVF-PQ 50M production streaming result",
    ),
    "production_streaming_load_qdrant_sharded_100m_results.json": ExpectedEvidenceArtifact(
        filename="production_streaming_load_qdrant_sharded_100m_results.json",
        destination="benchmarks/production_streaming_load_qdrant_sharded_100m_results.json",
        requirement_id="hundred_million_remote_load",
        description="horizontally sharded Qdrant 100M production streaming result",
    ),
}


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def load_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
    except json.JSONDecodeError as exc:
        raise ProductionEvidenceIngestError(f"{path.name}: invalid JSON: {exc}") from exc
    if not isinstance(payload, dict):
        raise ProductionEvidenceIngestError(f"{path.name}: expected a JSON object")
    return payload


def discover_expected_artifacts(artifact_dir: Path) -> list[tuple[Path, ExpectedEvidenceArtifact]]:
    discovered: list[tuple[Path, ExpectedEvidenceArtifact]] = []
    for path in sorted(artifact_dir.rglob("*.json")):
        expected = EXPECTED_EVIDENCE_ARTIFACTS.get(path.name)
        if expected is not None:
            discovered.append((path, expected))
    return discovered


def _copy_atomic(source: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    temp = destination.with_suffix(destination.suffix + ".tmp")
    shutil.copy2(source, temp)
    temp.replace(destination)


def _dependency_sources(
    artifact_dir: Path,
    expected: ExpectedEvidenceArtifact,
) -> list[Path]:
    sources: list[Path] = []
    for filename in expected.optional_dependencies:
        matches = sorted(artifact_dir.rglob(filename))
        if matches:
            sources.append(matches[0])
    return sources


def _validate_with_strict_gate(
    source: Path,
    expected: ExpectedEvidenceArtifact,
    *,
    artifact_dir: Path,
) -> dict[str, Any]:
    load_json(source)
    dependencies = _dependency_sources(artifact_dir, expected)
    with tempfile.TemporaryDirectory(prefix="wavemind-evidence-ingest-") as directory:
        temp_root = Path(directory)
        destination = temp_root / expected.destination
        _copy_atomic(source, destination)
        for dependency in dependencies:
            _copy_atomic(dependency, temp_root / "benchmarks" / dependency.name)
        payload = evaluate_production_evidence(temp_root)
    requirements = {
        str(row.get("id")): row
        for row in payload.get("requirements", [])
        if isinstance(row, dict)
    }
    row = requirements.get(expected.requirement_id)
    if not row:
        raise ProductionEvidenceIngestError(
            f"{source.name}: strict evidence gate did not produce {expected.requirement_id}"
        )
    if row.get("status") != "pass":
        issues = ", ".join(str(issue) for issue in row.get("issues") or ())
        evidence = str(row.get("evidence") or "")
        detail = f"; issues: {issues}" if issues else ""
        raise ProductionEvidenceIngestError(
            f"{source.name}: {expected.description} failed strict evidence validation: "
            f"{evidence}{detail}"
        )
    return {
        "filename": source.name,
        "description": expected.description,
        "requirement_id": expected.requirement_id,
        "status": row.get("status"),
        "evidence": row.get("evidence"),
        "artifact": expected.destination,
        "claim_unlocked": row.get("claim_unlocked"),
        "dependencies": [path.name for path in dependencies],
    }


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
        [python, "-m", "wavemind", "production-evidence-preflight", "--write-artifacts"],
        [python, "-m", "wavemind", "production-evidence-dispatch", "--write-artifacts"],
        [python, "-m", "wavemind", "production-evidence-bundle", "--write-artifacts"],
        [python, "-m", "wavemind", "release-claims", "--write-artifacts"],
        [python, "-m", "wavemind", "scale-gap", "--write-artifacts"],
        [
            python,
            "benchmarks/strict_evidence_readiness_report.py",
            "--output",
            "benchmarks/strict_evidence_readiness_results.json",
            "--markdown-output",
            "benchmarks/STRICT_EVIDENCE_READINESS.md",
        ],
        [
            python,
            "-m",
            "wavemind",
            "production-admission",
            "--target-memories",
            "100000000",
            "--engine",
            "qdrant-sharded-service",
            "--allow-plan-only",
            "--write-artifacts",
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


def ingest_production_evidence_artifacts(
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
        expected = ", ".join(sorted(EXPECTED_EVIDENCE_ARTIFACTS))
        raise ProductionEvidenceIngestError(
            f"no recognized production evidence artifacts found under {artifact_dir}; "
            f"expected one of: {expected}"
        )

    ingested: list[dict[str, Any]] = []
    for source, expected in artifacts:
        dependencies = _dependency_sources(artifact_dir, expected)
        summary = _validate_with_strict_gate(
            source,
            expected,
            artifact_dir=artifact_dir,
        )
        destination = output_root / expected.destination
        summary["source"] = str(source)
        summary["destination"] = str(destination)
        summary["copied"] = not dry_run
        ingested.append(summary)
        if not dry_run:
            _copy_atomic(source, destination)
            for dependency in dependencies:
                _copy_atomic(
                    dependency,
                    output_root / "benchmarks" / dependency.name,
                )

    manifest = {
        "schema": "wavemind.production_evidence_artifact_ingest.v1",
        "generated_at": _utc_now_iso(),
        "artifact_dir": str(artifact_dir),
        "output_root": str(output_root),
        "dry_run": dry_run,
        "refresh_requested": refresh,
        "ingested_count": len(ingested),
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
        manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    if refresh and not dry_run:
        run_refresh(output_root)

    return manifest
