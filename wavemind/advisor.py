from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

from .scale import (
    LOCAL_WATCH_LIMIT,
    SERVICE_INDEX_LIMIT,
    SINGLE_NODE_ANN_LIMIT,
    ScalePlan,
    build_scale_plan,
)


ADVICE_LEVELS = {
    "ok": 0,
    "watch": 1,
    "action_required": 2,
    "architecture_required": 3,
}


@dataclass(frozen=True)
class MemoryArchitectureRecommendation:
    id: str
    severity: str
    title: str
    rationale: str
    action: str
    commands: tuple[str, ...] = ()
    docs: tuple[str, ...] = ()

    def as_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True)
class MemoryArchitectureAdvice:
    status: str
    production_ready: bool
    deployment: str
    namespace: str | None
    current_memories: int
    target_memories: int
    index: str
    vector_dim: int
    target_p99_ms: float
    observed_p99_ms: float | None
    namespace_count: int | None
    node_count: int | None
    replication_factor: int
    read_quorum: int
    read_fanout: int
    scale_plan: dict[str, object]
    recommendations: tuple[MemoryArchitectureRecommendation, ...]
    next_commands: tuple[str, ...]

    def as_dict(self) -> dict[str, object]:
        payload = asdict(self)
        payload["recommendations"] = [
            recommendation.as_dict() for recommendation in self.recommendations
        ]
        return payload


def advice_status_meets_or_exceeds(status: str, threshold: str) -> bool:
    if threshold not in ADVICE_LEVELS:
        raise ValueError(
            "threshold must be one of: "
            + ", ".join(sorted(ADVICE_LEVELS, key=ADVICE_LEVELS.get))
        )
    return ADVICE_LEVELS.get(status, 0) >= ADVICE_LEVELS[threshold]


def advise_memory_architecture(
    stats: dict[str, Any],
    *,
    scale_plan: ScalePlan | dict[str, Any] | None = None,
    namespace: str | None = None,
    target_memories: int | None = None,
    target_p99_ms: float = 100.0,
    observed_p99_ms: float | None = None,
    namespace_count: int | None = None,
    node_count: int | None = None,
    replication_factor: int = 3,
    read_quorum: int = 1,
    read_fanout: int | None = None,
    target_qps: float = 100.0,
    deployment: str = "local",
    multimodal: bool = False,
) -> MemoryArchitectureAdvice:
    """Return deterministic production architecture advice from live memory stats."""

    current = _int_stat(stats, "active_memories", "total_memories")
    vector_dim = _int_stat(stats, "vector_dim", default=384)
    index = str(stats.get("index") or "numpy").lower().replace("_", "-")
    deployment_name = (deployment or "local").lower()
    target = max(current, int(target_memories if target_memories is not None else current))
    target_p99 = float(target_p99_ms)
    effective_replication_factor = max(1, int(replication_factor))
    effective_read_quorum = max(1, int(read_quorum))
    effective_read_fanout = (
        effective_replication_factor
        if read_fanout is None
        else max(1, int(read_fanout))
    )

    plan_dict: dict[str, Any]
    if scale_plan is None:
        plan = build_scale_plan(
            current_memories=current,
            target_memories=target,
            index=index,
            vector_dim=vector_dim,
            namespace=namespace,
            latency_target_ms=min(target_p99, 100.0),
        )
        plan_dict = plan.as_dict()
    elif isinstance(scale_plan, ScalePlan):
        plan_dict = scale_plan.as_dict()
    else:
        plan_dict = dict(scale_plan)

    recommendations: list[MemoryArchitectureRecommendation] = []
    seen: set[str] = set()

    def add(
        id: str,
        severity: str,
        title: str,
        rationale: str,
        action: str,
        commands: tuple[str, ...] = (),
        docs: tuple[str, ...] = (),
    ) -> None:
        if id in seen:
            return
        seen.add(id)
        recommendations.append(
            MemoryArchitectureRecommendation(
                id=id,
                severity=severity,
                title=title,
                rationale=rationale,
                action=action,
                commands=commands,
                docs=docs,
            )
        )

    scale_status = str(plan_dict.get("status") or "ok")
    if ADVICE_LEVELS.get(scale_status, 0) >= ADVICE_LEVELS["watch"]:
        add(
            "scale-plan",
            scale_status,
            "Scale plan requires attention",
            f"The current scale tier is {plan_dict.get('tier')} for target {target:,} memories.",
            "Treat the scale-plan output as the deployment preflight and resolve its warnings before growth.",
            (
                f"wavemind scale-plan --target-memories {target} --fail-on action_required --json",
            ),
            ("README.md#scale-readiness", "docs/ROADMAP.md"),
        )

    if not bool(stats.get("index_healthy", True)):
        add(
            "index-health",
            "architecture_required",
            "Rebuild unhealthy vector index",
            "The source-of-truth memory count and vector index count disagree.",
            "Rebuild and validate the candidate index before serving production traffic.",
            ("wavemind rebuild-index --json", "wavemind index-health --json"),
        )

    if index in {"numpy", "exact"} and target > LOCAL_WATCH_LIMIT:
        add(
            "ann-candidate-index",
            "action_required",
            "Move candidate search off NumPy exact scan",
            "NumPy exact search grows linearly and is not a production candidate index at this size.",
            "Use persisted FAISS for local single-node deployments or Qdrant/pgvector for service deployments.",
            (
                'pip install "wavemind[indexes]"',
                "wavemind rebuild-index --json",
                "python benchmarks/production_load_benchmark.py --output benchmarks/production_load_results.json",
            ),
            ("docs/BENCHMARK_BRIEF.md",),
        )

    if (
        effective_read_quorum > effective_replication_factor
        or effective_read_fanout > effective_replication_factor
    ):
        add(
            "invalid-read-quorum",
            "architecture_required",
            "Fix invalid read quorum and fanout",
            "Read quorum and read fanout must stay inside the configured replication factor.",
            "Set read quorum and read fanout to values between 1 and the replication factor before production.",
            (
                f"wavemind advise --replication-factor {effective_replication_factor} --read-quorum 1 --read-fanout 1 --json",
            ),
        )
    elif effective_read_fanout < effective_read_quorum:
        add(
            "invalid-read-fanout",
            "architecture_required",
            "Increase read fanout to satisfy read quorum",
            "The cluster cannot reach read quorum when read fanout is smaller than read quorum.",
            "Use read_fanout >= read_quorum, then rerun the local HTTP cluster smoke gate.",
            (
                f"python benchmarks/local_http_cluster_smoke.py --replication-factor {effective_replication_factor} --read-quorum {effective_read_quorum} --read-fanout {effective_read_quorum} --fail-on-slo",
            ),
        )
    elif effective_read_fanout > effective_read_quorum and (
        target_qps >= 100
        or target > SINGLE_NODE_ANN_LIMIT
        or (observed_p99_ms is not None and float(observed_p99_ms) > target_p99)
    ):
        add(
            "bounded-read-fanout",
            "action_required",
            "Bound read fanout for the hot path",
            (
                f"Read fanout {effective_read_fanout} queries more replicas than "
                f"read quorum {effective_read_quorum}, increasing p99 latency under load."
            ),
            "Use quorum-sized read fanout for normal queries and reserve wider fanout for repair or audit workflows.",
            (
                f"python benchmarks/local_http_cluster_smoke.py --replication-factor {effective_replication_factor} --read-quorum {effective_read_quorum} --read-fanout {effective_read_quorum} --fail-on-slo",
                f"python benchmarks/http_cluster_load_benchmark.py --node node-a=https://wm-a.example.com --node node-b=https://wm-b.example.com --node node-c=https://wm-c.example.com --node node-d=https://wm-d.example.com --replication-factor {effective_replication_factor} --read-quorum {effective_read_quorum} --read-fanout {effective_read_quorum} --fail-on-slo",
            ),
            ("docs/BENCHMARK_BRIEF.md",),
        )

    if target > SINGLE_NODE_ANN_LIMIT:
        add(
            "service-index",
            "action_required",
            "Use a service-backed vector index",
            "Large production memory sets need independent index lifecycle, health checks, and rebuild controls.",
            "Keep SQLite/Postgres as source of truth and run Qdrant or pgvector as candidate generation.",
            (
                "wavemind index-health --json",
                "python benchmarks/production_readiness_gate.py --json",
            ),
            ("benchmarks/PRODUCTION_READINESS.md", "docs/OBSERVABILITY.md"),
        )

    if target > SERVICE_INDEX_LIMIT or (namespace_count or 0) >= 1024:
        add(
            "namespace-sharding",
            "architecture_required",
            "Shard memory by namespace",
            "Million-plus memories or thousands of namespaces need bounded per-node storage and repair domains.",
            "Plan namespace placement across nodes, use quorum replication, and schedule anti-entropy repair.",
            (
                "wavemind cluster-plan --namespace-count 4096 --node node-a --node node-b --node node-c --replication-factor 3 --kubernetes --repair-cronjob --json",
                f"wavemind cluster-repair --namespace-count 4096 --node node-a=http://127.0.0.1:8001 --node node-b=http://127.0.0.1:8002 --node node-c=http://127.0.0.1:8003 --replication-factor {effective_replication_factor} --read-quorum {effective_read_quorum} --read-fanout {effective_read_quorum} --json",
            ),
            ("deploy/operator", "deploy/helm/wavemind"),
        )

    if target >= 10_000_000:
        add(
            "capacity-envelope",
            "architecture_required",
            "Run the 10M+ capacity envelope before claiming production scale",
            "Very large deployments need validated placement, p99, recall, rebuild, backup, and restore behavior.",
            "Run sustained external HTTP cluster load and keep the resulting artifact with the benchmark report.",
            (
                "python benchmarks/http_cluster_load_benchmark.py --node node-a=https://wm-a.example.com --node node-b=https://wm-b.example.com --node node-c=https://wm-c.example.com --node node-d=https://wm-d.example.com --replication-factor 3 --fail-on-slo",
            ),
            ("docs/BENCHMARK_BRIEF.md", ".github/workflows/external-http-cluster-load.yml"),
        )
        add(
            "active-active-region-evidence",
            "architecture_required",
            "Verify external active-active regions",
            "Large production deployments need real regional API evidence for convergence, delete propagation, cursor idempotency, and p99 latency.",
            "Run the external HTTP active-active workflow against at least three real API regions before claiming multi-region readiness.",
            (
                'gh workflow run external-http-active-active.yml -f regions="us-east=https://wm-us.example.com,eu-west=https://wm-eu.example.com,ap-south=https://wm-ap.example.com" -f namespace_count=16 -f p99_slo_ms=1500',
            ),
            ("docs/BENCHMARK_BRIEF.md", ".github/workflows/external-http-active-active.yml"),
        )

    if observed_p99_ms is not None and float(observed_p99_ms) > target_p99:
        add(
            "latency-slo",
            "action_required",
            "Reduce p99 query latency",
            f"Observed p99 {float(observed_p99_ms):.2f} ms is above target {target_p99:.2f} ms.",
            "Enable query-vector cache, hot-memory cache, and keep wave-field reranking limited to top candidates.",
            (
                "wavemind cache-prewarm --capacity 2048 --json",
                "wavemind memory-os --capacity 2048 --json",
            ),
            ("docs/OBSERVABILITY.md",),
        )

    expired = _int_stat(stats, "expired_memories", default=0)
    total = max(_int_stat(stats, "total_memories", "active_memories", default=current), 1)
    if expired > 0 and expired / total >= 0.02:
        add(
            "expired-memory-pressure",
            "watch",
            "Purge expired memories",
            f"Expired memories are {expired}/{total}; they add storage and repair pressure.",
            "Run Memory OS maintenance or purge expired records as part of the background job schedule.",
            ("wavemind memory-os --json",),
            ("README.md#memory-os",),
        )

    if deployment_name in {"production", "prod", "staging"}:
        add(
            "production-controls",
            "action_required",
            "Enable production controls",
            "Production deployments need auth, rate limiting, metrics, backup, restore drills, and auditability.",
            "Set API keys, shared Redis rate limiting, OpenTelemetry/Prometheus, and object-store DR drills.",
            (
                "python benchmarks/production_readiness_gate.py --json",
                "wavemind replicated-drill --from s3://bucket/wavemind --to ./restore-test --latest --json",
            ),
            ("benchmarks/PRODUCTION_READINESS.md", "docs/OBSERVABILITY.md"),
        )

    if deployment_name in {"production", "prod"} and (node_count or 0) < effective_replication_factor:
        add(
            "replication-capacity",
            "architecture_required",
            "Add enough nodes for replication",
            f"Replication factor {effective_replication_factor} requires at least {effective_replication_factor} available nodes.",
            "Provision enough API nodes before enabling quorum writes.",
            (
                f"wavemind cluster-plan --namespace-count {namespace_count or 128} --node node-a --node node-b --node node-c --replication-factor {effective_replication_factor} --json",
            ),
        )

    if target_qps >= 100 and deployment_name in {"production", "prod", "staging"}:
        add(
            "load-test",
            "action_required",
            "Run a sustained production load profile",
            f"Target QPS {float(target_qps):.1f} needs p99, failover, delete suppression, and repair evidence.",
            "Run the external HTTP cluster load workflow against real API nodes before publishing the SLO.",
            (
                f"gh workflow run external-http-cluster-load.yml -f nodes=\"node-a=https://wm-a.example.com,node-b=https://wm-b.example.com,node-c=https://wm-c.example.com,node-d=https://wm-d.example.com\" -f replication_factor={effective_replication_factor} -f read_quorum={effective_read_quorum} -f read_fanout={effective_read_quorum} -f fail_on_slo=true",
            ),
            (".github/workflows/external-http-cluster-load.yml",),
        )

    audit_events = _int_stat(stats, "audit_events", default=0)
    if deployment_name in {"production", "prod", "staging"} and audit_events == 0:
        add(
            "query-audit",
            "watch",
            "Collect query audit traffic for Memory OS",
            "Memory OS cache prewarm and priority prediction need observed query patterns.",
            "Enable audited query traffic in staging before tuning prewarm and adaptive forgetting.",
            ("wavemind --audit-queries cache-prewarm --json",),
        )

    if multimodal:
        add(
            "multimodal-payloads",
            "watch",
            "Validate multimodal and structured payload retrieval",
            "Images, audio, tables, and events need typed payload metadata and workload-specific encoders.",
            "Use typed payload helpers and run structured retrieval checks before exposing multimodal claims.",
            (
                "python -m pytest tests/test_multimodal.py -q",
                "python benchmarks/scale_readiness_benchmark.py --output benchmarks/scale_readiness_results.json",
            ),
            ("docs/USE_CASES.md",),
        )

    if not recommendations:
        add(
            "steady-state",
            "ok",
            "Current local architecture is acceptable",
            "The live stats and requested target do not cross a scale or production guardrail.",
            "Keep benchmarks and index-health checks in CI as the dataset grows.",
            ("wavemind index-health --json",),
        )

    status = _max_status([scale_status, *(item.severity for item in recommendations)])
    next_commands = tuple(
        dict.fromkeys(
            command
            for recommendation in recommendations
            for command in recommendation.commands
        )
    )
    production_ready = status in {"ok", "watch"} and deployment_name not in {"production", "prod"}

    return MemoryArchitectureAdvice(
        status=status,
        production_ready=production_ready,
        deployment=deployment_name,
        namespace=namespace,
        current_memories=current,
        target_memories=target,
        index=index,
        vector_dim=vector_dim,
        target_p99_ms=target_p99,
        observed_p99_ms=observed_p99_ms,
        namespace_count=namespace_count,
        node_count=node_count,
        replication_factor=effective_replication_factor,
        read_quorum=effective_read_quorum,
        read_fanout=effective_read_fanout,
        scale_plan=dict(plan_dict),
        recommendations=tuple(recommendations),
        next_commands=next_commands,
    )


def _int_stat(stats: dict[str, Any], *keys: str, default: int = 0) -> int:
    for key in keys:
        if key in stats and stats[key] is not None:
            try:
                return max(0, int(stats[key]))
            except (TypeError, ValueError):
                return default
    return default


def _max_status(statuses: list[str]) -> str:
    return max(statuses, key=lambda value: ADVICE_LEVELS.get(value, 0))
