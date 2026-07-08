from __future__ import annotations

import importlib.util
import math
import os
import shutil
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Mapping, Sequence


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


@dataclass(frozen=True)
class ProductionCostTarget:
    replica_hourly_cost_usd: float = 0.25
    storage_gb_monthly_cost_usd: float = 0.10
    memory_payload_kb: float = 2.0
    vector_dtype_bytes: int = 4
    hours_per_month: float = 730.0

    def __post_init__(self) -> None:
        if self.replica_hourly_cost_usd < 0:
            raise ValueError("replica_hourly_cost_usd cannot be negative")
        if self.storage_gb_monthly_cost_usd < 0:
            raise ValueError("storage_gb_monthly_cost_usd cannot be negative")
        if self.memory_payload_kb < 0:
            raise ValueError("memory_payload_kb cannot be negative")
        if self.vector_dtype_bytes <= 0:
            raise ValueError("vector_dtype_bytes must be positive")
        if self.hours_per_month <= 0:
            raise ValueError("hours_per_month must be positive")

    def as_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True)
class ProductionCostResult:
    engine: str
    cost_status: str
    memory_count: int
    vector_dim: int
    required_replicas: int
    target_qps: float
    replica_hourly_cost_usd: float
    storage_gb_monthly_cost_usd: float
    vector_storage_gb: float
    payload_storage_gb: float
    total_storage_gb: float
    monthly_storage_cost_usd: float
    compute_cost_per_1m_queries_usd: float
    monthly_compute_cost_at_target_qps_usd: float
    monthly_total_cost_at_target_qps_usd: float

    def as_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True)
class ProductionScaleRunProfile:
    name: str
    engine: str
    target_memories: int
    vector_dim: int
    queries: int
    top_k: int
    batch_size: int
    target_recall_at_k: float
    target_p99_ms: float
    target_qps: float
    replicas: int
    autoscaling_max_replicas: int
    capacity_headroom: float
    memory_payload_kb: float
    vector_dtype_bytes: int
    safety_factor: float
    output_artifact: str
    checkpoint_path: str
    required_env: tuple[str, ...]
    command_env: dict[str, str]
    module_requirements: tuple[str, ...]
    index_mode: str
    claim_boundary: str = (
        "plan_only; not a completed latency or recall benchmark until the "
        "output artifact is produced by a real run"
    )

    def as_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True)
class ProductionScaleRunPlan:
    profile: str
    status: str
    claim_boundary: str
    engine: str
    target_memories: int
    vector_dim: int
    queries: int
    top_k: int
    batch_size: int
    target_recall_at_k: float
    target_p99_ms: float
    target_qps: float
    replicas: int
    autoscaling_max_replicas: int
    capacity_headroom: float
    output_artifact: str
    checkpoint_path: str
    command: str
    command_env: dict[str, str]
    required_env: tuple[str, ...]
    missing_env: tuple[str, ...]
    module_requirements: dict[str, bool]
    estimated_index_gb: float
    estimated_transient_runner_gb: float
    estimated_payload_storage_gb: float
    estimated_float_vector_storage_gb: float
    estimated_application_storage_gb: float
    required_local_free_gb: float
    disk_free_gb: float
    index_mode: str
    slo_capacity_envelope: dict[str, object]
    cost_envelope: dict[str, object]
    blockers: tuple[str, ...]
    actions: tuple[str, ...]

    def as_dict(self) -> dict[str, object]:
        return asdict(self)


def _bytes_to_gb(value: float) -> float:
    return float(value) / float(1024**3)


def _round_gb(value: float) -> float:
    return round(float(value), 3)


def _profile_env(name: str, env: Mapping[str, str] | None) -> str | None:
    source = os.environ if env is None else env
    value = source.get(name)
    return str(value) if value else None


def _module_available(name: str) -> bool:
    return importlib.util.find_spec(name) is not None


def _local_disk_free_gb(path: str | os.PathLike[str] = ".") -> float:
    try:
        return _bytes_to_gb(float(shutil.disk_usage(path).free))
    except OSError:
        return 0.0


def production_scale_profile_names() -> tuple[str, ...]:
    return tuple(_PRODUCTION_SCALE_RUN_PROFILES)


def _production_scale_profiles(
    *,
    output_dir: str = "benchmarks",
    state_dir: str = "state",
) -> dict[str, ProductionScaleRunProfile]:
    output_prefix = str(output_dir).strip("/\\") or "benchmarks"
    state_prefix = str(state_dir).strip("/\\") or "state"

    def output(name: str) -> str:
        return f"{output_prefix}/{name}".replace("\\", "/")

    def checkpoint(name: str) -> str:
        return f"{state_prefix}/{name}.checkpoint.json".replace("\\", "/")

    return {
        "qdrant-10m": ProductionScaleRunProfile(
            name="qdrant-10m",
            engine="qdrant-service",
            target_memories=10_000_000,
            vector_dim=128,
            queries=2000,
            top_k=10,
            batch_size=5000,
            target_recall_at_k=0.95,
            target_p99_ms=100.0,
            target_qps=100.0,
            replicas=3,
            autoscaling_max_replicas=24,
            capacity_headroom=0.70,
            memory_payload_kb=2.0,
            vector_dtype_bytes=4,
            safety_factor=1.25,
            output_artifact=output("production_streaming_load_qdrant_10m_results.json"),
            checkpoint_path=checkpoint("qdrant-service-10000000"),
            required_env=("WAVEMIND_QDRANT_URL",),
            command_env={
                "WAVEMIND_QDRANT_URL": "http://qdrant.example:6333",
                "WAVEMIND_QDRANT_UPSERT_BATCH_SIZE": "2000",
                "WAVEMIND_QDRANT_WAIT_AFTER_BUILD_SECONDS": "30",
                "WAVEMIND_QDRANT_WARMUP_QUERIES": "100",
            },
            module_requirements=("qdrant_client",),
            index_mode="remote Qdrant HNSW service; local runner stores generated batches only",
        ),
        "qdrant-sharded-10m": ProductionScaleRunProfile(
            name="qdrant-sharded-10m",
            engine="qdrant-sharded-service",
            target_memories=10_000_000,
            vector_dim=128,
            queries=2000,
            top_k=10,
            batch_size=5000,
            target_recall_at_k=0.95,
            target_p99_ms=100.0,
            target_qps=250.0,
            replicas=4,
            autoscaling_max_replicas=48,
            capacity_headroom=0.70,
            memory_payload_kb=2.0,
            vector_dtype_bytes=4,
            safety_factor=1.25,
            output_artifact=output("production_streaming_load_qdrant_sharded_10m_results.json"),
            checkpoint_path=checkpoint("qdrant-sharded-service-10000000"),
            required_env=("WAVEMIND_QDRANT_URLS",),
            command_env={
                "WAVEMIND_QDRANT_URLS": ",".join(
                    f"http://qdrant-{index}.example:6333" for index in range(4)
                ),
                "WAVEMIND_QDRANT_COLLECTION_PREFIX": "wavemind_streaming_load_10m",
                "WAVEMIND_QDRANT_UPSERT_BATCH_SIZE": "2000",
                "WAVEMIND_QDRANT_FANOUT_WORKERS": "4",
                "WAVEMIND_QDRANT_WAIT_AFTER_BUILD_SECONDS": "30",
                "WAVEMIND_QDRANT_WARMUP_QUERIES": "100",
            },
            module_requirements=("qdrant_client",),
            index_mode="remote horizontally sharded Qdrant services with fanout top-k merge",
        ),
        "pgvector-10m": ProductionScaleRunProfile(
            name="pgvector-10m",
            engine="pgvector-service",
            target_memories=10_000_000,
            vector_dim=128,
            queries=2000,
            top_k=10,
            batch_size=5000,
            target_recall_at_k=0.95,
            target_p99_ms=100.0,
            target_qps=100.0,
            replicas=3,
            autoscaling_max_replicas=24,
            capacity_headroom=0.70,
            memory_payload_kb=2.0,
            vector_dtype_bytes=4,
            safety_factor=1.25,
            output_artifact=output("production_streaming_load_pgvector_10m_results.json"),
            checkpoint_path=checkpoint("pgvector-service-10000000"),
            required_env=("WAVEMIND_PGVECTOR_DSN",),
            command_env={
                "WAVEMIND_PGVECTOR_DSN": "postgresql://user:password@postgres.example:5432/wavemind",
                "WAVEMIND_PGVECTOR_CREATE_HNSW": "1",
                "WAVEMIND_PGVECTOR_EF_SEARCH": "1000",
                "WAVEMIND_PGVECTOR_WARMUP_QUERIES": "100",
            },
            module_requirements=("psycopg",),
            index_mode="remote PostgreSQL/pgvector HNSW service",
        ),
        "faiss-ivfpq-50m": ProductionScaleRunProfile(
            name="faiss-ivfpq-50m",
            engine="faiss-ivfpq-persisted",
            target_memories=50_000_000,
            vector_dim=128,
            queries=2000,
            top_k=10,
            batch_size=5000,
            target_recall_at_k=0.95,
            target_p99_ms=100.0,
            target_qps=100.0,
            replicas=3,
            autoscaling_max_replicas=24,
            capacity_headroom=0.70,
            memory_payload_kb=2.0,
            vector_dtype_bytes=4,
            safety_factor=1.25,
            output_artifact=output("production_streaming_load_ivfpq_50m_results.json"),
            checkpoint_path=checkpoint("faiss-ivfpq-persisted-50000000"),
            required_env=("WAVEMIND_FAISS_IVFPQ_PATH",),
            command_env={
                "WAVEMIND_FAISS_IVFPQ_PATH": "./state/wavemind-faiss-ivfpq-50m.faiss",
                "WAVEMIND_FAISS_IVFPQ_NLIST": "4096",
                "WAVEMIND_FAISS_IVFPQ_M": "16",
                "WAVEMIND_FAISS_IVFPQ_NBITS": "8",
                "WAVEMIND_FAISS_IVFPQ_NPROBE": "1024",
                "WAVEMIND_FAISS_IVFPQ_TRAINING_SIZE": "200000",
            },
            module_requirements=("faiss",),
            index_mode="local persisted FAISS IVF-PQ compressed codes plus int64 ids",
        ),
        "qdrant-sharded-100m": ProductionScaleRunProfile(
            name="qdrant-sharded-100m",
            engine="qdrant-sharded-service",
            target_memories=100_000_000,
            vector_dim=128,
            queries=5000,
            top_k=10,
            batch_size=10000,
            target_recall_at_k=0.95,
            target_p99_ms=100.0,
            target_qps=500.0,
            replicas=8,
            autoscaling_max_replicas=128,
            capacity_headroom=0.70,
            memory_payload_kb=2.0,
            vector_dtype_bytes=4,
            safety_factor=1.25,
            output_artifact=output("production_streaming_load_qdrant_sharded_100m_results.json"),
            checkpoint_path=checkpoint("qdrant-sharded-service-100000000"),
            required_env=("WAVEMIND_QDRANT_URLS",),
            command_env={
                "WAVEMIND_QDRANT_URLS": ",".join(
                    f"http://qdrant-{index}.example:6333" for index in range(16)
                ),
                "WAVEMIND_QDRANT_COLLECTION_PREFIX": "wavemind_streaming_load_100m",
                "WAVEMIND_QDRANT_UPSERT_BATCH_SIZE": "2000",
                "WAVEMIND_QDRANT_FANOUT_WORKERS": "16",
                "WAVEMIND_QDRANT_WAIT_AFTER_BUILD_SECONDS": "60",
                "WAVEMIND_QDRANT_WARMUP_QUERIES": "250",
            },
            module_requirements=("qdrant_client",),
            index_mode="remote horizontally sharded Qdrant services for 100M-memory target",
        ),
    }


_PRODUCTION_SCALE_RUN_PROFILES = _production_scale_profiles()


def _estimate_ivfpq_index_bytes(
    *,
    count: int,
    dim: int,
    vector_dtype_bytes: int,
    env: Mapping[str, str] | None,
) -> tuple[int, int]:
    nlist = int(_profile_env("WAVEMIND_FAISS_IVFPQ_NLIST", env) or 4096)
    pq_m = int(_profile_env("WAVEMIND_FAISS_IVFPQ_M", env) or 16)
    nbits = int(_profile_env("WAVEMIND_FAISS_IVFPQ_NBITS", env) or 8)
    training_size = int(
        _profile_env("WAVEMIND_FAISS_IVFPQ_TRAINING_SIZE", env)
        or max(200_000, nlist * 40)
    )
    code_bytes = int(count) * int(math.ceil((pq_m * nbits) / 8.0))
    id_bytes = int(count) * 8
    centroid_bytes = nlist * int(dim) * int(vector_dtype_bytes)
    training_bytes = training_size * int(dim) * int(vector_dtype_bytes)
    return code_bytes + id_bytes + centroid_bytes, training_bytes


def _production_run_command(profile: ProductionScaleRunProfile) -> str:
    parts = [
        "python",
        "benchmarks/production_streaming_load_benchmark.py",
        "--sizes",
        str(profile.target_memories),
        "--dim",
        str(profile.vector_dim),
        "--queries",
        str(profile.queries),
        "--top-k",
        str(profile.top_k),
        "--batch-size",
        str(profile.batch_size),
        "--engines",
        profile.engine,
        "--target-recall",
        str(profile.target_recall_at_k),
        "--target-p99-ms",
        str(profile.target_p99_ms),
        "--target-qps",
        str(profile.target_qps),
        "--replicas",
        str(profile.replicas),
        "--autoscaling-max-replicas",
        str(profile.autoscaling_max_replicas),
        "--capacity-headroom",
        str(profile.capacity_headroom),
        "--memory-payload-kb",
        str(profile.memory_payload_kb),
        "--vector-dtype-bytes",
        str(profile.vector_dtype_bytes),
        "--output",
        profile.output_artifact,
        "--checkpoint-path",
        profile.checkpoint_path,
    ]
    return " ".join(parts)


def build_production_scale_run_plan(
    *,
    profiles: Sequence[str] | None = None,
    env: Mapping[str, str] | None = None,
    disk_free_gb: float | None = None,
    output_dir: str = "benchmarks",
    state_dir: str = "state",
) -> dict[str, object]:
    """Build reproducible preflight plans for large production load profiles.

    The result is intentionally a plan, not benchmark evidence. It makes large-N
    runs auditable by listing required environment, storage, SLO/cost envelope,
    output artifacts, checkpoint paths, and exact commands before any heavy
    ingest starts.
    """

    available = _production_scale_profiles(output_dir=output_dir, state_dir=state_dir)
    requested = list(profiles or ("all",))
    if not requested or "all" in requested:
        names = list(available)
    else:
        unknown = [name for name in requested if name not in available]
        if unknown:
            raise ValueError(
                "unknown production scale profile(s): "
                + ", ".join(unknown)
                + "; expected one of: "
                + ", ".join(sorted(available))
            )
        names = requested

    effective_disk_free_gb = (
        float(disk_free_gb)
        if disk_free_gb is not None
        else _local_disk_free_gb(".")
    )
    plans: list[ProductionScaleRunPlan] = []
    for name in names:
        profile = available[name]
        vector_bytes = (
            profile.target_memories
            * profile.vector_dim
            * profile.vector_dtype_bytes
        )
        payload_bytes = (
            profile.target_memories * profile.memory_payload_kb * 1024.0
        )
        source_query_bytes = (
            min(profile.queries, profile.target_memories)
            * profile.vector_dim
            * profile.vector_dtype_bytes
        )
        batch_bytes = (
            min(profile.batch_size, profile.target_memories)
            * profile.vector_dim
            * profile.vector_dtype_bytes
        )
        transient_bytes = source_query_bytes + batch_bytes
        if profile.engine == "faiss-ivfpq-persisted":
            index_bytes, training_bytes = _estimate_ivfpq_index_bytes(
                count=profile.target_memories,
                dim=profile.vector_dim,
                vector_dtype_bytes=profile.vector_dtype_bytes,
                env=env,
            )
            transient_bytes += training_bytes
        elif profile.engine == "faiss-persisted":
            index_bytes = vector_bytes + profile.target_memories * 8
        else:
            index_bytes = 0

        required_local_free_gb = max(
            1.0,
            _bytes_to_gb(index_bytes + transient_bytes) * profile.safety_factor,
        )
        missing_env = tuple(
            name for name in profile.required_env if not _profile_env(name, env)
        )
        module_status = {
            name: _module_available(name) for name in profile.module_requirements
        }
        blockers: list[str] = []
        blockers.extend(f"missing_env:{name}" for name in missing_env)
        blockers.extend(
            f"missing_module:{name}"
            for name, ok in module_status.items()
            if not ok
        )
        if effective_disk_free_gb < required_local_free_gb:
            blockers.append("insufficient_local_disk_for_index_and_transient_batches")

        slo_target = ProductionSLOTarget(
            target_recall_at_k=profile.target_recall_at_k,
            target_p99_ms=profile.target_p99_ms,
            target_qps=profile.target_qps,
            replicas=profile.replicas,
            autoscaling_max_replicas=profile.autoscaling_max_replicas,
            capacity_headroom=profile.capacity_headroom,
        )
        slo_envelope = evaluate_production_slo(
            engine=profile.engine,
            recall_at_k=profile.target_recall_at_k,
            avg_latency_ms=max(profile.target_p99_ms / 2.0, 0.001),
            p99_latency_ms=profile.target_p99_ms,
            target=slo_target,
        )
        cost_envelope = estimate_production_cost(
            slo=slo_envelope,
            memory_count=profile.target_memories,
            vector_dim=profile.vector_dim,
            target=ProductionCostTarget(
                memory_payload_kb=profile.memory_payload_kb,
                vector_dtype_bytes=profile.vector_dtype_bytes,
            ),
        )

        actions = [
            "Provision the required service/index backend and set the required environment variables.",
            f"Run `{_production_run_command(profile)}` from the repository root.",
            f"Commit `{profile.output_artifact}` only after the real run completes.",
            "Refresh `wavemind production-evidence-bundle --write-artifacts --json` after committing new evidence.",
        ]
        if profile.engine == "faiss-ivfpq-persisted":
            actions.insert(
                1,
                "Keep the FAISS IVF-PQ checkpoint and index path on durable fast storage.",
            )
        if profile.engine == "qdrant-sharded-service":
            actions.insert(
                1,
                "Verify every Qdrant shard has comparable HNSW/on-disk settings before measuring fanout.",
            )

        plans.append(
            ProductionScaleRunPlan(
                profile=profile.name,
                status="ready" if not blockers else "action_required",
                claim_boundary=profile.claim_boundary,
                engine=profile.engine,
                target_memories=profile.target_memories,
                vector_dim=profile.vector_dim,
                queries=profile.queries,
                top_k=profile.top_k,
                batch_size=profile.batch_size,
                target_recall_at_k=profile.target_recall_at_k,
                target_p99_ms=profile.target_p99_ms,
                target_qps=profile.target_qps,
                replicas=profile.replicas,
                autoscaling_max_replicas=profile.autoscaling_max_replicas,
                capacity_headroom=profile.capacity_headroom,
                output_artifact=profile.output_artifact,
                checkpoint_path=profile.checkpoint_path,
                command=_production_run_command(profile),
                command_env=dict(profile.command_env),
                required_env=profile.required_env,
                missing_env=missing_env,
                module_requirements=module_status,
                estimated_index_gb=_round_gb(_bytes_to_gb(index_bytes)),
                estimated_transient_runner_gb=_round_gb(_bytes_to_gb(transient_bytes)),
                estimated_payload_storage_gb=_round_gb(_bytes_to_gb(payload_bytes)),
                estimated_float_vector_storage_gb=_round_gb(_bytes_to_gb(vector_bytes)),
                estimated_application_storage_gb=_round_gb(
                    _bytes_to_gb(vector_bytes + payload_bytes)
                ),
                required_local_free_gb=_round_gb(required_local_free_gb),
                disk_free_gb=round(float(effective_disk_free_gb), 3),
                index_mode=profile.index_mode,
                slo_capacity_envelope=slo_envelope.as_dict(),
                cost_envelope=cost_envelope.as_dict(),
                blockers=tuple(dict.fromkeys(blockers)),
                actions=tuple(actions),
            )
        )

    ready_count = sum(1 for plan in plans if plan.status == "ready")
    summary = {
        "schema": "wavemind.production_scale_run_plan.v1",
        "generated_at": _utc_now_iso(),
        "overall_status": "ready" if ready_count == len(plans) else "action_required",
        "ready_count": ready_count,
        "action_required_count": len(plans) - ready_count,
        "total_profiles": len(plans),
        "target_memories_total": sum(plan.target_memories for plan in plans),
        "profiles": [plan.profile for plan in plans],
        "claim_boundary": "preflight plans only; real benchmark claims require the output artifacts",
    }
    return {
        "schema": "wavemind.production_scale_run_plan.v1",
        "generated_at": summary["generated_at"],
        "summary": summary,
        "profiles": [plan.as_dict() for plan in plans],
    }


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


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


def estimate_production_cost(
    *,
    slo: ProductionSLOResult,
    memory_count: int,
    vector_dim: int,
    target: ProductionCostTarget | None = None,
) -> ProductionCostResult:
    target = target or ProductionCostTarget()
    memories = max(0, int(memory_count))
    dim = max(1, int(vector_dim))
    required_replicas = max(1, int(slo.required_replicas))

    vector_storage_gb = (
        memories * dim * target.vector_dtype_bytes / float(1024**3)
    )
    payload_storage_gb = (
        memories * target.memory_payload_kb * 1024.0 / float(1024**3)
    )
    total_storage_gb = vector_storage_gb + payload_storage_gb
    monthly_storage_cost = total_storage_gb * target.storage_gb_monthly_cost_usd

    monthly_compute_cost = (
        required_replicas * target.replica_hourly_cost_usd * target.hours_per_month
    )
    monthly_queries_at_target = (
        slo.target_qps * 3600.0 * target.hours_per_month
    )
    compute_cost_per_1m_queries = (
        monthly_compute_cost / max(monthly_queries_at_target / 1_000_000.0, 0.001)
    )
    cost_status = "valid_slo" if slo.status in {"pass", "scale_required"} else "invalid_slo"

    return ProductionCostResult(
        engine=slo.engine,
        cost_status=cost_status,
        memory_count=memories,
        vector_dim=dim,
        required_replicas=required_replicas,
        target_qps=slo.target_qps,
        replica_hourly_cost_usd=target.replica_hourly_cost_usd,
        storage_gb_monthly_cost_usd=target.storage_gb_monthly_cost_usd,
        vector_storage_gb=vector_storage_gb,
        payload_storage_gb=payload_storage_gb,
        total_storage_gb=total_storage_gb,
        monthly_storage_cost_usd=monthly_storage_cost,
        compute_cost_per_1m_queries_usd=compute_cost_per_1m_queries,
        monthly_compute_cost_at_target_qps_usd=monthly_compute_cost,
        monthly_total_cost_at_target_qps_usd=monthly_compute_cost + monthly_storage_cost,
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
