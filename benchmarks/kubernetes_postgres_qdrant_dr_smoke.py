#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from benchmarks.kubernetes_serverless_lifecycle_smoke import (  # noqa: E402
    API_KEY,
    _json,
    _ready,
    _run,
    _wait_for,
    _workload,
    build_serverless_resources,
)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _source_provenance(payload: dict[str, Any]) -> dict[str, Any]:
    source_ref = str(os.getenv("GITHUB_SHA") or "").strip()
    workflow_run_id = str(os.getenv("GITHUB_RUN_ID") or "").strip()
    repository = str(os.getenv("GITHUB_REPOSITORY") or "").strip()
    server_url = str(os.getenv("GITHUB_SERVER_URL") or "https://github.com").rstrip("/")
    if source_ref:
        payload["source_ref"] = source_ref
    if workflow_run_id:
        payload["workflow_run_id"] = workflow_run_id
    if workflow_run_id and repository:
        payload["workflow_run_url"] = (
            f"{server_url}/{repository}/actions/runs/{workflow_run_id}"
        )
    return payload


def evaluate_kubernetes_postgres_qdrant_dr_smoke(
    observed: dict[str, Any],
) -> dict[str, Any]:
    restored = dict(observed.get("restored") or {})
    replaced = dict(observed.get("restored_after_api_replacement") or {})
    stats = dict(observed.get("recovery_stats") or {})
    checks = [
        {
            "id": "source_and_recovery_non_loopback",
            "passed": (
                ".svc.cluster.local" in str(observed.get("source_service") or "")
                and ".svc.cluster.local" in str(observed.get("recovery_service") or "")
                and observed.get("source_namespace") != observed.get("recovery_namespace")
            ),
            "observed": {
                "source": observed.get("source_service"),
                "recovery": observed.get("recovery_service"),
            },
            "required": "distinct non-loopback Kubernetes service DNS endpoints",
        },
        {
            "id": "postgres_backup_materialized",
            "passed": (
                observed.get("backup_format") == "pg_dump-custom"
                and int(observed.get("backup_bytes") or 0) > 0
                and len(str(observed.get("backup_sha256") or "")) == 64
            ),
            "observed": {
                "format": observed.get("backup_format"),
                "bytes": observed.get("backup_bytes"),
                "sha256": observed.get("backup_sha256"),
            },
            "required": "non-empty checksummed pg_dump custom archive",
        },
        {
            "id": "source_state_services_stopped",
            "passed": observed.get("source_state_stopped") is True,
            "observed": observed.get("source_state_stopped"),
            "required": True,
        },
        {
            "id": "fresh_recovery_state",
            "passed": (
                observed.get("recovery_services") == ["postgres", "qdrant", "redis"]
                and int(observed.get("recovery_pvcs") or 0) >= 3
            ),
            "observed": {
                "services": observed.get("recovery_services"),
                "pvcs": observed.get("recovery_pvcs"),
            },
            "required": {"services": ["postgres", "qdrant", "redis"], "pvcs": ">=3"},
        },
        {
            "id": "postgres_restore_completed",
            "passed": observed.get("postgres_restore_completed") is True,
            "observed": observed.get("postgres_restore_completed"),
            "required": True,
        },
        {
            "id": "all_memories_recalled_after_restore",
            "passed": float(restored.get("rate") or 0.0) >= 1.0,
            "observed": restored.get("rate"),
            "required": 1.0,
        },
        {
            "id": "qdrant_rebuilt_from_postgres",
            "passed": (
                stats.get("index_healthy") is True
                and int(stats.get("index_expected_records") or -1)
                == int(observed.get("memory_count") or -2)
                and int(stats.get("index_vector_records") or -1)
                == int(observed.get("memory_count") or -2)
                and int(stats.get("index_missing_records", -1)) == 0
                and int(stats.get("index_extra_records", -1)) == 0
            ),
            "observed": {
                "healthy": stats.get("index_healthy"),
                "expected": stats.get("index_expected_records"),
                "vectors": stats.get("index_vector_records"),
                "missing": stats.get("index_missing_records"),
                "extra": stats.get("index_extra_records"),
            },
            "required": "Qdrant exactly rebuilt from restored PostgreSQL rows",
        },
        {
            "id": "recovery_api_replaced",
            "passed": (
                bool(observed.get("recovery_api_uid_before"))
                and observed.get("recovery_api_uid_before")
                != observed.get("recovery_api_uid_after")
            ),
            "observed": {
                "before": observed.get("recovery_api_uid_before"),
                "after": observed.get("recovery_api_uid_after"),
            },
            "required": "replacement pod UID differs",
        },
        {
            "id": "recall_survives_recovery_api_replacement",
            "passed": float(replaced.get("rate") or 0.0) >= 1.0,
            "observed": replaced.get("rate"),
            "required": 1.0,
        },
        {
            "id": "restore_time_budget",
            "passed": float(observed.get("restore_elapsed_ms") or float("inf"))
            <= float(observed.get("restore_budget_ms") or 0.0),
            "observed": observed.get("restore_elapsed_ms"),
            "required": f"<= {observed.get('restore_budget_ms')} ms",
        },
    ]
    passed = sum(bool(check["passed"]) for check in checks)
    return _source_provenance(
        {
            "schema": "wavemind.kubernetes_postgres_qdrant_dr_smoke.v1",
            "generated_at": _utc_now(),
            "environment": "kind-independent-namespace-postgres-qdrant-dr-ci",
            "evidence_source": "github-actions-kind-pg-dump-independent-restore",
            "claim_boundary": (
                "Ephemeral non-loopback Kubernetes disaster-recovery evidence. "
                "It proves logical PostgreSQL backup/restore and Qdrant rebuild in "
                "an independent namespace, not managed-cloud PITR or multi-region DR."
            ),
            "status": "pass" if passed == len(checks) else "fail",
            "summary": {
                "check_count": len(checks),
                "passed_checks": passed,
                "failed_checks": len(checks) - passed,
            },
            "checks": checks,
            "observed": observed,
        }
    )


def _apply_resources(args: argparse.Namespace, namespace: str) -> None:
    try:
        _run(args.kubectl, "create", "namespace", namespace)
    except RuntimeError as exc:
        if "AlreadyExists" not in str(exc):
            raise
    resources = {
        "apiVersion": "v1",
        "kind": "List",
        "items": build_serverless_resources(
            namespace=namespace,
            image=args.image,
            postgres_image=args.postgres_image,
            qdrant_image=args.qdrant_image,
            redis_image=args.redis_image,
        ),
    }
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".json", encoding="utf-8", delete=False
    ) as handle:
        json.dump(resources, handle)
        manifest_path = Path(handle.name)
    try:
        _run(args.kubectl, "apply", "-f", str(manifest_path), timeout=180.0)
    finally:
        manifest_path.unlink(missing_ok=True)


def _ready_api_pods(kubectl: str, namespace: str) -> list[dict[str, Any]]:
    payload = _json(
        kubectl,
        "get",
        "pods",
        "-n",
        namespace,
        "-l",
        "app.kubernetes.io/component=serverless-api-keda",
    )
    return [pod for pod in payload.get("items") or [] if _ready(pod)]


def run_smoke(args: argparse.Namespace) -> dict[str, Any]:
    started = time.perf_counter()
    source_service = (
        f"http://wavemind-serverless-keda.{args.source_namespace}."
        "svc.cluster.local:8000"
    )
    recovery_service = (
        f"http://wavemind-serverless-keda.{args.recovery_namespace}."
        "svc.cluster.local:8000"
    )
    backup_fd, backup_name = tempfile.mkstemp(suffix=".pgdump")
    os.close(backup_fd)
    backup_path = Path(backup_name)
    try:
        _run(
            args.kubectl,
            "exec",
            "postgres-0",
            "-n",
            args.source_namespace,
            "--",
            "pg_dump",
            "-U",
            "wavemind",
            "-d",
            "wavemind",
            "-Fc",
            "-f",
            "/tmp/wavemind-dr.pgdump",
            timeout=180.0,
        )
        _run(
            args.kubectl,
            "cp",
            f"{args.source_namespace}/postgres-0:/tmp/wavemind-dr.pgdump",
            str(backup_path),
            timeout=180.0,
        )
        backup_bytes = backup_path.stat().st_size
        backup_sha256 = hashlib.sha256(backup_path.read_bytes()).hexdigest()

        for resource in (
            "deployment/wavemind-serverless-keda",
            "statefulset/postgres",
            "statefulset/qdrant",
            "statefulset/redis",
        ):
            _run(
                args.kubectl,
                "scale",
                resource,
                "-n",
                args.source_namespace,
                "--replicas=0",
            )

        def source_stopped() -> bool | None:
            pods = _json(args.kubectl, "get", "pods", "-n", args.source_namespace)
            active = {
                str((pod.get("metadata") or {}).get("name") or "")
                for pod in pods.get("items") or []
            }
            blocked = {
                name
                for name in active
                if name.startswith(("postgres-", "qdrant-", "redis-", "wavemind-serverless-keda-"))
            }
            return True if not blocked else None

        _wait_for(
            "source state services to stop",
            source_stopped,
            timeout_seconds=args.timeout_seconds,
        )

        restore_started = time.perf_counter()
        _apply_resources(args, args.recovery_namespace)
        for pod_name in ("postgres-0", "qdrant-0", "redis-0", "serverless-runner"):
            _wait_for(
                f"ready recovery pod {pod_name}",
                lambda pod_name=pod_name: (
                    pod
                    if _ready(
                        pod := _json(
                            args.kubectl,
                            "get",
                            "pod",
                            pod_name,
                            "-n",
                            args.recovery_namespace,
                        )
                    )
                    else None
                ),
                timeout_seconds=args.timeout_seconds,
                interval_seconds=2.0,
            )

        _run(
            args.kubectl,
            "cp",
            str(backup_path),
            f"{args.recovery_namespace}/postgres-0:/tmp/wavemind-dr.pgdump",
            timeout=180.0,
        )
        _run(
            args.kubectl,
            "exec",
            "postgres-0",
            "-n",
            args.recovery_namespace,
            "--",
            "pg_restore",
            "-U",
            "wavemind",
            "-d",
            "wavemind",
            "--exit-on-error",
            "/tmp/wavemind-dr.pgdump",
            timeout=180.0,
        )
        _run(
            args.kubectl,
            "scale",
            "deployment/wavemind-serverless-keda",
            "-n",
            args.recovery_namespace,
            "--replicas=1",
        )
        pods = _wait_for(
            "ready recovery API",
            lambda: (
                rows if len(rows := _ready_api_pods(args.kubectl, args.recovery_namespace)) == 1 else None
            ),
            timeout_seconds=args.timeout_seconds,
        )
        _wait_for(
            "recovery API HTTP readiness",
            lambda: _workload(
                kubectl=args.kubectl,
                namespace=args.recovery_namespace,
                config={
                    "api_key": API_KEY,
                    "namespace": args.memory_namespace,
                    "mode": "probe",
                    "bases": [recovery_service],
                },
                timeout=20.0,
            ),
            timeout_seconds=args.timeout_seconds,
        )
        restored = _workload(
            kubectl=args.kubectl,
            namespace=args.recovery_namespace,
            config={
                "api_key": API_KEY,
                "namespace": args.memory_namespace,
                "mode": "verify",
                "bases": [recovery_service],
                "count": args.memories,
            },
            timeout=300.0,
        )
        restored["rate"] = int(restored.get("successes") or 0) / max(
            1, int(restored.get("count") or 0)
        )
        probe = _workload(
            kubectl=args.kubectl,
            namespace=args.recovery_namespace,
            config={
                "api_key": API_KEY,
                "namespace": args.memory_namespace,
                "mode": "probe",
                "bases": [recovery_service],
            },
        )
        recovery_stats = dict(probe.get("stats") or {})
        uid_before = str((pods[0].get("metadata") or {}).get("uid") or "")
        pod_name = str((pods[0].get("metadata") or {}).get("name") or "")
        _run(
            args.kubectl,
            "delete",
            "pod",
            pod_name,
            "-n",
            args.recovery_namespace,
            "--wait=true",
            timeout=180.0,
        )
        replacement = _wait_for(
            "replacement recovery API",
            lambda: (
                rows[0]
                if len(rows := _ready_api_pods(args.kubectl, args.recovery_namespace)) == 1
                and str((rows[0].get("metadata") or {}).get("uid") or "") != uid_before
                else None
            ),
            timeout_seconds=args.timeout_seconds,
        )
        replaced = _workload(
            kubectl=args.kubectl,
            namespace=args.recovery_namespace,
            config={
                "api_key": API_KEY,
                "namespace": args.memory_namespace,
                "mode": "verify",
                "bases": [recovery_service],
                "count": args.memories,
            },
            timeout=300.0,
        )
        replaced["rate"] = int(replaced.get("successes") or 0) / max(
            1, int(replaced.get("count") or 0)
        )
        restore_elapsed_ms = round((time.perf_counter() - restore_started) * 1000.0, 3)
        recovery_pvcs = len(
            (_json(args.kubectl, "get", "pvc", "-n", args.recovery_namespace).get("items") or [])
        )
        return evaluate_kubernetes_postgres_qdrant_dr_smoke(
            {
                "source_namespace": args.source_namespace,
                "recovery_namespace": args.recovery_namespace,
                "source_service": source_service,
                "recovery_service": recovery_service,
                "backup_format": "pg_dump-custom",
                "backup_bytes": backup_bytes,
                "backup_sha256": backup_sha256,
                "source_state_stopped": True,
                "recovery_services": ["postgres", "qdrant", "redis"],
                "recovery_pvcs": recovery_pvcs,
                "postgres_restore_completed": True,
                "memory_count": args.memories,
                "restored": restored,
                "recovery_stats": recovery_stats,
                "recovery_api_uid_before": uid_before,
                "recovery_api_uid_after": str(
                    (replacement.get("metadata") or {}).get("uid") or ""
                ),
                "restored_after_api_replacement": replaced,
                "restore_elapsed_ms": restore_elapsed_ms,
                "restore_budget_ms": args.restore_budget_ms,
                "elapsed_ms": round((time.perf_counter() - started) * 1000.0, 3),
            }
        )
    finally:
        backup_path.unlink(missing_ok=True)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run independent-namespace Kubernetes PostgreSQL/Qdrant DR smoke"
    )
    parser.add_argument("--kubectl", default="kubectl")
    parser.add_argument("--source-namespace", default="wavemind-serverless")
    parser.add_argument("--recovery-namespace", default="wavemind-serverless-dr")
    parser.add_argument("--image", default="wavemind:ci-upgrade")
    parser.add_argument("--postgres-image", default="postgres:16-alpine")
    parser.add_argument("--qdrant-image", default="qdrant/qdrant:v1.18.2")
    parser.add_argument("--redis-image", default="redis:7-alpine")
    parser.add_argument("--memory-namespace", default="kind-serverless-lifecycle")
    parser.add_argument("--memories", type=int, default=24)
    parser.add_argument("--restore-budget-ms", type=float, default=180000.0)
    parser.add_argument("--timeout-seconds", type=float, default=300.0)
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("benchmarks/kubernetes_postgres_qdrant_dr_smoke_results.json"),
    )
    return parser


def main() -> int:
    args = build_parser().parse_args()
    if args.source_namespace == args.recovery_namespace:
        raise SystemExit("source and recovery namespaces must differ")
    payload = run_smoke(args)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0 if payload["status"] == "pass" else 4


if __name__ == "__main__":
    raise SystemExit(main())
