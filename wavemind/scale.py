from __future__ import annotations

from dataclasses import asdict, dataclass
import math


LOCAL_OPTIMAL_LIMIT = 1_000
LOCAL_WATCH_LIMIT = 5_000
SINGLE_NODE_ANN_LIMIT = 50_000
SERVICE_INDEX_LIMIT = 1_000_000
STATUS_LEVELS = {
    "ok": 0,
    "watch": 1,
    "action_required": 2,
    "architecture_required": 3,
}


@dataclass(frozen=True)
class ScalePlan:
    current_memories: int
    target_memories: int
    index: str
    vector_dim: int
    namespace: str | None
    latency_target_ms: float
    tier: str
    status: str
    recommended_index: str
    warnings: tuple[str, ...]
    actions: tuple[str, ...]

    def as_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True)
class ProductionSLOTarget:
    target_recall_at_k: float = 0.95
    target_p99_ms: float = 100.0
    target_qps: float = 100.0
    replicas: int = 3
    autoscaling_max_replicas: int = 24
    capacity_headroom: float = 0.70

    def __post_init__(self) -> None:
        if self.target_recall_at_k <= 0 or self.target_recall_at_k > 1:
            raise ValueError("target_recall_at_k must be in (0, 1]")
        if self.target_p99_ms <= 0:
            raise ValueError("target_p99_ms must be positive")
        if self.target_qps <= 0:
            raise ValueError("target_qps must be positive")
        if self.replicas <= 0:
            raise ValueError("replicas must be positive")
        if self.autoscaling_max_replicas < self.replicas:
            raise ValueError("autoscaling_max_replicas must be >= replicas")
        if self.capacity_headroom <= 0 or self.capacity_headroom > 1:
            raise ValueError("capacity_headroom must be in (0, 1]")

    def as_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True)
class ProductionSLOResult:
    engine: str
    status: str
    target_recall_at_k: float
    target_p99_ms: float
    target_qps: float
    recall_at_k: float
    p99_latency_ms: float
    avg_latency_ms: float
    per_replica_qps_at_headroom: float
    current_replicas: int
    current_capacity_qps: float
    required_replicas: int
    autoscaling_max_replicas: int
    autoscaled_capacity_qps: float
    blocking_reasons: tuple[str, ...]

    def as_dict(self) -> dict[str, object]:
        return asdict(self)


def evaluate_production_slo(
    *,
    engine: str,
    recall_at_k: float,
    avg_latency_ms: float,
    p99_latency_ms: float | None = None,
    p95_latency_ms: float | None = None,
    target: ProductionSLOTarget | None = None,
) -> ProductionSLOResult:
    target = target or ProductionSLOTarget()
    avg_latency = max(float(avg_latency_ms), 0.001)
    p99_latency = float(
        p99_latency_ms
        if p99_latency_ms is not None
        else p95_latency_ms
        if p95_latency_ms is not None
        else avg_latency
    )
    recall = float(recall_at_k)

    per_replica_qps = (1000.0 / avg_latency) * target.capacity_headroom
    current_capacity_qps = per_replica_qps * target.replicas
    autoscaled_capacity_qps = per_replica_qps * target.autoscaling_max_replicas
    required_replicas = max(1, math.ceil(target.target_qps / per_replica_qps))

    blocking_reasons: list[str] = []
    if recall < target.target_recall_at_k:
        blocking_reasons.append("recall_below_target")
    if p99_latency > target.target_p99_ms:
        blocking_reasons.append("p99_above_target")
    if required_replicas > target.autoscaling_max_replicas:
        blocking_reasons.append("autoscaling_capacity_below_target_qps")

    if blocking_reasons:
        status = "fail"
    elif required_replicas > target.replicas:
        status = "scale_required"
    else:
        status = "pass"

    return ProductionSLOResult(
        engine=engine,
        status=status,
        target_recall_at_k=target.target_recall_at_k,
        target_p99_ms=target.target_p99_ms,
        target_qps=target.target_qps,
        recall_at_k=recall,
        p99_latency_ms=p99_latency,
        avg_latency_ms=avg_latency,
        per_replica_qps_at_headroom=per_replica_qps,
        current_replicas=target.replicas,
        current_capacity_qps=current_capacity_qps,
        required_replicas=required_replicas,
        autoscaling_max_replicas=target.autoscaling_max_replicas,
        autoscaled_capacity_qps=autoscaled_capacity_qps,
        blocking_reasons=tuple(blocking_reasons),
    )


def normalize_index_name(index: str | None) -> str:
    return (index or "numpy").lower().replace("_", "-")


def scale_status_meets_or_exceeds(status: str, threshold: str) -> bool:
    if threshold not in STATUS_LEVELS:
        raise ValueError(
            "threshold must be one of: "
            + ", ".join(sorted(STATUS_LEVELS, key=STATUS_LEVELS.get))
        )
    return STATUS_LEVELS.get(status, 0) >= STATUS_LEVELS[threshold]


def build_scale_plan(
    *,
    current_memories: int,
    target_memories: int | None = None,
    index: str = "numpy",
    vector_dim: int = 384,
    namespace: str | None = None,
    latency_target_ms: float = 20.0,
) -> ScalePlan:
    current = max(0, int(current_memories))
    target = max(current, int(target_memories if target_memories is not None else current))
    normalized_index = normalize_index_name(index)
    warnings: list[str] = []
    actions: list[str] = []

    if target <= LOCAL_OPTIMAL_LIMIT:
        tier = "small"
        status = "ok"
        recommended_index = "numpy"
        actions.append("Use SQLite plus the default NumPy exact index for simplest local operation.")
        actions.append("Keep namespaces explicit and run `wavemind index-health --json` after imports.")
    elif target <= LOCAL_WATCH_LIMIT:
        tier = "medium"
        status = "watch"
        recommended_index = "numpy or faiss-persisted"
        warnings.append(
            "NumPy exact search is still acceptable here, but latency grows linearly."
        )
        actions.append("Benchmark your real queries before publishing latency claims.")
        actions.append(
            "Use `--index faiss-persisted` if p95 latency matters more than a zero-dependency setup."
        )
    elif target <= SINGLE_NODE_ANN_LIMIT:
        tier = "large-local"
        status = "action_required"
        recommended_index = "faiss-persisted or qdrant"
        if normalized_index in {"numpy", "exact"}:
            warnings.append(
                "Do not use NumPy exact search as the primary candidate index at this size."
            )
        else:
            warnings.append(
                "At this size, validate recall, p95 latency, rebuild time, and index-health on real data."
            )
        actions.append('Install index extras with `pip install "wavemind[indexes]"`.')
        actions.append(
            "For local single-node deployments, set `WAVEMIND_FAISS_PATH` and use `--index faiss-persisted`."
        )
        actions.append(
            "For service deployments, run Qdrant as a service and use `--index qdrant`."
        )
        actions.append("Run `wavemind rebuild-index` and then `wavemind index-health --json`.")
    elif target <= SERVICE_INDEX_LIMIT:
        tier = "production-service"
        status = "action_required"
        recommended_index = "qdrant service or pgvector HNSW"
        warnings.append(
            "This should be treated as a service-backed deployment, not a local NumPy deployment."
        )
        actions.append("Keep SQLite or Postgres as the source of truth and use an external candidate index.")
        actions.append("Shard by namespace, tenant, user, project, or agent before the database becomes hot.")
        actions.append("Measure recall@k, p95, and rebuild time on production-like hardware.")
        actions.append("Keep WaveMind as a top-k reranker; do not full-scan the field over every memory.")
    else:
        tier = "million-plus"
        status = "architecture_required"
        recommended_index = "external vector database plus namespace sharding"
        warnings.append(
            "WaveMind should be the memory-policy layer here, not the primary large-document vector database."
        )
        actions.append("Use Qdrant, pgvector, Pinecone, Weaviate, Milvus, or a similar service for candidate search.")
        actions.append("Partition memory by tenant/namespace and define retention policy before import.")
        actions.append("Run load tests for recall, p95, p99, rebuild time, backup, and restore drills.")

    if normalized_index in {"numpy", "exact"} and target > LOCAL_WATCH_LIMIT:
        warnings.append(
            "Current index is NumPy exact; switch to an explicit ANN or service backend before production growth."
        )
    if normalized_index in {"annoy", "quantized", "int8"} and target > LOCAL_WATCH_LIMIT:
        warnings.append(
            "Current checked-in curves show recall or latency tradeoffs for this backend; validate before production."
        )
    if normalized_index in {"faiss", "faiss-persisted", "persisted-faiss"}:
        actions.append("Persist and validate the FAISS id map; rebuild when source-of-truth ids drift.")
    if normalized_index in {"qdrant", "pgvector", "postgres", "postgresql"}:
        actions.append("Expose index-health, metrics, backup, and restore checks in deployment runbooks.")
    if latency_target_ms < 20.0 and target > LOCAL_OPTIMAL_LIMIT:
        warnings.append(
            "Latency target is aggressive for dynamic memory; benchmark candidate search and reranking separately."
        )

    return ScalePlan(
        current_memories=current,
        target_memories=target,
        index=normalized_index,
        vector_dim=int(vector_dim),
        namespace=namespace,
        latency_target_ms=float(latency_target_ms),
        tier=tier,
        status=status,
        recommended_index=recommended_index,
        warnings=tuple(dict.fromkeys(warnings)),
        actions=tuple(dict.fromkeys(actions)),
    )
