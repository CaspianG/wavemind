from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from pathlib import Path

from . import __version__
from .benchmark import BenchmarkCase, run_benchmark, synthetic_cases
from .cluster import ClusterNode, build_cluster_autoscale_plan, build_cluster_plan
from .consensus import run_control_plane_consensus_profile
from .core import WaveMind
from .encoders import create_text_encoder
from .advisor import advise_memory_architecture, advice_status_meets_or_exceeds
from .scale import (
    build_production_scale_run_plan,
    build_scale_plan,
    production_scale_profile_names,
    scale_status_meets_or_exceeds,
)
from .serverless import (
    SecretEnvRef,
    ServerlessObservedTelemetry,
    ServerlessWorkloadTarget,
    WaveMindServerlessSpec,
)
from .importers import import_path
from .jobs import (
    CachePrewarmWorker,
    DistributedRepairWorker,
    HotMemoryCache,
    MemoryMaintenanceWorker,
    MemoryOSScheduler,
    MemoryOSWorker,
    RedisMemoryOSLock,
    ReplicatedObjectStoreDrillWorker,
    ReplicatedSnapshotWorker,
    RedisHotMemoryCache,
)
from .k8s_operator import (
    KubernetesApplyClient,
    WaveMindClusterSpec,
    operator_bundle,
    operator_loop,
    operator_reconcile,
    operator_status,
)
from .object_store import S3SnapshotStore
from .postgres_recovery import build_postgres_pitr_plan
from .production_evidence import (
    build_scale_gap_manifest,
    build_release_claims_manifest,
    evaluate_production_evidence,
    evaluate_production_evidence_bundle,
    evaluate_production_evidence_preflight,
    render_bundle_markdown,
    render_markdown,
    render_preflight_markdown,
    render_release_claims_markdown,
    render_scale_gap_markdown,
)
from .replication import ReplicatedWaveMind
from .sharding import DistributedShardedWaveMind, HTTPNamespaceShardClient
from .storage import SQLiteMemoryStore


def configure_stdio() -> None:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            try:
                stream.reconfigure(encoding="utf-8", errors="replace")
            except (OSError, ValueError):
                pass


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="wavemind",
        description="WaveMind persistent dynamic memory engine",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            'Try: wavemind quickstart\n'
            'Then: wavemind remember "Andrey is a trader" --namespace demo\n'
            'And:  wavemind query "What does Andrey do?" --namespace demo'
        ),
    )
    parser.add_argument("--db", default=None, help="SQLite database path")
    parser.add_argument(
        "--recovery-journal",
        default=os.environ.get("WAVEMIND_RECOVERY_JOURNAL"),
        help="Append remember/forget/purge mutations to a SQLite recovery journal JSONL file.",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    parser.add_argument("--store", default=None, choices=["sqlite", "postgres"])
    parser.add_argument("--postgres-dsn", default=None)
    parser.add_argument(
        "--index",
        default="numpy",
        choices=[
            "numpy",
            "quantized",
            "faiss",
            "faiss-persisted",
            "annoy",
            "pgvector",
            "qdrant",
        ],
    )
    parser.add_argument("--encoder", default="hash", choices=["hash", "sentence"])
    parser.add_argument(
        "--model",
        default="sentence-transformers/paraphrase-multilingual-mpnet-base-v2",
        help="sentence-transformers model name when --encoder sentence is used",
    )
    parser.add_argument("--score-threshold", type=float, default=0.0)
    parser.add_argument("--width", type=int, default=128)
    parser.add_argument("--height", type=int, default=128)
    parser.add_argument("--layers", type=int, default=6)
    parser.add_argument("--graph-weight", type=float, default=0.0)
    parser.add_argument("--graph-steps", type=int, default=2)
    parser.add_argument("--graph-expand-k", type=int, default=10)
    parser.add_argument(
        "--audit-queries",
        action="store_true",
        default=os.environ.get("WAVEMIND_AUDIT_QUERIES", "0").lower()
        in {"1", "true", "yes", "on"},
        help="Store query text in the audit log for cache prewarm and diagnostics.",
    )

    sub = parser.add_subparsers(dest="command")

    sub.add_parser("quickstart", help="Show the shortest CLI path")

    remember = sub.add_parser("remember", help="Store a memory")
    remember.add_argument("text")
    remember.add_argument("--namespace", default="default")
    remember.add_argument("--tag", action="append", default=[])
    remember.add_argument("--ttl-seconds", type=float)
    remember.add_argument("--priority", type=float, default=1.0)

    query = sub.add_parser("query", help="Query memories")
    query.add_argument("text")
    query.add_argument("--namespace", default="default")
    query.add_argument("--tag", action="append", default=[])
    query.add_argument("--top-k", type=int, default=3)
    query.add_argument("--min-score", type=float)
    query.add_argument("--json", action="store_true")

    forget = sub.add_parser("forget", help="Delete a memory")
    forget.add_argument("--id", type=int)
    forget.add_argument("--text")
    forget.add_argument("--namespace")

    feedback = sub.add_parser("feedback", help="Record useful/not-useful recall feedback")
    feedback.add_argument("--id", type=int, required=True)
    feedback.add_argument("--namespace")
    feedback.add_argument("--strength", type=float, default=0.25)
    feedback.add_argument("--query")
    feedback.add_argument("--reason")
    feedback.add_argument("--not-useful", action="store_true")
    feedback.add_argument("--json", action="store_true")

    feedback_batch = sub.add_parser("feedback-batch", help="Record recall feedback from a JSON batch")
    feedback_batch.add_argument(
        "--file",
        required=True,
        help="JSON file, or '-', containing a list of feedback items or an object with an items list.",
    )
    feedback_batch.add_argument("--namespace")
    feedback_batch.add_argument(
        "--fail-on-rejected",
        action="store_true",
        help="Exit non-zero when any batch item is rejected.",
    )
    feedback_batch.add_argument("--json", action="store_true")

    stats = sub.add_parser("stats", help="Show memory stats")
    stats.add_argument("--namespace")

    index_health = sub.add_parser("index-health", help="Check vector index consistency")
    index_health.add_argument("--json", action="store_true")

    rebuild_index = sub.add_parser("rebuild-index", help="Rebuild vector index from stored memories")
    rebuild_index.add_argument("--json", action="store_true")

    consolidate = sub.add_parser("consolidate", help="Create concept memories from active field clusters")
    consolidate.add_argument("--namespace")
    consolidate.add_argument("--seed")
    consolidate.add_argument("--min-energy", type=float, default=0.05)
    consolidate.add_argument("--min-size", type=int, default=2)
    consolidate.add_argument("--max-concepts", type=int, default=3)
    consolidate.add_argument("--priority", type=float, default=6.0)
    consolidate.add_argument("--json", action="store_true")

    scale_plan = sub.add_parser("scale-plan", help="Show scale readiness and index recommendations")
    scale_plan.add_argument("--namespace")
    scale_plan.add_argument("--current-memories", type=int)
    scale_plan.add_argument("--target-memories", type=int)
    scale_plan.add_argument("--latency-target-ms", type=float, default=20.0)
    scale_plan.add_argument(
        "--fail-on",
        choices=["watch", "action_required", "architecture_required"],
        help="Exit non-zero when scale status reaches this threshold",
    )
    scale_plan.add_argument("--json", action="store_true")

    production_scale_plan = sub.add_parser(
        "production-scale-plan",
        help="Plan large 10M/50M/100M production benchmark runs",
    )
    production_scale_plan.add_argument(
        "--profile",
        action="append",
        choices=["all", *production_scale_profile_names()],
        default=[],
        help="Profile to include. Can be repeated. Defaults to all profiles.",
    )
    production_scale_plan.add_argument(
        "--disk-free-gb",
        type=float,
        help="Override local free disk for deterministic preflight artifacts.",
    )
    production_scale_plan.add_argument("--output-dir", default="benchmarks")
    production_scale_plan.add_argument("--state-dir", default="state")
    production_scale_plan.add_argument(
        "--write-artifact",
        action="store_true",
        help="Write the plan JSON to --output.",
    )
    production_scale_plan.add_argument(
        "--output",
        type=Path,
        default=Path("benchmarks/production_scale_run_plan.json"),
    )
    production_scale_plan.add_argument(
        "--fail-on-action-required",
        action="store_true",
        help="Exit non-zero unless every requested profile is ready to run.",
    )
    production_scale_plan.add_argument("--json", action="store_true")

    advise = sub.add_parser(
        "advise",
        help="Recommend production memory architecture from live stats and target scale",
    )
    advise.add_argument("--namespace")
    advise.add_argument("--current-memories", type=int)
    advise.add_argument("--target-memories", type=int)
    advise.add_argument("--target-p99-ms", type=float, default=100.0)
    advise.add_argument("--observed-p99-ms", type=float)
    advise.add_argument("--namespace-count", type=int)
    advise.add_argument("--node-count", type=int)
    advise.add_argument("--replication-factor", type=int, default=3)
    advise.add_argument("--read-quorum", type=int, default=1)
    advise.add_argument("--read-fanout", type=int)
    advise.add_argument("--target-qps", type=float, default=100.0)
    advise.add_argument(
        "--deployment",
        choices=["local", "staging", "production"],
        default="local",
    )
    advise.add_argument("--multimodal", action="store_true")
    advise.add_argument(
        "--fail-on",
        choices=["watch", "action_required", "architecture_required"],
        help="Exit non-zero when advice status reaches this threshold",
    )
    advise.add_argument("--json", action="store_true")

    production_evidence = sub.add_parser(
        "production-evidence",
        help="Check strict external production-evidence artifacts before scale claims",
    )
    production_evidence.add_argument(
        "--root",
        type=Path,
        default=Path.cwd(),
        help="Repository/artifact root. Defaults to the current working directory.",
    )
    production_evidence.add_argument(
        "--strict",
        action="store_true",
        help="Exit non-zero unless every external production-evidence requirement passes.",
    )
    production_evidence.add_argument(
        "--write-artifacts",
        action="store_true",
        help="Write JSON and Markdown reports to the output paths.",
    )
    production_evidence.add_argument(
        "--output",
        type=Path,
        default=Path("benchmarks/production_evidence_results.json"),
    )
    production_evidence.add_argument(
        "--markdown-output",
        type=Path,
        default=Path("benchmarks/PRODUCTION_EVIDENCE.md"),
    )
    production_evidence.add_argument("--json", action="store_true")

    production_evidence_preflight = sub.add_parser(
        "production-evidence-preflight",
        help="Check env and plan prerequisites for strict production-evidence runs",
    )
    production_evidence_preflight.add_argument(
        "--root",
        type=Path,
        default=Path.cwd(),
        help="Repository/artifact root. Defaults to the current working directory.",
    )
    production_evidence_preflight.add_argument(
        "--write-artifacts",
        action="store_true",
        help="Write JSON and Markdown preflight reports to the output paths.",
    )
    production_evidence_preflight.add_argument(
        "--fail-on-action-required",
        action="store_true",
        help="Exit non-zero unless every production-evidence prerequisite is ready.",
    )
    production_evidence_preflight.add_argument(
        "--output",
        type=Path,
        default=Path("benchmarks/production_evidence_preflight_results.json"),
    )
    production_evidence_preflight.add_argument(
        "--markdown-output",
        type=Path,
        default=Path("benchmarks/PRODUCTION_EVIDENCE_PREFLIGHT.md"),
    )
    production_evidence_preflight.add_argument("--json", action="store_true")

    production_evidence_bundle = sub.add_parser(
        "production-evidence-bundle",
        help="Build a combined strict evidence, preflight, readiness, and claim-status bundle",
    )
    production_evidence_bundle.add_argument(
        "--root",
        type=Path,
        default=Path.cwd(),
        help="Repository/artifact root. Defaults to the current working directory.",
    )
    production_evidence_bundle.add_argument(
        "--write-artifacts",
        action="store_true",
        help="Write JSON and Markdown bundle reports to the output paths.",
    )
    production_evidence_bundle.add_argument(
        "--strict",
        action="store_true",
        help="Exit non-zero unless strict production claims are unlocked.",
    )
    production_evidence_bundle.add_argument(
        "--output",
        type=Path,
        default=Path("benchmarks/production_evidence_bundle_results.json"),
    )
    production_evidence_bundle.add_argument(
        "--markdown-output",
        type=Path,
        default=Path("benchmarks/PRODUCTION_EVIDENCE_BUNDLE.md"),
    )
    production_evidence_bundle.add_argument("--json", action="store_true")

    release_claims = sub.add_parser(
        "release-claims",
        help="Build a compact release-safe public claims manifest",
    )
    release_claims.add_argument(
        "--root",
        type=Path,
        default=Path.cwd(),
        help="Repository/artifact root. Defaults to the current working directory.",
    )
    release_claims.add_argument(
        "--write-artifacts",
        action="store_true",
        help="Write JSON and Markdown release-claims reports to the output paths.",
    )
    release_claims.add_argument(
        "--strict",
        action="store_true",
        help="Exit non-zero unless strict production claims are unlocked.",
    )
    release_claims.add_argument(
        "--fail-on-blocked",
        action="store_true",
        help="Exit non-zero only when the release claim contract is blocked.",
    )
    release_claims.add_argument(
        "--output",
        type=Path,
        default=Path("benchmarks/release_claims_results.json"),
    )
    release_claims.add_argument(
        "--markdown-output",
        type=Path,
        default=Path("benchmarks/RELEASE_CLAIMS.md"),
    )
    release_claims.add_argument("--json", action="store_true")

    scale_gap = sub.add_parser(
        "scale-gap",
        help="Build the large-N benchmark gap matrix for 10M/50M/100M claims",
    )
    scale_gap.add_argument(
        "--root",
        type=Path,
        default=Path.cwd(),
        help="Repository/artifact root. Defaults to the current working directory.",
    )
    scale_gap.add_argument(
        "--write-artifacts",
        action="store_true",
        help="Write JSON and Markdown scale-gap reports to the output paths.",
    )
    scale_gap.add_argument(
        "--fail-on-action-required",
        action="store_true",
        help="Exit non-zero unless every large-N profile has strict passing evidence.",
    )
    scale_gap.add_argument(
        "--output",
        type=Path,
        default=Path("benchmarks/scale_gap_results.json"),
    )
    scale_gap.add_argument(
        "--markdown-output",
        type=Path,
        default=Path("benchmarks/SCALE_GAP.md"),
    )
    scale_gap.add_argument("--json", action="store_true")

    cluster_plan = sub.add_parser("cluster-plan", help="Plan namespace placement across cluster nodes")
    cluster_plan.add_argument("--namespace", action="append", default=[])
    cluster_plan.add_argument("--namespace-prefix", default="tenant")
    cluster_plan.add_argument("--namespace-count", type=int, default=0)
    cluster_plan.add_argument("--node", action="append", required=True, help="node_id=host:port or node_id")
    cluster_plan.add_argument("--replication-factor", type=int, default=2)
    cluster_plan.add_argument("--kubernetes", action="store_true")
    cluster_plan.add_argument("--image", default="wavemind:latest")
    cluster_plan.add_argument("--storage-size", default="20Gi")
    cluster_plan.add_argument("--repair-cronjob", action="store_true")
    cluster_plan.add_argument("--repair-schedule", default="*/15 * * * *")
    cluster_plan.add_argument("--repair-name", default="wavemind-cluster-repair")
    cluster_plan.add_argument("--repair-api-key-secret")
    cluster_plan.add_argument("--repair-api-key-secret-key", default="api-key")
    cluster_plan.add_argument("--repair-limit", type=int, default=1000)
    cluster_plan.add_argument("--repair-include-expired", action="store_true")
    cluster_plan.add_argument("--repair-tag", action="append", default=[])
    cluster_plan.add_argument("--json", action="store_true")

    cluster_autoscale = sub.add_parser(
        "cluster-autoscale-plan",
        help="Plan node additions and namespace movement for target cluster scale",
    )
    cluster_autoscale.add_argument("--namespace", action="append", default=[])
    cluster_autoscale.add_argument("--namespace-prefix", default="tenant")
    cluster_autoscale.add_argument("--namespace-count", type=int, default=0)
    cluster_autoscale.add_argument("--node", action="append", required=True, help="node_id=host:port or node_id")
    cluster_autoscale.add_argument("--replication-factor", type=int, default=3)
    cluster_autoscale.add_argument("--target-memories", type=int, required=True)
    cluster_autoscale.add_argument("--max-memories-per-node", type=int, default=1_000_000)
    cluster_autoscale.add_argument("--headroom", type=float, default=0.70)
    cluster_autoscale.add_argument("--node-prefix", default="node")
    cluster_autoscale.add_argument("--address-template", default="http://{node_id}:8000")
    cluster_autoscale.add_argument("--zone", action="append", default=[])
    cluster_autoscale.add_argument("--max-moves", type=int, default=100)
    cluster_autoscale.add_argument("--rebalance-plan", action="store_true")
    cluster_autoscale.add_argument("--rebalance-batch-size", type=int, default=25)
    cluster_autoscale.add_argument("--rebalance-max-node-moves-per-batch", type=int)
    cluster_autoscale.add_argument("--drain-node", action="append", default=[])
    cluster_autoscale.add_argument("--json", action="store_true")

    control_plane_consensus = sub.add_parser(
        "control-plane-consensus",
        help="Run the deterministic control-plane majority/lease safety profile",
    )
    control_plane_consensus.add_argument("--json", action="store_true")

    cluster_repair = sub.add_parser(
        "cluster-repair",
        help="Run service-mode anti-entropy repair across cluster namespaces",
    )
    cluster_repair.add_argument("--namespace", action="append", default=[])
    cluster_repair.add_argument("--namespace-prefix", default="tenant")
    cluster_repair.add_argument("--namespace-count", type=int, default=0)
    cluster_repair.add_argument("--node", action="append", required=True, help="node_id=host:port or node_id")
    cluster_repair.add_argument("--replication-factor", type=int, default=2)
    cluster_repair.add_argument("--write-quorum", type=int)
    cluster_repair.add_argument("--read-quorum", type=int, default=1)
    cluster_repair.add_argument("--read-fanout", type=int)
    cluster_repair.add_argument(
        "--api-key",
        default=os.environ.get("WAVEMIND_API_KEY"),
        help="Bearer token for WaveMind API nodes. Defaults to WAVEMIND_API_KEY.",
    )
    cluster_repair.add_argument("--timeout", type=float, default=10.0)
    cluster_repair.add_argument("--limit", type=int, default=1000)
    cluster_repair.add_argument("--include-expired", action="store_true")
    cluster_repair.add_argument("--tag", action="append", default=[])
    cluster_repair.add_argument("--fail-fast", action="store_true")
    cluster_repair.add_argument("--json", action="store_true")

    cluster_health = sub.add_parser(
        "cluster-health",
        help="Probe service-mode cluster nodes and show health/circuit state",
    )
    cluster_health.add_argument("--node", action="append", required=True, help="node_id=host:port or node_id")
    cluster_health.add_argument("--replication-factor", type=int, default=2)
    cluster_health.add_argument("--write-quorum", type=int)
    cluster_health.add_argument("--read-quorum", type=int, default=1)
    cluster_health.add_argument("--read-fanout", type=int)
    cluster_health.add_argument(
        "--api-key",
        default=os.environ.get("WAVEMIND_API_KEY"),
        help="Bearer token for WaveMind API nodes. Defaults to WAVEMIND_API_KEY.",
    )
    cluster_health.add_argument("--timeout", type=float, default=10.0)
    cluster_health.add_argument(
        "--fail-on-degraded",
        action="store_true",
        help="Exit non-zero when any node is degraded or unavailable.",
    )
    cluster_health.add_argument("--json", action="store_true")

    operator_sample = sub.add_parser(
        "operator-sample",
        help="Emit a WaveMindCluster custom resource as Kubernetes JSON",
    )
    _add_operator_spec_args(operator_sample)
    operator_sample.add_argument("--json", action="store_true")
    operator_sample.add_argument("--out", help="Write UTF-8 JSON to this file instead of stdout")

    operator_bundle_cmd = sub.add_parser(
        "operator-bundle",
        help="Emit CRD, RBAC, operator deployment, and sample WaveMindCluster",
    )
    operator_bundle_cmd.add_argument("--namespace", default="default")
    operator_bundle_cmd.add_argument("--operator-image", default="ghcr.io/caspiang/wavemind:latest")
    operator_bundle_cmd.add_argument("--sample-name", default="wavemind")
    operator_bundle_cmd.add_argument("--sample-image", default="ghcr.io/caspiang/wavemind:latest")
    operator_bundle_cmd.add_argument("--sample-replicas", type=int, default=3)
    operator_bundle_cmd.add_argument("--sample-replication-factor", type=int, default=2)
    operator_bundle_cmd.add_argument("--sample-namespace-count", type=int, default=128)
    operator_bundle_cmd.add_argument("--json", action="store_true")
    operator_bundle_cmd.add_argument("--out", help="Write UTF-8 JSON to this file instead of stdout")

    operator_reconcile_cmd = sub.add_parser(
        "operator-reconcile",
        help="Render Kubernetes resources from a WaveMindCluster JSON file",
    )
    operator_reconcile_cmd.add_argument("--file", required=True, help="WaveMindCluster JSON file or '-' for stdin")
    operator_reconcile_cmd.add_argument("--json", action="store_true")
    operator_reconcile_cmd.add_argument("--out", help="Write UTF-8 JSON to this file instead of stdout")

    operator_status_cmd = sub.add_parser(
        "operator-status",
        help="Render WaveMindCluster status conditions from a custom resource",
    )
    operator_status_cmd.add_argument("--file", required=True, help="WaveMindCluster JSON file or '-' for stdin")
    operator_status_cmd.add_argument("--ready-replicas", type=int)
    operator_status_cmd.add_argument("--current-replicas", type=int)
    operator_status_cmd.add_argument("--hpa-desired-replicas", type=int)
    operator_status_cmd.add_argument("--current-memories", type=int)
    operator_status_cmd.add_argument("--degraded-nodes", type=int)
    operator_status_cmd.add_argument("--unavailable-nodes", type=int)
    operator_status_cmd.add_argument("--json", action="store_true")
    operator_status_cmd.add_argument("--out", help="Write UTF-8 JSON to this file instead of stdout")

    operator_loop_cmd = sub.add_parser(
        "operator-loop",
        help="Run the in-cluster WaveMindCluster reconciliation loop",
    )
    operator_loop_cmd.add_argument("--namespace", default=os.environ.get("POD_NAMESPACE", "default"))
    operator_loop_cmd.add_argument("--interval-seconds", type=float, default=30.0)
    operator_loop_cmd.add_argument("--timeout", type=float, default=10.0)
    operator_loop_cmd.add_argument("--once", action="store_true")
    operator_loop_cmd.add_argument("--json", action="store_true")

    serverless_sample = sub.add_parser(
        "serverless-sample",
        help="Emit Knative/KEDA serverless API resources for external Postgres/Qdrant/Redis",
    )
    _add_serverless_spec_args(serverless_sample)
    serverless_sample.add_argument("--no-keda", action="store_true")
    serverless_mode = serverless_sample.add_mutually_exclusive_group()
    serverless_mode.add_argument("--readiness", action="store_true")
    serverless_mode.add_argument("--operational-profile", action="store_true")
    serverless_sample.add_argument("--target-rps", type=float, default=3200.0)
    serverless_sample.add_argument("--avg-request-ms", type=float, default=80.0)
    serverless_sample.add_argument("--p99-request-ms", type=float, default=320.0)
    serverless_sample.add_argument("--cold-start-ms", type=float, default=900.0)
    serverless_sample.add_argument("--target-p99-ms", type=float, default=500.0)
    serverless_sample.add_argument("--cold-start-budget-ms", type=float, default=1500.0)
    serverless_sample.add_argument("--active-fraction", type=float, default=0.35)
    serverless_sample.add_argument("--replica-hourly-cost-usd", type=float, default=0.08)
    serverless_sample.add_argument("--monthly-budget-usd", type=float, default=750.0)
    serverless_sample.add_argument("--max-error-rate", type=float, default=0.01)
    serverless_sample.add_argument("--max-scale-out-seconds", type=float, default=60.0)
    serverless_sample.add_argument(
        "--observed-telemetry",
        help="JSON file, or '-', with observed Knative/KEDA load-test telemetry.",
    )
    serverless_sample.add_argument("--json", action="store_true")
    serverless_sample.add_argument("--out", help="Write UTF-8 JSON to this file instead of stdout")

    audit = sub.add_parser("audit", help="Show audit log events")
    audit.add_argument("--namespace")
    audit.add_argument("--action")
    audit.add_argument("--limit", type=int, default=20)
    audit.add_argument("--json", action="store_true")

    maintenance = sub.add_parser("maintenance", help="Run one deterministic maintenance job")
    maintenance.add_argument("--namespace")
    maintenance.add_argument("--consolidate-steps", type=int, default=0)
    maintenance.add_argument("--consolidate-concepts", action="store_true")
    maintenance.add_argument("--no-rebuild-index", action="store_true")
    maintenance.add_argument("--json", action="store_true")

    cache_prewarm = sub.add_parser(
        "cache-prewarm",
        help="Prewarm hot query cache from audited query events",
    )
    cache_prewarm.add_argument("--namespace")
    cache_prewarm.add_argument("--audit-limit", type=int, default=256)
    cache_prewarm.add_argument("--max-queries", type=int, default=32)
    cache_prewarm.add_argument("--min-frequency", type=int, default=1)
    cache_prewarm.add_argument("--top-k", type=int, default=3)
    cache_prewarm.add_argument("--min-score", type=float)
    cache_prewarm.add_argument("--capacity", type=int, default=512)
    cache_prewarm.add_argument("--ttl-seconds", type=float, default=60.0)
    cache_prewarm.add_argument(
        "--redis-url",
        default=os.environ.get("WAVEMIND_REDIS_URL"),
        help="Redis URL for a shared production cache. Defaults to WAVEMIND_REDIS_URL.",
    )
    cache_prewarm.add_argument(
        "--redis-prefix",
        default=os.environ.get("WAVEMIND_REDIS_PREFIX", "wavemind:hot"),
    )
    cache_prewarm.add_argument("--json", action="store_true")

    memory_os = sub.add_parser(
        "memory-os",
        help="Run one adaptive Memory OS maintenance and prefetch cycle",
    )
    memory_os.add_argument("--namespace")
    memory_os.add_argument("--audit-limit", type=int, default=512)
    memory_os.add_argument("--max-hot-queries", type=int, default=32)
    memory_os.add_argument("--min-frequency", type=int, default=2)
    memory_os.add_argument("--top-k", type=int, default=3)
    memory_os.add_argument("--min-score", type=float)
    memory_os.add_argument("--consolidate-steps", type=int, default=10)
    memory_os.add_argument("--no-consolidate-concepts", action="store_true")
    memory_os.add_argument("--concept-seed-text")
    memory_os.add_argument("--min-concept-energy", type=float, default=0.02)
    memory_os.add_argument("--min-concept-size", type=int, default=2)
    memory_os.add_argument("--max-concepts", type=int, default=3)
    memory_os.add_argument("--concept-priority", type=float, default=6.0)
    memory_os.add_argument("--no-predict-priorities", action="store_true")
    memory_os.add_argument("--max-priority-predictions", type=int, default=16)
    memory_os.add_argument("--priority-boost-per-hit", type=float, default=0.05)
    memory_os.add_argument("--max-priority-boost", type=float, default=0.5)
    memory_os.add_argument("--no-adaptive-forgetting", action="store_true")
    memory_os.add_argument("--forgetting-min-age-seconds", type=float, default=7 * 24 * 60 * 60)
    memory_os.add_argument("--forgetting-max-memories", type=int, default=32)
    memory_os.add_argument("--forgetting-max-access-count", type=int, default=0)
    memory_os.add_argument("--forgetting-priority-decay", type=float, default=0.10)
    memory_os.add_argument("--forgetting-min-priority", type=float, default=0.0)
    memory_os.add_argument("--no-predictive-prefetch", action="store_true")
    memory_os.add_argument("--max-predictive-queries", type=int, default=16)
    memory_os.add_argument("--predictive-terms-per-hot-query", type=int, default=3)
    memory_os.add_argument("--transition-prefetch-window-seconds", type=float, default=15 * 60)
    memory_os.add_argument("--no-rebuild-index", action="store_true")
    memory_os.add_argument("--memory-pressure-threshold", type=int, default=50_000)
    memory_os.add_argument("--no-architecture-advice", action="store_true")
    memory_os.add_argument("--target-memories", type=int)
    memory_os.add_argument("--target-p99-ms", type=float, default=100.0)
    memory_os.add_argument("--observed-p99-ms", type=float)
    memory_os.add_argument("--namespace-count", type=int)
    memory_os.add_argument("--node-count", type=int)
    memory_os.add_argument("--replication-factor", type=int, default=3)
    memory_os.add_argument("--read-quorum", type=int, default=1)
    memory_os.add_argument("--read-fanout", type=int)
    memory_os.add_argument("--target-qps", type=float, default=100.0)
    memory_os.add_argument(
        "--deployment",
        choices=["local", "staging", "production", "prod"],
        default="local",
    )
    memory_os.add_argument("--multimodal", action="store_true")
    memory_os.add_argument("--capacity", type=int, default=512)
    memory_os.add_argument("--ttl-seconds", type=float, default=60.0)
    memory_os.add_argument(
        "--redis-url",
        default=os.environ.get("WAVEMIND_REDIS_URL"),
        help="Redis URL for a shared production cache. Defaults to WAVEMIND_REDIS_URL.",
    )
    memory_os.add_argument(
        "--redis-prefix",
        default=os.environ.get("WAVEMIND_REDIS_PREFIX", "wavemind:hot"),
    )
    memory_os.add_argument(
        "--lock-required",
        action="store_true",
        default=os.environ.get("WAVEMIND_MEMORY_OS_LOCK_REQUIRED", "0").lower()
        in {"1", "true", "yes", "on"},
        help="Require a Redis single-flight lock before mutating Memory OS state.",
    )
    memory_os.add_argument(
        "--lock-prefix",
        default=os.environ.get("WAVEMIND_MEMORY_OS_LOCK_PREFIX", "wavemind:memory-os:lock"),
    )
    memory_os.add_argument("--lock-ttl-seconds", type=int, default=300)
    memory_os.add_argument("--no-cache", action="store_true")
    memory_os.add_argument("--json", action="store_true")

    memory_os_plan = sub.add_parser(
        "memory-os-plan",
        help="Build a read-only production schedule for Memory OS workers",
    )
    memory_os_plan.add_argument("--namespace")
    memory_os_plan.add_argument("--audit-limit", type=int, default=512)
    memory_os_plan.add_argument("--max-hot-queries", type=int, default=32)
    memory_os_plan.add_argument("--min-frequency", type=int, default=2)
    memory_os_plan.add_argument("--top-k", type=int, default=3)
    memory_os_plan.add_argument("--min-score", type=float)
    memory_os_plan.add_argument("--target-memories", type=int)
    memory_os_plan.add_argument("--namespace-count", type=int)
    memory_os_plan.add_argument("--node-count", type=int)
    memory_os_plan.add_argument("--replication-factor", type=int, default=3)
    memory_os_plan.add_argument("--read-quorum", type=int, default=1)
    memory_os_plan.add_argument("--read-fanout", type=int)
    memory_os_plan.add_argument("--target-qps", type=float, default=100.0)
    memory_os_plan.add_argument("--target-p99-ms", type=float, default=100.0)
    memory_os_plan.add_argument("--observed-p99-ms", type=float)
    memory_os_plan.add_argument(
        "--deployment",
        choices=["local", "staging", "production", "prod"],
        default="local",
    )
    memory_os_plan.add_argument(
        "--cache-mode",
        choices=["auto", "disabled", "local", "redis"],
        default="auto",
    )
    memory_os_plan.add_argument("--multimodal", action="store_true")
    memory_os_plan.add_argument("--memory-pressure-threshold", type=int, default=50_000)
    memory_os_plan.add_argument("--strict", action="store_true")
    memory_os_plan.add_argument("--json", action="store_true")

    imp = sub.add_parser("import", help="Import txt/pdf/json")
    imp.add_argument("path")
    imp.add_argument("--namespace", default="default")
    imp.add_argument("--tag", action="append", default=[])
    imp.add_argument("--max-chars", type=int, default=1000)
    imp.add_argument("--overlap", type=int, default=120)

    backup = sub.add_parser("backup", help="Backup SQLite database")
    backup.add_argument("--out", required=True)
    backup.add_argument("--keep-last", type=int)
    backup.add_argument("--prefix", default="wavemind")

    restore = sub.add_parser("restore", help="Restore a SQLite backup")
    restore.add_argument("--from", dest="source", required=True)
    restore.add_argument("--to", dest="destination")
    restore.add_argument("--overwrite", action="store_true")

    recovery_restore = sub.add_parser(
        "recovery-restore",
        help="Restore a SQLite database from a WaveMind recovery journal",
    )
    recovery_restore.add_argument("--from", dest="source", required=True)
    recovery_restore.add_argument("--to", dest="destination")
    recovery_restore.add_argument("--until", type=float)
    recovery_restore.add_argument("--overwrite", action="store_true")
    recovery_restore.add_argument("--json", action="store_true")

    postgres_pitr = sub.add_parser(
        "postgres-pitr-plan",
        help="Emit a secret-safe Postgres point-in-time recovery runbook/preflight",
    )
    postgres_pitr.add_argument("--dsn-env", default="WAVEMIND_POSTGRES_DSN")
    postgres_pitr.add_argument("--basebackup-env", default="WAVEMIND_POSTGRES_BASEBACKUP_DIR")
    postgres_pitr.add_argument("--wal-archive-env", default="WAVEMIND_POSTGRES_WAL_ARCHIVE_DIR")
    postgres_pitr.add_argument("--restore-data-env", default="WAVEMIND_POSTGRES_RESTORE_DATA_DIR")
    postgres_pitr.add_argument("--restore-target-env", default="WAVEMIND_POSTGRES_RESTORE_TARGET_TIME")
    postgres_pitr.add_argument("--retention-hours", type=int, default=72)
    postgres_pitr.add_argument(
        "--fail-on-missing-env",
        action="store_true",
        help="Exit non-zero when any required runtime environment variable is missing.",
    )
    postgres_pitr.add_argument("--out", type=Path)
    postgres_pitr.add_argument("--json", action="store_true")

    replicated_snapshot = sub.add_parser(
        "replicated-snapshot",
        help="Snapshot a ReplicatedWaveMind root with optional offsite mirror/archive",
    )
    replicated_snapshot.add_argument("--root", required=True)
    replicated_snapshot.add_argument("--node", action="append", required=True)
    replicated_snapshot.add_argument("--replication-factor", type=int, default=3)
    replicated_snapshot.add_argument("--write-quorum", type=int)
    replicated_snapshot.add_argument("--read-quorum", type=int, default=1)
    replicated_snapshot.add_argument("--out", required=True)
    replicated_snapshot.add_argument("--offsite")
    replicated_snapshot.add_argument("--archive")
    replicated_snapshot.add_argument(
        "--s3",
        help="Upload archive to s3://bucket/prefix or s3://bucket/key.tar.gz",
    )
    replicated_snapshot.add_argument("--s3-endpoint-url")
    replicated_snapshot.add_argument("--s3-region")
    replicated_snapshot.add_argument(
        "--s3-keep-last",
        type=int,
        help="Prune older S3-compatible snapshot archives after upload",
    )
    replicated_snapshot.add_argument("--keep-last", type=int)
    replicated_snapshot.add_argument("--prefix", default="wavemind-replicated")
    replicated_snapshot.add_argument("--allow-partial", action="store_true")
    replicated_snapshot.add_argument("--json", action="store_true")

    replicated_restore = sub.add_parser(
        "replicated-restore",
        help="Restore a ReplicatedWaveMind snapshot into a replica root",
    )
    replicated_restore.add_argument("--from", dest="source", required=True)
    replicated_restore.add_argument("--to", dest="destination", required=True)
    replicated_restore.add_argument("--overwrite", action="store_true")
    replicated_restore.add_argument("--s3-endpoint-url")
    replicated_restore.add_argument("--s3-region")
    replicated_restore.add_argument(
        "--latest",
        action="store_true",
        help="Restore the newest archive under an s3://bucket/prefix source",
    )
    replicated_restore.add_argument("--json", action="store_true")

    replicated_s3_archives = sub.add_parser(
        "replicated-s3-archives",
        help="List or prune S3-compatible replicated snapshot archives",
    )
    replicated_s3_archives.add_argument("--s3", required=True)
    replicated_s3_archives.add_argument("--s3-endpoint-url")
    replicated_s3_archives.add_argument("--s3-region")
    replicated_s3_archives.add_argument("--latest", action="store_true")
    replicated_s3_archives.add_argument("--prune-keep-last", type=int)
    replicated_s3_archives.add_argument("--json", action="store_true")

    replicated_drill = sub.add_parser(
        "replicated-drill",
        help="Run an S3-compatible replicated snapshot disaster-recovery drill",
    )
    replicated_drill.add_argument("--from", dest="source", required=True)
    replicated_drill.add_argument("--to", dest="destination", required=True)
    replicated_drill.add_argument("--download-to")
    replicated_drill.add_argument("--overwrite", action="store_true")
    replicated_drill.add_argument("--s3-endpoint-url")
    replicated_drill.add_argument("--s3-region")
    replicated_drill.add_argument("--latest", action="store_true")
    replicated_drill.add_argument("--namespace")
    replicated_drill.add_argument("--query")
    replicated_drill.add_argument("--expect-text")
    replicated_drill.add_argument("--top-k", type=int, default=1)
    replicated_drill.add_argument("--keep-primary", action="store_true")
    replicated_drill.add_argument("--json", action="store_true")

    bench = sub.add_parser("benchmark", help="Run a synthetic recall benchmark")
    bench.add_argument("--namespace", default="bench")
    bench.add_argument("--top-k", type=int, default=1)

    serve = sub.add_parser("serve", help="Run FastAPI daemon")
    serve.add_argument("--host", default="0.0.0.0")
    serve.add_argument("--port", type=int, default=8000)
    serve.add_argument(
        "--replicated-root",
        dest="root",
        help="Run the API with a ReplicatedWaveMind root instead of a single SQLite store.",
    )
    serve.add_argument(
        "--replica-node",
        dest="node",
        action="append",
        default=[],
        help="Replica node as node_id=address or node_id. Repeat for every local replica.",
    )
    serve.add_argument("--replication-factor", type=int, default=3)
    serve.add_argument("--write-quorum", type=int)
    serve.add_argument("--read-quorum", type=int, default=1)

    studio = sub.add_parser("studio", help="Run local WaveMind Studio dashboard")
    studio.add_argument("--host", default="127.0.0.1")
    studio.add_argument("--port", type=int, default=8000)
    studio.add_argument("--no-open", action="store_true")

    sub.add_parser("test", help="Run pytest suite")
    return parser


def make_mind(args) -> WaveMind:
    encoder = create_text_encoder(kind=args.encoder, vector_dim=384, model_name=args.model)
    db_path = Path(args.db) if args.db else Path.cwd() / "wavemind.sqlite3"
    return WaveMind(
        db_path=db_path,
        store_kind=args.store,
        postgres_dsn=args.postgres_dsn,
        width=args.width,
        height=args.height,
        layers=args.layers,
        encoder=encoder,
        index_kind=args.index,
        score_threshold=args.score_threshold,
        audit_queries=args.audit_queries,
        graph_weight=args.graph_weight,
        graph_steps=args.graph_steps,
        graph_expand_k=args.graph_expand_k,
        recovery_journal_path=args.recovery_journal,
    )


def make_replicated_mind(args) -> ReplicatedWaveMind:
    encoder = create_text_encoder(kind=args.encoder, vector_dim=384, model_name=args.model)
    return ReplicatedWaveMind(
        root_path=args.root,
        nodes=[_parse_cluster_node(value) for value in args.node],
        replication_factor=args.replication_factor,
        write_quorum=args.write_quorum,
        read_quorum=args.read_quorum,
        width=args.width,
        height=args.height,
        layers=args.layers,
        encoder=encoder,
        index_kind=args.index,
        score_threshold=args.score_threshold,
        audit_queries=args.audit_queries,
        graph_weight=args.graph_weight,
        graph_steps=args.graph_steps,
        graph_expand_k=args.graph_expand_k,
    )


def make_served_mind(args) -> WaveMind | ReplicatedWaveMind:
    if getattr(args, "root", None) or getattr(args, "node", None):
        if not getattr(args, "root", None):
            raise SystemExit("--replicated-root is required when --replica-node is used")
        if not getattr(args, "node", None):
            raise SystemExit("--replica-node is required when --replicated-root is used")
        return make_replicated_mind(args)
    return make_mind(args)


def replicated_restore_kwargs(args) -> dict[str, object]:
    return {
        "width": args.width,
        "height": args.height,
        "layers": args.layers,
        "encoder": create_text_encoder(
            kind=args.encoder,
            vector_dim=384,
            model_name=args.model,
        ),
        "index_kind": args.index,
        "score_threshold": args.score_threshold,
        "graph_weight": args.graph_weight,
        "graph_steps": args.graph_steps,
        "graph_expand_k": args.graph_expand_k,
    }


def print_stats(stats: dict) -> None:
    for key, value in stats.items():
        print(f"{key}: {value}")


def print_scale_plan(plan: dict[str, object]) -> None:
    print(f"tier: {plan['tier']}")
    print(f"status: {plan['status']}")
    print(f"current_memories: {plan['current_memories']}")
    print(f"target_memories: {plan['target_memories']}")
    print(f"index: {plan['index']}")
    print(f"recommended_index: {plan['recommended_index']}")
    print(f"latency_target_ms: {plan['latency_target_ms']}")
    warnings = plan.get("warnings") or []
    actions = plan.get("actions") or []
    if warnings:
        print("warnings:")
        for item in warnings:
            print(f"- {item}")
    if actions:
        print("actions:")
        for item in actions:
            print(f"- {item}")


def print_production_scale_run_plan(payload: dict[str, object]) -> None:
    summary = payload["summary"]
    print(f"status: {summary['overall_status']}")
    print(f"ready: {summary['ready_count']}/{summary['total_profiles']}")
    print(f"target_memories_total: {summary['target_memories_total']}")
    print(f"claim_boundary: {summary['claim_boundary']}")
    for row in payload.get("profiles", []):
        print(f"- [{row['status']}] {row['profile']}")
        print(f"  engine: {row['engine']}")
        print(f"  target_memories: {row['target_memories']}")
        print(f"  output: {row['output_artifact']}")
        print(f"  required_local_free_gb: {row['required_local_free_gb']}")
        missing_env = row.get("missing_env") or []
        if missing_env:
            print(f"  missing_env: {', '.join(missing_env)}")
        blockers = row.get("blockers") or []
        if blockers:
            print(f"  blockers: {', '.join(blockers)}")
        print(f"  command: {row['command']}")


def print_architecture_advice(advice: dict[str, object]) -> None:
    print(f"status: {advice['status']}")
    print(f"production_ready: {str(advice['production_ready']).lower()}")
    print(f"deployment: {advice['deployment']}")
    print(f"current_memories: {advice['current_memories']}")
    print(f"target_memories: {advice['target_memories']}")
    print(f"index: {advice['index']}")
    print(f"replication_factor: {advice['replication_factor']}")
    print(f"read_quorum: {advice['read_quorum']}")
    print(f"read_fanout: {advice['read_fanout']}")
    print(f"target_p99_ms: {advice['target_p99_ms']}")
    observed = advice.get("observed_p99_ms")
    if observed is not None:
        print(f"observed_p99_ms: {observed}")
    recommendations = advice.get("recommendations") or []
    if recommendations:
        print("recommendations:")
        for recommendation in recommendations:
            print(f"- [{recommendation['severity']}] {recommendation['title']}")
            print(f"  action: {recommendation['action']}")
    next_commands = advice.get("next_commands") or []
    if next_commands:
        print("next_commands:")
        for command in next_commands:
            print(f"- {command}")


def print_production_evidence(payload: dict[str, object]) -> None:
    summary = payload["summary"]
    print(f"status: {summary['overall_status']}")
    print(f"passed: {summary['pass_count']}/{summary['total_requirements']}")
    print(f"action_required: {summary['action_required_count']}")
    print(f"failed: {summary['fail_count']}")
    print("requirements:")
    for row in payload.get("requirements", []):
        print(f"- [{row['status']}] {row['title']}")
        print(f"  artifact: {row['artifact']}")
        print(f"  evidence: {row['evidence']}")
        issues = row.get("issues") or []
        if issues:
            print(f"  issues: {', '.join(issues)}")
        command = row.get("command")
        if command:
            print(f"  command: {command}")


def print_production_evidence_preflight(payload: dict[str, object]) -> None:
    summary = payload["summary"]
    print(f"status: {summary['overall_status']}")
    print(f"ready: {summary['ready_count']}/{summary['total_checks']}")
    print(f"action_required: {summary['action_required_count']}")
    print("checks:")
    for row in payload.get("checks", []):
        print(f"- [{row['status']}] {row['title']}")
        print(f"  output: {row['output_artifact']}")
        print(f"  evidence: {row['evidence']}")
        missing_env = row.get("missing_env") or []
        if missing_env:
            print(f"  missing_env: {', '.join(missing_env)}")
        issues = row.get("issues") or []
        if issues:
            print(f"  issues: {', '.join(issues)}")
        warnings = row.get("warnings") or []
        if warnings:
            print(f"  warnings: {', '.join(warnings)}")
        command = row.get("command")
        if command:
            print(f"  command: {command}")


def print_production_evidence_bundle(payload: dict[str, object]) -> None:
    summary = payload["summary"]
    print(f"claim_status: {summary['claim_status']}")
    print(
        "strict: "
        f"{summary['strict_pass_count']}/{summary['strict_total_requirements']} "
        f"({summary['strict_overall_status']})"
    )
    print(
        "preflight: "
        f"{summary['preflight_ready_count']}/{summary['preflight_total_checks']} "
        f"({summary['preflight_overall_status']})"
    )
    print(f"readiness: {summary['production_readiness_status']}")
    print(f"artifact_audit: {summary['artifact_audit_status']}")
    print(f"next_actions: {summary['next_action_count']}")
    print("claim_boundaries:")
    for row in payload.get("claim_boundaries", []):
        print(f"- [{row['status']}] {row['claim']}")
        print(f"  evidence: {row['evidence']}")
    next_actions = payload.get("next_actions", [])
    if next_actions:
        print("next_actions_detail:")
    for row in next_actions:
        print(f"- [{row['strict_status']}/{row['preflight_status']}] {row['title']}")
        print(f"  artifact: {row['artifact']}")
        missing_env = row.get("missing_env") or []
        if missing_env:
            print(f"  missing_env: {', '.join(missing_env)}")
        issues = row.get("issues") or []
        if issues:
            print(f"  issues: {', '.join(issues)}")
        command = row.get("command")
        if command:
            print(f"  command: {command}")


def print_release_claims(payload: dict[str, object]) -> None:
    summary = payload["summary"]
    print(f"release_status: {summary['release_status']}")
    print(f"claim_status: {summary['claim_status']}")
    print(f"readiness: {summary['production_readiness_status']}")
    print(f"artifact_audit: {summary['artifact_audit_status']}")
    print(f"allowed_claims: {summary['allowed_claim_count']}")
    print(f"locked_claims: {summary['locked_claim_count']}")
    print("allowed:")
    for row in payload.get("allowed_claims", []):
        print(f"- [{row['status']}] {row['claim']}")
    locked = payload.get("locked_claims", [])
    if locked:
        print("locked:")
    for row in locked:
        print(f"- [{row['status']}] {row['claim']}")
        print(f"  evidence: {row['evidence']}")
    next_actions = payload.get("next_actions", [])
    if next_actions:
        print("next_actions:")
    for row in next_actions:
        print(f"- [{row['strict_status']}/{row['preflight_status']}] {row['title']}")
        print(f"  artifact: {row['artifact']}")
        missing_env = row.get("missing_env") or []
        if missing_env:
            print(f"  missing_env: {', '.join(missing_env)}")
        command = row.get("command")
        if command:
            print(f"  command: {command}")


def print_cluster_autoscale_plan(plan: dict[str, object]) -> None:
    print(f"status: {plan['status']}")
    print(f"current_nodes: {len(plan['current_nodes'])}")
    print(f"required_nodes: {plan['required_nodes']}")
    print(f"additional_nodes: {plan['additional_nodes']}")
    print(f"target_memories: {plan['target_memories']}")
    print(f"max_memories_per_node: {plan['max_memories_per_node']}")
    print(f"current_max_node_memories: {plan['current_max_node_memories']}")
    print(f"target_max_node_memories: {plan['target_max_node_memories']}")
    print(f"moves: {len(plan['moves'])}")
    if plan.get("omitted_moves"):
        print(f"omitted_moves: {plan['omitted_moves']}")
    if plan.get("warnings"):
        print("warnings:")
        for warning in plan["warnings"]:
            print(f"- {warning}")
    if plan.get("actions"):
        print("actions:")
        for action in plan["actions"]:
            print(f"- {action}")
    if plan.get("rebalance_plan"):
        rebalance = plan["rebalance_plan"]
        print("rebalance_plan:")
        print(f"- status: {rebalance['status']}")
        print(f"- batches: {rebalance['batch_count']}")
        print(f"- write_quorum: {rebalance['write_quorum']}")
        print(f"- full_plan: {rebalance['full_plan']}")
        print(f"- max_batch_node_pressure: {rebalance['max_batch_node_pressure']}")


def print_quickstart() -> None:
    print(
        """WaveMind quickstart

Install:
  python -m pip install wavemind

Store one memory:
  wavemind remember "Andrey is a trader" --namespace demo

Query it:
  wavemind query "What does Andrey do?" --namespace demo

Check state:
  wavemind stats --namespace demo

Where data goes:
  ./wavemind.sqlite3 in the current directory by default

Useful next commands:
  wavemind --help
  wavemind studio
  wavemind import ./notes.txt --namespace demo
  wavemind serve --host 127.0.0.1 --port 8000
  wavemind forget --namespace demo
"""
    )


def run_interactive(args) -> int:
    mind = make_mind(args)
    print("WaveMind v2 interactive CLI. Type help or exit.")
    while True:
        try:
            line = input("> ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nexit")
            return 0
        if not line:
            continue
        if line in {"exit", "quit"}:
            print("exit")
            return 0
        if line == "help":
            print("remember <text> | query <text> | query5 <text> | stats | list | exit")
            continue
        command, _, rest = line.partition(" ")
        if command == "remember" and rest:
            id = mind.remember(rest)
            print(f"remembered id={id}")
        elif command == "query" and rest:
            for result in mind.query(rest, top_k=3):
                print(f"{result.score:.4f} id={result.id} {result.text}")
        elif command == "query5" and rest:
            for result in mind.query(rest, top_k=5):
                print(f"{result.score:.4f} id={result.id} {result.text}")
        elif command == "stats":
            print_stats(mind.stats())
        elif command == "list":
            for record in mind.store.list(include_expired=False):
                print(f"{record.id}: [{record.namespace}] {record.text}")
        else:
            print("unknown command")


def main(argv: list[str] | None = None) -> int:
    configure_stdio()
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command is None:
        if argv is not None:
            parser.print_help()
            return 0
        return run_interactive(args)

    if args.command == "quickstart":
        print_quickstart()
        return 0

    if args.command == "test":
        import pytest

        return int(pytest.main(["-q"]))

    if args.command == "serve":
        import uvicorn

        from .api import create_app

        uvicorn.run(create_app(mind=make_served_mind(args)), host=args.host, port=args.port)
        return 0

    if args.command == "studio":
        import webbrowser
        from threading import Timer

        import uvicorn

        from .api import create_app

        open_host = "127.0.0.1" if args.host in {"0.0.0.0", "::"} else args.host
        url = f"http://{open_host}:{args.port}/studio"
        print(f"WaveMind Studio: {url}")
        if not args.no_open:
            Timer(1.0, lambda: webbrowser.open(url)).start()
        uvicorn.run(create_app(mind=make_mind(args)), host=args.host, port=args.port)
        return 0

    if args.command == "restore":
        destination = Path(args.destination) if args.destination else (
            Path(args.db) if args.db else Path.cwd() / "wavemind.sqlite3"
        )
        path = SQLiteMemoryStore.restore_backup(
            source=args.source,
            destination=destination,
            overwrite=args.overwrite,
        )
        print(f"restored: {path}")
        return 0

    if args.command == "recovery-restore":
        destination = Path(args.destination) if args.destination else (
            Path(args.db) if args.db else Path.cwd() / "wavemind.sqlite3"
        )
        report = SQLiteMemoryStore.restore_recovery_journal(
            journal_path=args.source,
            destination=destination,
            until=args.until,
            overwrite=args.overwrite,
        )
        payload = report.as_dict()
        if args.json:
            print(json.dumps(payload, ensure_ascii=False, indent=2))
        else:
            print(f"restored: {payload['destination_path']}")
            print(f"applied_entries: {payload['applied_entries']}")
            print(f"restored_records: {payload['restored_records']}")
        return 0

    if args.command == "postgres-pitr-plan":
        plan = build_postgres_pitr_plan(
            dsn_env=args.dsn_env,
            basebackup_env=args.basebackup_env,
            wal_archive_env=args.wal_archive_env,
            restore_data_env=args.restore_data_env,
            restore_target_env=args.restore_target_env,
            retention_hours=args.retention_hours,
        )
        payload = plan.as_dict()
        if args.out:
            args.out.parent.mkdir(parents=True, exist_ok=True)
            args.out.write_text(
                json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
        if args.json:
            print(json.dumps(payload, ensure_ascii=False, indent=2))
        else:
            print(f"status: {payload['status']}")
            print(f"environment_status: {payload['environment_status']}")
            print(f"required_env: {', '.join(payload['required_env'])}")
            if payload["missing_env"]:
                print(f"missing_env: {', '.join(payload['missing_env'])}")
        if args.fail_on_missing_env and payload["missing_env"]:
            return 4
        return 0

    if args.command == "replicated-snapshot":
        memory = make_replicated_mind(args)
        try:
            object_store = None
            if args.s3 and (args.s3_endpoint_url or args.s3_region):
                object_store = S3SnapshotStore.from_uri(
                    args.s3,
                    endpoint_url=args.s3_endpoint_url,
                    region_name=args.s3_region,
                )
            report = ReplicatedSnapshotWorker(memory).run_once(
                destination=args.out,
                prefix=args.prefix,
                keep_last=args.keep_last,
                require_all=not args.allow_partial,
                offsite_destination=args.offsite,
                archive_destination=args.archive,
                object_store_destination=args.s3,
                object_store=object_store,
                object_store_keep_last=args.s3_keep_last,
            )
        finally:
            memory.close()
        payload = report.as_dict()
        if args.json:
            print(json.dumps(payload, ensure_ascii=False, indent=2))
        else:
            print(f"snapshot: {payload['snapshot_path']}")
            print(f"verified: {payload['verified']}")
            if payload["offsite_path"]:
                print(f"offsite: {payload['offsite_path']}")
                print(f"offsite_verified: {payload['offsite_verified']}")
            if payload["archive_path"]:
                print(f"archive: {payload['archive_path']}")
                print(f"archive_verified: {payload['archive_verified']}")
            if payload["object_store_upload"]:
                upload = payload["object_store_upload"]
                print(f"object_store: {upload['uri']}")
                print(f"object_store_verified: {upload['verified']}")
            if payload["pruned_object_store"]:
                print(f"object_store_pruned: {len(payload['pruned_object_store'])}")
        return 0 if report.ok else 4

    if args.command == "replicated-restore":
        source = Path(args.source)
        if args.source.startswith("s3://"):
            store = S3SnapshotStore.from_uri(
                args.source,
                endpoint_url=args.s3_endpoint_url,
                region_name=args.s3_region,
            )
            with tempfile.TemporaryDirectory(prefix="wavemind-s3-restore-") as tmp:
                remote_source = args.source
                if args.latest:
                    latest = store.latest_archive()
                    if latest is None:
                        print(
                            f"no snapshot archives found under {args.source}",
                            file=sys.stderr,
                        )
                        return 4
                    remote_source = latest.uri
                archive_path = store.download_archive(remote_source, tmp)
                restored, report = ReplicatedWaveMind.restore_snapshot_archive(
                    archive_path,
                    args.destination,
                    overwrite=args.overwrite,
                )
        elif args.latest:
            print("--latest is only supported with s3:// sources", file=sys.stderr)
            return 2
        elif source.name.endswith(".tar.gz") or source.suffix == ".tgz":
            restored, report = ReplicatedWaveMind.restore_snapshot_archive(
                source,
                args.destination,
                overwrite=args.overwrite,
            )
        else:
            restored, report = ReplicatedWaveMind.restore_snapshot(
                source,
                args.destination,
                overwrite=args.overwrite,
            )
        try:
            payload = report.as_dict()
        finally:
            restored.close()
        if args.json:
            print(json.dumps(payload, ensure_ascii=False, indent=2))
        else:
            print(f"restored: {payload['root_path']}")
            print(f"nodes: {len(payload['nodes'])}")
        return 0

    if args.command == "replicated-s3-archives":
        store = S3SnapshotStore.from_uri(
            args.s3,
            endpoint_url=args.s3_endpoint_url,
            region_name=args.s3_region,
        )
        pruned = ()
        if args.prune_keep_last is not None:
            pruned = store.prune_archives(keep_last=args.prune_keep_last)
        archives = store.list_archives()
        latest = archives[0] if archives else None
        archive_dicts = [archive.as_dict() for archive in archives]
        if args.latest:
            archive_dicts = [latest.as_dict()] if latest is not None else []
        payload = {
            "source": args.s3,
            "archives": archive_dicts,
            "latest": latest.as_dict() if latest is not None else None,
            "pruned": [archive.as_dict() for archive in pruned],
        }
        if args.json:
            print(json.dumps(payload, ensure_ascii=False, indent=2))
        else:
            if not archive_dicts:
                print(f"no snapshot archives found under {args.s3}")
            else:
                for archive in archive_dicts:
                    print(
                        f"{archive['uri']} "
                        f"bytes={archive['total_bytes']} "
                        f"verified={archive['verified']}"
                    )
                if pruned:
                    print(f"pruned: {len(pruned)}")
        return 0

    if args.command == "replicated-drill":
        store = S3SnapshotStore.from_uri(
            args.source,
            endpoint_url=args.s3_endpoint_url,
            region_name=args.s3_region,
        )
        try:
            report = ReplicatedObjectStoreDrillWorker(store).run_once(
                source=args.source,
                destination=args.destination,
                latest=args.latest or None,
                download_destination=args.download_to,
                overwrite=args.overwrite,
                namespace=args.namespace,
                query=args.query,
                expected_text=args.expect_text,
                top_k=args.top_k,
                disable_primary=not args.keep_primary,
                **replicated_restore_kwargs(args),
            )
        except Exception as exc:
            if args.json:
                print(
                    json.dumps(
                        {"ok": False, "error": str(exc)},
                        ensure_ascii=False,
                        indent=2,
                    )
                )
            else:
                print(f"drill failed: {exc}", file=sys.stderr)
            return 4
        payload = report.as_dict()
        if args.json:
            print(json.dumps(payload, ensure_ascii=False, indent=2))
        else:
            print(f"selected_archive: {payload['selected_archive']['uri']}")
            print(f"download_matches_object: {payload['download_matches_object']}")
            print(f"archive_verified: {payload['archive_verified']}")
            print(f"restored: {payload['restore_root']}")
            if payload["primary_node_disabled"]:
                print(f"primary_node_disabled: {payload['primary_node_disabled']}")
                print(
                    "recalled_after_primary_loss: "
                    f"{payload['recalled_after_primary_loss']}"
                )
            print(f"ok: {payload['ok']}")
        return 0 if report.ok else 4

    if args.command == "scale-plan":
        current_memories = args.current_memories
        vector_dim = 768 if args.encoder == "sentence" else 384
        index_name = args.index
        mind = None
        try:
            if current_memories is None:
                mind = make_mind(args)
                plan_obj = mind.scale_plan(
                    target_memories=args.target_memories,
                    namespace=args.namespace,
                    latency_target_ms=args.latency_target_ms,
                )
            else:
                plan_obj = build_scale_plan(
                    current_memories=current_memories,
                    target_memories=args.target_memories,
                    index=index_name,
                    vector_dim=vector_dim,
                    namespace=args.namespace,
                    latency_target_ms=args.latency_target_ms,
                )
            plan = plan_obj.as_dict()
            failed_threshold = (
                args.fail_on is not None
                and scale_status_meets_or_exceeds(plan_obj.status, args.fail_on)
            )
        finally:
            if mind is not None:
                mind.close()
        if args.json:
            print(json.dumps(plan, ensure_ascii=False, indent=2))
        else:
            print_scale_plan(plan)
        return 3 if failed_threshold else 0

    if args.command == "production-scale-plan":
        profiles = args.profile or ["all"]
        payload = build_production_scale_run_plan(
            profiles=profiles,
            disk_free_gb=args.disk_free_gb,
            output_dir=args.output_dir,
            state_dir=args.state_dir,
        )
        if args.write_artifact:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(
                json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
        if args.json:
            print(json.dumps(payload, ensure_ascii=False, indent=2))
        else:
            print_production_scale_run_plan(payload)
        failed = (
            args.fail_on_action_required
            and payload["summary"]["overall_status"] != "ready"
        )
        return 3 if failed else 0

    if args.command == "advise":
        current_memories = args.current_memories
        vector_dim = 768 if args.encoder == "sentence" else 384
        index_name = args.index
        mind = None
        try:
            if current_memories is None:
                mind = make_mind(args)
                stats = mind.stats(namespace=args.namespace)
                plan_obj = mind.scale_plan(
                    target_memories=args.target_memories,
                    namespace=args.namespace,
                    latency_target_ms=min(args.target_p99_ms, 100.0),
                )
            else:
                stats = {
                    "active_memories": current_memories,
                    "total_memories": current_memories,
                    "expired_memories": 0,
                    "audit_events": 0,
                    "index": index_name,
                    "index_healthy": True,
                    "vector_dim": vector_dim,
                }
                plan_obj = build_scale_plan(
                    current_memories=current_memories,
                    target_memories=args.target_memories,
                    index=index_name,
                    vector_dim=vector_dim,
                    namespace=args.namespace,
                    latency_target_ms=min(args.target_p99_ms, 100.0),
                )
            advice_obj = advise_memory_architecture(
                stats,
                scale_plan=plan_obj,
                namespace=args.namespace,
                target_memories=args.target_memories,
                target_p99_ms=args.target_p99_ms,
                observed_p99_ms=args.observed_p99_ms,
                namespace_count=args.namespace_count,
                node_count=args.node_count,
                replication_factor=args.replication_factor,
                read_quorum=args.read_quorum,
                read_fanout=args.read_fanout,
                target_qps=args.target_qps,
                deployment=args.deployment,
                multimodal=args.multimodal,
            )
            advice = advice_obj.as_dict()
            failed_threshold = (
                args.fail_on is not None
                and advice_status_meets_or_exceeds(advice_obj.status, args.fail_on)
            )
        finally:
            if mind is not None:
                mind.close()
        if args.json:
            print(json.dumps(advice, ensure_ascii=False, indent=2))
        else:
            print_architecture_advice(advice)
        return 3 if failed_threshold else 0

    if args.command == "production-evidence":
        payload = evaluate_production_evidence(args.root)
        if args.write_artifacts:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(
                json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            args.markdown_output.parent.mkdir(parents=True, exist_ok=True)
            args.markdown_output.write_text(
                render_markdown(payload),
                encoding="utf-8",
            )
        if args.json:
            print(json.dumps(payload, ensure_ascii=False, indent=2))
        else:
            print_production_evidence(payload)
            if args.write_artifacts:
                print(f"json_report: {args.output}")
                print(f"markdown_report: {args.markdown_output}")
        if args.strict and payload["overall_status"] != "pass":
            return 2
        return 0 if payload["overall_status"] in {"pass", "action_required"} else 1

    if args.command == "production-evidence-preflight":
        payload = evaluate_production_evidence_preflight(args.root)
        if args.write_artifacts:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(
                json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            args.markdown_output.parent.mkdir(parents=True, exist_ok=True)
            args.markdown_output.write_text(
                render_preflight_markdown(payload),
                encoding="utf-8",
            )
        if args.json:
            print(json.dumps(payload, ensure_ascii=False, indent=2))
        else:
            print_production_evidence_preflight(payload)
            if args.write_artifacts:
                print(f"json_report: {args.output}")
                print(f"markdown_report: {args.markdown_output}")
        if args.fail_on_action_required and payload["overall_status"] != "ready":
            return 2
        return 0

    if args.command == "production-evidence-bundle":
        payload = evaluate_production_evidence_bundle(args.root)
        if args.write_artifacts:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(
                json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            args.markdown_output.parent.mkdir(parents=True, exist_ok=True)
            args.markdown_output.write_text(
                render_bundle_markdown(payload),
                encoding="utf-8",
            )
        if args.json:
            print(json.dumps(payload, ensure_ascii=False, indent=2))
        else:
            print_production_evidence_bundle(payload)
            if args.write_artifacts:
                print(f"json_report: {args.output}")
                print(f"markdown_report: {args.markdown_output}")
        if args.strict and payload["claim_status"] != "claims_unlocked":
            return 2
        return 0 if payload["claim_status"] in {"claims_unlocked", "claims_limited"} else 1

    if args.command == "release-claims":
        payload = build_release_claims_manifest(args.root)
        if args.write_artifacts:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(
                json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            args.markdown_output.parent.mkdir(parents=True, exist_ok=True)
            args.markdown_output.write_text(
                render_release_claims_markdown(payload),
                encoding="utf-8",
            )
        if args.json:
            print(json.dumps(payload, ensure_ascii=False, indent=2))
        else:
            print_release_claims(payload)
            if args.write_artifacts:
                print(f"json_report: {args.output}")
                print(f"markdown_report: {args.markdown_output}")
        if args.strict and payload["claim_status"] != "claims_unlocked":
            return 2
        if args.fail_on_blocked and payload["release_status"] == "release_blocked":
            return 2
        return 0 if payload["release_status"] != "release_blocked" else 1

    if args.command == "scale-gap":
        payload = build_scale_gap_manifest(args.root)
        if args.write_artifacts:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(
                json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            args.markdown_output.parent.mkdir(parents=True, exist_ok=True)
            args.markdown_output.write_text(
                render_scale_gap_markdown(payload),
                encoding="utf-8",
            )
        if args.json:
            print(json.dumps(payload, ensure_ascii=False, indent=2))
        else:
            summary = payload["summary"]
            print(f"overall_status: {payload['overall_status']}")
            print(f"complete_profiles: {summary['complete_count']}/{summary['total_profiles']}")
            print(f"planned_target_memories: {summary['planned_target_memories']}")
            print(f"proven_target_memories: {summary['proven_target_memories']}")
            print(f"nearest_baseline_max_memories: {summary['nearest_baseline_max_memories']}")
            for row in payload["profile_gaps"]:
                print(
                    f"- {row['profile']}: {row['status']} "
                    f"target={row['target_memories']} artifact={row['output_artifact']}"
                )
            if args.write_artifacts:
                print(f"json_report: {args.output}")
                print(f"markdown_report: {args.markdown_output}")
        if args.fail_on_action_required and payload["overall_status"] != "complete":
            return 2
        return 0

    if args.command == "cluster-plan":
        namespaces = list(args.namespace)
        namespaces.extend(
            f"{args.namespace_prefix}:{index}"
            for index in range(max(0, int(args.namespace_count)))
        )
        nodes = [_parse_cluster_node(value) for value in args.node]
        plan = build_cluster_plan(
            namespaces=namespaces,
            nodes=nodes,
            replication_factor=args.replication_factor,
        )
        payload = plan.as_dict()
        if args.kubernetes:
            payload["kubernetes"] = plan.kubernetes_manifest(
                image=args.image,
                storage_size=args.storage_size,
            )
        if args.repair_cronjob:
            payload["repair_cronjob"] = plan.kubernetes_repair_cronjob(
                image=args.image,
                schedule=args.repair_schedule,
                name=args.repair_name,
                api_key_secret=args.repair_api_key_secret,
                api_key_secret_key=args.repair_api_key_secret_key,
                repair_limit=args.repair_limit,
                include_expired=args.repair_include_expired,
                tags=tuple(args.repair_tag),
            )
        if args.json:
            print(json.dumps(payload, ensure_ascii=False, indent=2))
        else:
            print(f"nodes: {len(plan.nodes)}")
            print(f"namespaces: {len(plan.placements)}")
            print(f"replication_factor: {plan.replication_factor}")
            print("node_load:")
            for node_id, load in sorted(plan.node_load.items()):
                print(f"- {node_id}: {load}")
            if plan.warnings:
                print("warnings:")
                for warning in plan.warnings:
                    print(f"- {warning}")
        return 0

    if args.command == "cluster-autoscale-plan":
        namespaces = list(args.namespace)
        namespaces.extend(
            f"{args.namespace_prefix}:{index}"
            for index in range(max(0, int(args.namespace_count)))
        )
        if not namespaces:
            print("cluster-autoscale-plan requires --namespace or --namespace-count", file=sys.stderr)
            return 2
        plan = build_cluster_autoscale_plan(
            namespaces=namespaces,
            nodes=[_parse_cluster_node(value) for value in args.node],
            replication_factor=args.replication_factor,
            target_memories=args.target_memories,
            max_memories_per_node=args.max_memories_per_node,
            headroom=args.headroom,
            node_prefix=args.node_prefix,
            address_template=args.address_template,
            zones=tuple(args.zone),
            max_moves=args.max_moves,
        )
        payload = plan.as_dict()
        if args.rebalance_plan:
            payload["rebalance_plan"] = plan.rebalance_plan(
                batch_size=args.rebalance_batch_size,
                max_node_moves_per_batch=args.rebalance_max_node_moves_per_batch,
                drain_nodes=tuple(args.drain_node),
            ).as_dict()
        if args.json:
            print(json.dumps(payload, ensure_ascii=False, indent=2))
        else:
            print_cluster_autoscale_plan(payload)
        return 0

    if args.command == "control-plane-consensus":
        payload = run_control_plane_consensus_profile()
        if args.json:
            print(json.dumps(payload, ensure_ascii=False, indent=2))
        else:
            print(f"ok: {payload['ok']}")
            print(f"voters: {payload['voters_initial']} -> {payload['voters_after_membership']}")
            print(f"term: {payload['lease_term']} -> {payload['new_leader_term']}")
            print(f"revision: {payload['final_revision']}")
            print(f"minority_commit_blocked: {payload['minority_commit_blocked']}")
            print(f"stale_leader_blocked: {payload['stale_leader_blocked']}")
            print(f"stale_revision_blocked: {payload['stale_revision_blocked']}")
        return 0 if payload["ok"] else 4

    if args.command == "cluster-repair":
        namespaces = list(args.namespace)
        namespaces.extend(
            f"{args.namespace_prefix}:{index}"
            for index in range(max(0, int(args.namespace_count)))
        )
        if not namespaces:
            print("cluster-repair requires --namespace or --namespace-count", file=sys.stderr)
            return 2
        client = HTTPNamespaceShardClient(api_key=args.api_key, timeout=args.timeout)
        memory = DistributedShardedWaveMind(
            nodes=[_parse_cluster_node(value) for value in args.node],
            replication_factor=args.replication_factor,
            write_quorum=args.write_quorum,
            read_quorum=args.read_quorum,
            read_fanout=args.read_fanout,
            client=client,
        )
        report = DistributedRepairWorker(memory).run_once(
            namespaces=tuple(namespaces),
            limit=args.limit,
            include_expired=args.include_expired,
            tags=tuple(args.tag),
            fail_fast=args.fail_fast,
        )
        payload = report.as_dict()
        if args.json:
            print(json.dumps(payload, ensure_ascii=False, indent=2))
        else:
            print(f"namespaces: {len(payload['namespaces'])}")
            print(f"repaired_total: {payload['repaired_total']}")
            print(f"tombstone_deleted: {payload['tombstone_deleted']}")
            if payload["failed_namespaces"]:
                print("failed_namespaces:")
                for namespace, error in payload["failed_namespaces"].items():
                    print(f"- {namespace}: {error}")
            print(f"ok: {payload['ok']}")
        return 0 if report.ok else 4

    if args.command == "cluster-health":
        client = HTTPNamespaceShardClient(api_key=args.api_key, timeout=args.timeout)
        memory = DistributedShardedWaveMind(
            nodes=[_parse_cluster_node(value) for value in args.node],
            replication_factor=args.replication_factor,
            write_quorum=args.write_quorum,
            read_quorum=args.read_quorum,
            read_fanout=args.read_fanout,
            client=client,
        )
        health = memory.probe_nodes()
        stats = memory.stats()
        payload = {
            "ok": stats["degraded_nodes"] == 0 and stats["unavailable_nodes"] == 0,
            "nodes": stats["nodes"],
            "healthy_nodes": stats["healthy_nodes"],
            "degraded_nodes": stats["degraded_nodes"],
            "unavailable_nodes": stats["unavailable_nodes"],
            "replication_factor": stats["replication_factor"],
            "write_quorum": stats["write_quorum"],
            "read_quorum": stats["read_quorum"],
            "read_fanout": stats["read_fanout"],
            "node_health": health,
        }
        if args.json:
            print(json.dumps(payload, ensure_ascii=False, indent=2))
        else:
            print(f"ok: {str(payload['ok']).lower()}")
            print(f"healthy_nodes: {payload['healthy_nodes']}")
            print(f"degraded_nodes: {payload['degraded_nodes']}")
            print(f"unavailable_nodes: {payload['unavailable_nodes']}")
            for node_id, node in health.items():
                suffix = f" ({node['last_error']})" if node["last_error"] else ""
                print(f"- {node_id}: {node['status']}{suffix}")
        return 4 if args.fail_on_degraded and not payload["ok"] else 0

    if args.command == "operator-sample":
        _emit_json(_operator_spec_from_args(args).custom_resource(), out=args.out)
        return 0

    if args.command == "operator-bundle":
        sample = WaveMindClusterSpec(
            name=args.sample_name,
            namespace=args.namespace,
            image=args.sample_image,
            replicas=args.sample_replicas,
            replication_factor=args.sample_replication_factor,
            namespace_count=args.sample_namespace_count,
        )
        _emit_json(
            operator_bundle(
                operator_image=args.operator_image,
                namespace=args.namespace,
                sample=sample,
            ),
            out=args.out,
        )
        return 0

    if args.command == "operator-reconcile":
        _emit_json(operator_reconcile(_read_json_file(args.file)), out=args.out)
        return 0

    if args.command == "operator-status":
        _emit_json(
            operator_status(
                _read_json_file(args.file),
                observed=_operator_status_observed_from_args(args),
            ),
            out=args.out,
        )
        return 0

    if args.command == "operator-loop":
        client = KubernetesApplyClient.in_cluster(timeout=args.timeout)
        report = operator_loop(
            namespace=args.namespace,
            client=client,
            interval_seconds=args.interval_seconds,
            once=args.once,
        )
        _print_json(report)
        return 0

    if args.command == "serverless-sample":
        spec = _serverless_spec_from_args(args)
        if args.operational_profile:
            payload = spec.operational_profile(
                _serverless_workload_target_from_args(args),
                observed=_serverless_observed_telemetry_from_args(args),
            )
        elif args.readiness:
            payload = spec.readiness_report()
        else:
            payload = spec.resource_list(include_keda=not args.no_keda)
        _emit_json(payload, out=args.out)
        return 0

    mind = make_mind(args)
    if args.command == "remember":
        id = mind.remember(
            args.text,
            namespace=args.namespace,
            tags=args.tag,
            ttl_seconds=args.ttl_seconds,
            priority=args.priority,
        )
        print(f"remembered id={id}")
        return 0

    if args.command == "query":
        results = mind.query(
            args.text,
            namespace=args.namespace,
            tags=args.tag,
            top_k=args.top_k,
            min_score=args.min_score,
        )
        if args.json:
            print(json.dumps([result.__dict__ for result in results], ensure_ascii=False, indent=2))
        else:
            for result in results:
                print(
                    f"{result.score:.4f} "
                    f"vector={result.vector_score:.4f} "
                    f"field={result.field_score:.4f} "
                    f"graph={result.graph_score:.4f} "
                    f"id={result.id} {result.text}"
                )
        return 0

    if args.command == "forget":
        print(f"deleted={mind.forget(id=args.id, text=args.text, namespace=args.namespace)}")
        return 0

    if args.command == "feedback":
        accepted = mind.feedback(
            args.id,
            useful=not args.not_useful,
            strength=args.strength,
            namespace=args.namespace,
            query=args.query,
            reason=args.reason,
        )
        record = mind.store.get(args.id) if accepted else None
        payload = {
            "ok": bool(accepted),
            "id": int(args.id),
            "namespace": record.namespace if record is not None else args.namespace,
            "priority": float(record.priority) if record is not None else None,
            "access_count": int(record.access_count) if record is not None else None,
        }
        if args.json:
            print(json.dumps(payload, ensure_ascii=False, indent=2))
        else:
            if not accepted:
                print(f"ok=false id={int(args.id)}")
            else:
                print(
                    f"ok=true id={int(args.id)} namespace={record.namespace} "
                    f"priority={record.priority:.4f} access_count={record.access_count}"
                )
        return 0 if accepted else 4

    if args.command == "feedback-batch":
        if args.file == "-":
            raw_payload = sys.stdin.read()
        else:
            raw_payload = Path(args.file).read_text(encoding="utf-8")
        payload = json.loads(raw_payload)
        if isinstance(payload, dict):
            items = payload.get("items", [])
            namespace = payload.get("namespace", args.namespace)
        else:
            items = payload
            namespace = args.namespace
        if not isinstance(items, list) or not items:
            print("feedback batch requires at least one item", file=sys.stderr)
            return 2
        report = mind.feedback_batch(items, namespace=namespace)
        output = {
            "ok": int(report["rejected"]) == 0,
            "accepted": int(report["accepted"]),
            "rejected": int(report["rejected"]),
            "accepted_ids": list(report["accepted_ids"]),
            "rejected_ids": list(report["rejected_ids"]),
            "namespaces": list(report["namespaces"]),
            "results": list(report["results"]),
            "errors": list(report["errors"]),
        }
        if args.json:
            print(json.dumps(output, ensure_ascii=False, indent=2))
        else:
            print(
                f"accepted={output['accepted']} "
                f"rejected={output['rejected']} "
                f"namespaces={','.join(output['namespaces']) or '-'}"
            )
            for error in output["errors"]:
                print(
                    f"rejected id={error.get('id')} "
                    f"namespace={error.get('namespace') or '-'} "
                    f"error={error.get('error')}",
                    file=sys.stderr,
                )
        return 4 if args.fail_on_rejected and output["rejected"] else 0

    if args.command == "stats":
        print_stats(mind.stats(namespace=args.namespace))
        return 0

    if args.command == "index-health":
        health = mind.index_health()
        if args.json:
            print(json.dumps(health, ensure_ascii=False, indent=2))
        else:
            print_stats(health)
        return 0

    if args.command == "rebuild-index":
        health = mind.rebuild_index()
        if args.json:
            print(json.dumps(health, ensure_ascii=False, indent=2))
        else:
            print_stats(health)
        return 0

    if args.command == "consolidate":
        concepts = mind.consolidate_concepts(
            namespace=args.namespace,
            seed_text=args.seed,
            min_energy=args.min_energy,
            min_size=args.min_size,
            max_concepts=args.max_concepts,
            priority=args.priority,
        )
        if args.json:
            print(json.dumps({"concepts": concepts}, ensure_ascii=False, indent=2))
        else:
            if not concepts:
                print("created=0")
            for concept in concepts:
                print(f"created id={concept['id']} namespace={concept['namespace']} {concept['text']}")
        return 0

    if args.command == "audit":
        events = mind.audit_events(
            namespace=args.namespace,
            action=args.action,
            limit=args.limit,
        )
        payload = [
            {
                "id": event.id,
                "created_at": event.created_at,
                "action": event.action,
                "namespace": event.namespace,
                "memory_id": event.memory_id,
                "metadata": event.metadata,
            }
            for event in events
        ]
        if args.json:
            print(json.dumps(payload, ensure_ascii=False, indent=2))
        else:
            for event in events:
                namespace = event.namespace or "-"
                memory_id = event.memory_id if event.memory_id is not None else "-"
                print(
                    f"{event.created_at:.3f} "
                    f"action={event.action} "
                    f"namespace={namespace} "
                    f"memory_id={memory_id}"
                )
        return 0

    if args.command == "maintenance":
        report = MemoryMaintenanceWorker(mind).run_once(
            namespace=args.namespace,
            consolidate_steps=args.consolidate_steps,
            consolidate_concepts=args.consolidate_concepts,
            rebuild_unhealthy_index=not args.no_rebuild_index,
        )
        payload = report.as_dict()
        if args.json:
            print(json.dumps(payload, ensure_ascii=False, indent=2))
        else:
            print_stats(payload)
        return 0

    if args.command == "cache-prewarm":
        if args.redis_url:
            cache = RedisHotMemoryCache.from_url(
                args.redis_url,
                prefix=args.redis_prefix,
                ttl_seconds=args.ttl_seconds,
            )
        else:
            cache = HotMemoryCache(capacity=args.capacity, ttl_seconds=args.ttl_seconds)
        report = CachePrewarmWorker(mind, cache).run_once(
            namespace=args.namespace,
            audit_limit=args.audit_limit,
            max_queries=args.max_queries,
            min_frequency=args.min_frequency,
            top_k=args.top_k,
            min_score=args.min_score,
        )
        payload = report.as_dict()
        payload["cache"] = "redis" if args.redis_url else "local"
        if args.json:
            print(json.dumps(payload, ensure_ascii=False, indent=2))
        else:
            print_stats(payload)
            if not args.redis_url:
                print(
                    "note: local cache is process-local; use --redis-url for production prewarm",
                    file=sys.stderr,
                )
        return 0 if report.ok else 4

    if args.command == "memory-os-plan":
        plan = MemoryOSScheduler(mind).plan(
            namespace=args.namespace,
            audit_limit=args.audit_limit,
            max_hot_queries=args.max_hot_queries,
            min_frequency=args.min_frequency,
            top_k=args.top_k,
            min_score=args.min_score,
            target_memories=args.target_memories,
            namespace_count=args.namespace_count,
            node_count=args.node_count,
            replication_factor=args.replication_factor,
            read_quorum=args.read_quorum,
            read_fanout=args.read_fanout,
            target_qps=args.target_qps,
            target_p99_ms=args.target_p99_ms,
            observed_p99_ms=args.observed_p99_ms,
            deployment=args.deployment,
            cache_mode=args.cache_mode,
            multimodal=args.multimodal,
            memory_pressure_threshold=args.memory_pressure_threshold,
        )
        payload = plan.as_dict()
        if args.json:
            print(json.dumps(payload, ensure_ascii=False, indent=2))
        else:
            print_stats(payload)
        if args.strict and plan.status not in {"ok", "watch"}:
            return 3
        return 0 if plan.ok else 4

    if args.command == "memory-os":
        cache = None
        lock = None
        if not args.no_cache:
            if args.redis_url:
                cache = RedisHotMemoryCache.from_url(
                    args.redis_url,
                    prefix=args.redis_prefix,
                    ttl_seconds=args.ttl_seconds,
                )
            else:
                cache = HotMemoryCache(
                    capacity=args.capacity,
                    ttl_seconds=args.ttl_seconds,
                )
        if args.redis_url:
            lock_key = f"{args.lock_prefix.rstrip(':')}:{args.namespace or 'all'}"
            lock = RedisMemoryOSLock.from_url(
                args.redis_url,
                key=lock_key,
                ttl_seconds=args.lock_ttl_seconds,
            )
        report = MemoryOSWorker(mind, cache).run_once(
            namespace=args.namespace,
            audit_limit=args.audit_limit,
            max_hot_queries=args.max_hot_queries,
            min_frequency=args.min_frequency,
            top_k=args.top_k,
            min_score=args.min_score,
            consolidate_steps=args.consolidate_steps,
            consolidate_concepts=not args.no_consolidate_concepts,
            concept_seed_text=args.concept_seed_text,
            min_concept_energy=args.min_concept_energy,
            min_concept_size=args.min_concept_size,
            max_concepts=args.max_concepts,
            concept_priority=args.concept_priority,
            predict_priorities=not args.no_predict_priorities,
            max_priority_predictions=args.max_priority_predictions,
            priority_boost_per_hit=args.priority_boost_per_hit,
            max_priority_boost=args.max_priority_boost,
            adaptive_forgetting=not args.no_adaptive_forgetting,
            forgetting_min_age_seconds=args.forgetting_min_age_seconds,
            forgetting_max_memories=args.forgetting_max_memories,
            forgetting_max_access_count=args.forgetting_max_access_count,
            forgetting_priority_decay=args.forgetting_priority_decay,
            forgetting_min_priority=args.forgetting_min_priority,
            predictive_prefetch=not args.no_predictive_prefetch,
            max_predictive_queries=args.max_predictive_queries,
            predictive_terms_per_hot_query=args.predictive_terms_per_hot_query,
            transition_prefetch_window_seconds=args.transition_prefetch_window_seconds,
            rebuild_unhealthy_index=not args.no_rebuild_index,
            memory_pressure_threshold=args.memory_pressure_threshold,
            architecture_advice=not args.no_architecture_advice,
            target_memories=args.target_memories,
            target_p99_ms=args.target_p99_ms,
            observed_p99_ms=args.observed_p99_ms,
            namespace_count=args.namespace_count,
            node_count=args.node_count,
            replication_factor=args.replication_factor,
            read_quorum=args.read_quorum,
            read_fanout=args.read_fanout,
            target_qps=args.target_qps,
            deployment=args.deployment,
            multimodal=args.multimodal,
            lock=lock,
            lock_required=args.lock_required,
        )
        payload = report.as_dict()
        payload["cache"] = (
            "disabled"
            if args.no_cache
            else "redis"
            if args.redis_url
            else "local"
        )
        if args.json:
            print(json.dumps(payload, ensure_ascii=False, indent=2))
        else:
            print_stats(payload)
            if not args.redis_url and not args.no_cache:
                print(
                    "note: local cache is process-local; use --redis-url for production Memory OS prewarm",
                    file=sys.stderr,
                )
        return 0 if report.ok else 4

    if args.command == "import":
        ids = import_path(
            args.path,
            mind,
            namespace=args.namespace,
            tags=args.tag,
            max_chars=args.max_chars,
            overlap=args.overlap,
        )
        print(f"imported={len(ids)} ids={','.join(str(id) for id in ids)}")
        return 0

    if args.command == "backup":
        path = mind.save(
            args.out,
            keep_last=args.keep_last,
            backup_prefix=args.prefix,
        )
        print(f"backup: {path}")
        return 0

    if args.command == "benchmark":
        existing = {
            record.text
            for record in mind.store.list(namespace=args.namespace, include_expired=False)
        }
        for query, text in synthetic_cases(namespace=args.namespace):
            if text not in existing:
                mind.remember(text, namespace=args.namespace)
                existing.add(text)
        cases = [
            BenchmarkCase(query=query, expected_text=text, namespace=args.namespace)
            for query, text in synthetic_cases(namespace=args.namespace)
        ]
        report = run_benchmark(mind, cases, k=args.top_k)
        print(json.dumps(report.__dict__, ensure_ascii=False, indent=2))
        return 0

    parser.print_help()
    return 2


def _parse_cluster_node(value: str) -> ClusterNode:
    node_id, sep, address = value.partition("=")
    node_id = node_id.strip()
    address = address.strip() if sep else node_id
    return ClusterNode(id=node_id, address=address)


def _add_operator_spec_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--name", default="wavemind")
    parser.add_argument("--namespace", default="default")
    parser.add_argument("--image", default="ghcr.io/caspiang/wavemind:latest")
    parser.add_argument("--replicas", type=int, default=3)
    parser.add_argument("--replication-factor", type=int, default=2)
    parser.add_argument("--namespace-count", type=int, default=128)
    parser.add_argument("--namespace-prefix", default="tenant")
    parser.add_argument("--storage-size", default="20Gi")
    parser.add_argument("--service-port", type=int, default=8000)
    parser.add_argument("--encoder", default="hash")
    parser.add_argument("--index", default="faiss-persisted")
    parser.add_argument("--score-threshold", type=float, default=0.0)
    parser.add_argument("--cache-capacity", type=int, default=512)
    parser.add_argument("--cache-ttl-seconds", type=float, default=60.0)
    parser.add_argument("--redis-url")
    parser.add_argument("--auth-secret")
    parser.add_argument("--auth-secret-key", default="api-key")
    parser.add_argument("--repair-schedule", default="*/15 * * * *")
    parser.add_argument("--repair-limit", type=int, default=1000)
    parser.add_argument("--no-repair", action="store_true")
    parser.add_argument("--no-control-plane-consensus", action="store_true")
    parser.add_argument("--control-plane-lease-ttl-seconds", type=float, default=30.0)
    parser.add_argument("--control-plane-config-revision", type=int, default=0)
    parser.add_argument("--autoscaling", action="store_true")
    parser.add_argument("--autoscaling-min-replicas", type=int, default=3)
    parser.add_argument("--autoscaling-max-replicas", type=int, default=12)
    parser.add_argument("--autoscaling-target-cpu", type=int, default=70)
    parser.add_argument("--autoscaling-target-memory", type=int)
    parser.add_argument("--autoscaling-target-memories", type=int)
    parser.add_argument("--autoscaling-max-memories-per-node", type=int, default=1_000_000)
    parser.add_argument("--autoscaling-headroom", type=float, default=0.70)
    parser.add_argument("--rebalance-batch-size", type=int, default=50)
    parser.add_argument("--rebalance-max-node-moves-per-batch", type=int, default=50)
    parser.add_argument("--rebalance-preview-batches", type=int, default=3)


def _operator_spec_from_args(args: argparse.Namespace) -> WaveMindClusterSpec:
    return WaveMindClusterSpec(
        name=args.name,
        namespace=args.namespace,
        image=args.image,
        replicas=args.replicas,
        replication_factor=args.replication_factor,
        namespace_count=args.namespace_count,
        namespace_prefix=args.namespace_prefix,
        storage_size=args.storage_size,
        service_port=args.service_port,
        encoder=args.encoder,
        index=args.index,
        score_threshold=args.score_threshold,
        cache_capacity=args.cache_capacity,
        cache_ttl_seconds=args.cache_ttl_seconds,
        redis_url=args.redis_url,
        auth_secret=args.auth_secret,
        auth_secret_key=args.auth_secret_key,
        repair_enabled=not args.no_repair,
        repair_schedule=args.repair_schedule,
        repair_limit=args.repair_limit,
        control_plane_consensus_enabled=not args.no_control_plane_consensus,
        control_plane_lease_ttl_seconds=args.control_plane_lease_ttl_seconds,
        control_plane_config_revision=args.control_plane_config_revision,
        autoscaling_enabled=args.autoscaling,
        autoscaling_min_replicas=args.autoscaling_min_replicas,
        autoscaling_max_replicas=args.autoscaling_max_replicas,
        autoscaling_target_cpu_utilization=args.autoscaling_target_cpu,
        autoscaling_target_memory_utilization=args.autoscaling_target_memory,
        autoscaling_target_memories=args.autoscaling_target_memories,
        autoscaling_max_memories_per_node=args.autoscaling_max_memories_per_node,
        autoscaling_headroom=args.autoscaling_headroom,
        rebalance_batch_size=args.rebalance_batch_size,
        rebalance_max_node_moves_per_batch=args.rebalance_max_node_moves_per_batch,
        rebalance_preview_batches=args.rebalance_preview_batches,
    )


def _operator_status_observed_from_args(args: argparse.Namespace) -> dict[str, int]:
    mapping = {
        "readyReplicas": args.ready_replicas,
        "currentReplicas": args.current_replicas,
        "hpaDesiredReplicas": args.hpa_desired_replicas,
        "currentMemories": args.current_memories,
        "degradedNodes": args.degraded_nodes,
        "unavailableNodes": args.unavailable_nodes,
    }
    return {key: int(value) for key, value in mapping.items() if value is not None}


def _add_serverless_spec_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--name", default="wavemind")
    parser.add_argument("--namespace", default="default")
    parser.add_argument("--image", default="ghcr.io/caspiang/wavemind:latest")
    parser.add_argument("--service-port", type=int, default=8000)
    parser.add_argument("--min-scale", type=int, default=0)
    parser.add_argument("--max-scale", type=int, default=24)
    parser.add_argument("--target-concurrency", type=int, default=50)
    parser.add_argument("--scale-down-delay-seconds", type=int, default=300)
    parser.add_argument("--encoder", default="hash")
    parser.add_argument("--index", default="qdrant")
    parser.add_argument("--score-threshold", type=float, default=0.0)
    parser.add_argument("--no-audit-queries", action="store_true")
    parser.add_argument("--postgres-secret", default="wavemind-postgres")
    parser.add_argument("--postgres-secret-key", default="dsn")
    parser.add_argument("--qdrant-secret", default="wavemind-qdrant")
    parser.add_argument("--qdrant-secret-key", default="url")
    parser.add_argument("--qdrant-api-key-secret")
    parser.add_argument("--qdrant-api-key-secret-key", default="api-key")
    parser.add_argument("--redis-secret", default="wavemind-redis")
    parser.add_argument("--redis-secret-key", default="url")
    parser.add_argument("--no-redis", action="store_true")
    parser.add_argument("--auth-secret", default="wavemind-auth")
    parser.add_argument("--auth-secret-key", default="api-keys")
    parser.add_argument("--no-auth", action="store_true")


def _serverless_spec_from_args(args: argparse.Namespace) -> WaveMindServerlessSpec:
    qdrant_url = None
    if args.index.lower() == "qdrant":
        qdrant_url = SecretEnvRef(args.qdrant_secret, args.qdrant_secret_key)
    qdrant_api_key = (
        SecretEnvRef(args.qdrant_api_key_secret, args.qdrant_api_key_secret_key)
        if args.qdrant_api_key_secret
        else None
    )
    return WaveMindServerlessSpec(
        name=args.name,
        namespace=args.namespace,
        image=args.image,
        service_port=args.service_port,
        min_scale=args.min_scale,
        max_scale=args.max_scale,
        target_concurrency=args.target_concurrency,
        scale_down_delay_seconds=args.scale_down_delay_seconds,
        index=args.index,
        encoder=args.encoder,
        score_threshold=args.score_threshold,
        audit_queries=not args.no_audit_queries,
        postgres_dsn=SecretEnvRef(args.postgres_secret, args.postgres_secret_key),
        qdrant_url=qdrant_url,
        qdrant_api_key=qdrant_api_key,
        redis_url=None if args.no_redis else SecretEnvRef(args.redis_secret, args.redis_secret_key),
        api_keys=None if args.no_auth else SecretEnvRef(args.auth_secret, args.auth_secret_key),
    )


def _serverless_workload_target_from_args(args: argparse.Namespace) -> ServerlessWorkloadTarget:
    return ServerlessWorkloadTarget(
        requests_per_second=args.target_rps,
        avg_request_ms=args.avg_request_ms,
        p99_request_ms=args.p99_request_ms,
        cold_start_ms=args.cold_start_ms,
        target_p99_ms=args.target_p99_ms,
        cold_start_budget_ms=args.cold_start_budget_ms,
        active_fraction=args.active_fraction,
        replica_hourly_cost_usd=args.replica_hourly_cost_usd,
        monthly_budget_usd=args.monthly_budget_usd,
        max_error_rate=args.max_error_rate,
        max_scale_out_seconds=args.max_scale_out_seconds,
    )


def _serverless_observed_telemetry_from_args(
    args: argparse.Namespace,
) -> ServerlessObservedTelemetry | None:
    if not args.observed_telemetry:
        return None
    return ServerlessObservedTelemetry.from_mapping(_read_json_file(args.observed_telemetry))


def _read_json_file(path: str) -> dict[str, object]:
    if path == "-":
        return json.loads(sys.stdin.read())
    raw = Path(path).read_bytes()
    for encoding in ("utf-8-sig", "utf-16"):
        try:
            return json.loads(raw.decode(encoding))
        except UnicodeDecodeError:
            continue
    return json.loads(raw.decode("utf-8", errors="replace"))


def _print_json(payload: object) -> None:
    print(json.dumps(payload, ensure_ascii=False, indent=2))


def _emit_json(payload: object, *, out: str | None = None) -> None:
    text = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
    if out:
        Path(out).write_text(text, encoding="utf-8")
    else:
        print(text, end="")


if __name__ == "__main__":
    raise SystemExit(main())
