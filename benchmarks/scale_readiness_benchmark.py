from __future__ import annotations

import argparse
import fnmatch
import json
import logging
import socket
import statistics
import subprocess
import sys
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from io import BytesIO
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import ProxyHandler, Request, build_opener

import numpy as np

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) in sys.path:
    sys.path.remove(str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT))

from wavemind import (
    CachePrewarmWorker,
    ClusterNode,
    CrossModalMemoryLayer,
    ActiveActiveSyncWorker,
    DistributedRepairWorker,
    DistributedShardedWaveMind,
    FieldStateCRDT,
    HashingTextEncoder,
    HTTPActiveActiveSyncWorker,
    HTTPNamespaceShardClient,
    HotMemoryCache,
    KnowledgeGraphMemoryLayer,
    MemoryOSScheduler,
    MemoryOSWorker,
    PrecomputedCrossModalEncoder,
    QueryVectorCache,
    QueryResult,
    RedisHotMemoryCache,
    RedisMemoryOSLock,
    RedisQueryVectorCache,
    ReplicatedObjectStoreDrillWorker,
    ReplicatedWaveMind,
    ReplicatedSnapshotWorker,
    S3AssetStore,
    S3SnapshotStore,
    SQLiteMemoryStore,
    TemporalEventMemoryLayer,
    WaveMind,
    asset3d_payload,
    audio_payload,
    build_cluster_autoscale_plan,
    build_cluster_plan,
    check_cross_modal_encoder_health,
    event_payload,
    graph_payload,
    image_payload,
    kubernetes_resource_path,
    operator_bundle,
    operator_reconcile,
    operator_status,
    query_with_cache,
    query_with_vector_cache,
    remember_payload,
    run_control_plane_consensus_profile,
    serverless_sample_bundle,
    sync_namespace_delta,
    table_payload,
    video_payload,
    ServerlessObservedTelemetry,
    ServerlessWorkloadTarget,
    WaveMindClusterSpec,
    WaveMindServerlessSpec,
    audit_field_state_watermarks,
    stable_memory_key,
    validate_precomputed_cross_modal_contract,
)
from wavemind.api import RedisRateLimiter, create_app

logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("wavemind.api").setLevel(logging.WARNING)


SERVERLESS_LOOPBACK_OBSERVED_TELEMETRY_PATH = (
    PROJECT_ROOT / "deploy" / "serverless" / "observed-telemetry.loopback.json"
)
SERVERLESS_REMOTE_OBSERVED_TELEMETRY_PATH = (
    PROJECT_ROOT / "deploy" / "serverless" / "observed-telemetry.remote.json"
)


def serverless_observed_telemetry_path() -> Path:
    if SERVERLESS_REMOTE_OBSERVED_TELEMETRY_PATH.exists():
        return SERVERLESS_REMOTE_OBSERVED_TELEMETRY_PATH
    return SERVERLESS_LOOPBACK_OBSERVED_TELEMETRY_PATH


def display_path(path: Path) -> str:
    try:
        return str(path.relative_to(PROJECT_ROOT))
    except ValueError:
        return str(path)


class InMemoryS3Client:
    def __init__(self):
        self.objects: dict[tuple[str, str], dict[str, object]] = {}
        self.counter = 0

    def upload_file(self, filename: str, bucket: str, key: str, ExtraArgs=None):
        self.counter += 1
        self.objects[(bucket, key)] = {
            "Body": Path(filename).read_bytes(),
            "ContentType": (ExtraArgs or {}).get("ContentType"),
            "Metadata": dict((ExtraArgs or {}).get("Metadata") or {}),
            "LastModified": f"2026-01-01T00:00:{self.counter:02d}Z",
        }

    def put_object(self, Bucket: str, Key: str, Body, ContentType=None, Metadata=None):
        self.counter += 1
        payload = Body.read() if hasattr(Body, "read") else Body
        self.objects[(Bucket, Key)] = {
            "Body": bytes(payload),
            "ContentType": ContentType,
            "Metadata": dict(Metadata or {}),
            "LastModified": f"2026-01-01T00:00:{self.counter:02d}Z",
        }

    def head_object(self, Bucket: str, Key: str) -> dict[str, object]:
        payload = self.objects[(Bucket, Key)]
        body = payload["Body"]
        return {
            "ContentLength": len(body),
            "Metadata": dict(payload["Metadata"]),
            "ContentType": payload.get("ContentType"),
            "ETag": '"benchmark-etag"',
        }

    def list_objects_v2(
        self,
        Bucket: str,
        Prefix: str = "",
        ContinuationToken: str | None = None,
    ) -> dict[str, object]:
        contents = []
        for (bucket, key), payload in self.objects.items():
            if bucket == Bucket and key.startswith(Prefix):
                body = payload["Body"]
                contents.append(
                    {
                        "Key": key,
                        "Size": len(body),
                        "LastModified": payload["LastModified"],
                        "ETag": '"benchmark-etag"',
                    }
                )
        return {"Contents": sorted(contents, key=lambda item: item["Key"])}

    def delete_objects(self, Bucket: str, Delete: dict[str, object]) -> dict[str, object]:
        deleted = []
        for item in Delete["Objects"]:
            key = item["Key"]
            self.objects.pop((Bucket, key), None)
            deleted.append({"Key": key})
        return {"Deleted": deleted}

    def get_object(self, Bucket: str, Key: str) -> dict[str, object]:
        return {"Body": BytesIO(self.objects[(Bucket, Key)]["Body"])}


class RedisLikeCacheClient:
    """Small Redis-compatible client for deterministic shared-cache profiles."""

    def __init__(self):
        self.items: dict[str, str] = {}
        self.expirations: dict[str, int | None] = {}

    def get(self, key: str):
        return self.items.get(key)

    def set(self, key: str, value: str, ex: int | None = None, nx: bool = False):
        if nx and key in self.items:
            return False
        self.items[key] = value
        self.expirations[key] = ex
        return True

    def scan_iter(self, match: str):
        for key in list(self.items):
            if fnmatch.fnmatch(key, match):
                yield key

    def delete(self, *keys: str):
        for key in keys:
            self.items.pop(key, None)
            self.expirations.pop(key, None)

    def incr(self, key: str):
        self.items[key] = str(int(self.items.get(key, "0")) + 1)
        return int(self.items[key])

    def expire(self, key: str, seconds: int):
        self.expirations[key] = int(seconds)
        return True


class MemoryOSEncoder:
    vector_dim = 4

    def encode_vector(self, text: str) -> np.ndarray:
        lowered = text.lower()
        if any(token in lowered for token in ("rust", "compiler", "systems", "programming")):
            return self._unit([1.0, 0.0, 0.0, 0.0])
        if any(token in lowered for token in ("budget", "recall", "prewarm")):
            return self._unit([0.0, 1.0, 0.0, 0.0])
        return self._unit([0.0, 0.0, 1.0, 0.0])

    def _unit(self, values: list[float]) -> np.ndarray:
        vector = np.asarray(values, dtype=np.float32)
        return vector / (float(np.linalg.norm(vector)) + 1e-9)


class CountingMemoryOSEncoder(MemoryOSEncoder):
    def __init__(self):
        self.calls = 0

    def encode_vector(self, text: str) -> np.ndarray:
        self.calls += 1
        return super().encode_vector(text)


class LocalWaveMindServiceClient:
    def __init__(self, root: Path):
        self.root = root
        self.minds: dict[str, WaveMind] = {}

    def remember(
        self,
        address: str,
        *,
        text: str,
        namespace: str,
        tags: tuple[str, ...] = (),
        ttl_seconds: float | None = None,
        metadata: dict[str, object] | None = None,
        priority: float = 1.0,
    ) -> int:
        return self._mind(address).remember(
            text,
            namespace=namespace,
            tags=tags,
            ttl_seconds=ttl_seconds,
            metadata=metadata,
            priority=priority,
        )

    def query(
        self,
        address: str,
        *,
        text: str,
        namespace: str,
        top_k: int = 3,
        tags: tuple[str, ...] = (),
        min_score: float | None = None,
    ) -> list[QueryResult]:
        return self._mind(address).query(
            text,
            namespace=namespace,
            top_k=top_k,
            tags=tags,
            min_score=min_score,
        )

    def forget(
        self,
        address: str,
        *,
        namespace: str,
        id: int | None = None,
        text: str | None = None,
    ) -> int:
        return self._mind(address).forget(
            id=id,
            text=text,
            namespace=namespace,
        )

    def forget_batch(
        self,
        address: str,
        *,
        items: list[dict[str, object]],
    ) -> dict[str, object]:
        response_items = []
        for index, item in enumerate(items):
            response_items.append(
                {
                    "index": index,
                    "namespace": item.get("namespace", "default"),
                    "deleted": self.forget(
                        address,
                        namespace=str(item.get("namespace", "default")),
                        id=item.get("id"),  # type: ignore[arg-type]
                        text=item.get("text"),  # type: ignore[arg-type]
                    ),
                }
            )
        return {
            "count": len(response_items),
            "deleted": sum(int(item["deleted"]) for item in response_items),
            "items": response_items,
        }

    def export_namespace(
        self,
        address: str,
        *,
        namespace: str,
        limit: int = 1000,
        include_expired: bool = False,
        tags: tuple[str, ...] = (),
    ) -> list[dict[str, object]]:
        records = self._mind(address).store.list(
            namespace=namespace,
            include_expired=include_expired,
            tags=tags,
        )[:limit]
        return [
            {
                "id": record.id,
                "text": record.text,
                "namespace": record.namespace,
                "tags": list(record.tags),
                "metadata": record.metadata,
                "created_at": record.created_at,
                "updated_at": record.updated_at,
                "expires_at": record.expires_at,
                "priority": record.priority,
                "access_count": record.access_count,
            }
            for record in records
        ]

    def export_namespace_state(
        self,
        address: str,
        *,
        namespace: str,
        limit: int = 1000,
        include_expired: bool = False,
        tags: tuple[str, ...] = (),
        include_tombstones: bool = True,
    ) -> dict[str, object]:
        tombstones = []
        if include_tombstones:
            tombstones = [
                {
                    "record_keys": list(event.metadata.get("record_keys", [])),
                    "texts": list(event.metadata.get("texts", [])),
                }
                for event in self._mind(address).audit_events(
                    namespace=namespace,
                    action="distributed_tombstone",
                    limit=10_000,
                )
            ]
        return {
            "records": self.export_namespace(
                address,
                namespace=namespace,
                limit=limit,
                include_expired=include_expired,
                tags=tags,
            ),
            "tombstones": tombstones,
        }

    def log_tombstone(
        self,
        address: str,
        *,
        namespace: str,
        record_keys: tuple[str, ...] = (),
        texts: tuple[str, ...] = (),
    ) -> int:
        return self._log_tombstone_event(
            address,
            namespace=namespace,
            record_keys=record_keys,
            texts=texts,
        )

    def _log_tombstone_event(
        self,
        address: str,
        *,
        namespace: str,
        record_keys: tuple[str, ...] = (),
        texts: tuple[str, ...] = (),
    ) -> int:
        return self._mind(address).store.log_audit_event(
            "distributed_tombstone",
            namespace=namespace,
            metadata={
                "record_keys": sorted(record_keys),
                "texts": sorted(texts),
            },
        )

    def log_tombstone_batch(
        self,
        address: str,
        *,
        items: list[dict[str, object]],
    ) -> dict[str, object]:
        response_items = []
        for index, item in enumerate(items):
            response_items.append(
                {
                    "index": index,
                    "namespace": item["namespace"],
                    "id": self._log_tombstone_event(
                        address,
                        namespace=str(item["namespace"]),
                        record_keys=tuple(item.get("record_keys", ())),  # type: ignore[arg-type]
                        texts=tuple(item.get("texts", ())),  # type: ignore[arg-type]
                    ),
                }
            )
        return {"count": len(response_items), "items": response_items}

    def close(self) -> None:
        for mind in self.minds.values():
            mind.close()
        self.minds.clear()

    def _mind(self, address: str) -> WaveMind:
        mind = self.minds.get(address)
        if mind is None:
            mind = WaveMind(
                db_path=self.root / f"{address}.sqlite3",
                width=16,
                height=16,
                layers=1,
                encoder=HashingTextEncoder(vector_dim=64),
            )
            self.minds[address] = mind
        return mind


class FastAPIReplicatedRegionClient:
    """Service-boundary client for benchmarked active-active region sync.

    This keeps the scale-readiness profile CI-friendly while still exercising
    FastAPI request validation and response serialization for namespace deltas.
    """

    def __init__(self, regions: dict[str, ReplicatedWaveMind]):
        from fastapi.testclient import TestClient

        self.clients = {
            address.rstrip("/"): TestClient(create_app(mind=memory))
            for address, memory in regions.items()
        }
        self.export_calls = 0
        self.import_calls = 0

    def export_namespace_delta(
        self,
        address: str,
        *,
        namespace: str,
        since: float | None = None,
        limit: int | None = None,
    ) -> dict[str, object]:
        self.export_calls += 1
        response = self.clients[address.rstrip("/")].post(
            "/namespace-delta/export",
            json={"namespace": namespace, "since": since, "limit": limit},
        )
        response.raise_for_status()
        return response.json()

    def import_namespace_delta(
        self,
        address: str,
        *,
        delta: dict[str, object],
        namespace: str | None = None,
    ) -> dict[str, object]:
        self.import_calls += 1
        response = self.clients[address.rstrip("/")].post(
            "/namespace-delta/import",
            json={"delta": delta, "namespace": namespace},
        )
        response.raise_for_status()
        return response.json()

    def close(self) -> None:
        for client in self.clients.values():
            client.close()


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _start_api_node(root: Path, node_id: str) -> dict[str, object]:
    port = _free_port()
    db_path = root / f"{node_id}.sqlite3"
    process = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "wavemind",
            "--db",
            str(db_path),
            "--score-threshold",
            "0.05",
            "serve",
            "--host",
            "127.0.0.1",
            "--port",
            str(port),
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
    )
    node = {
        "id": node_id,
        "address": f"http://127.0.0.1:{port}",
        "zone": f"zone-{node_id}",
        "process": process,
    }
    _wait_api_node_ready(node)
    return node


def _wait_api_node_ready(node: dict[str, object]) -> None:
    opener = build_opener(ProxyHandler({}))
    deadline = time.time() + 20.0
    last_error: object = None
    process = node["process"]
    assert isinstance(process, subprocess.Popen)
    address = str(node["address"])
    while time.time() < deadline:
        if process.poll() is not None:
            stdout, stderr = process.communicate(timeout=1)
            raise RuntimeError(
                f"{node['id']} exited before readiness with {process.returncode}\n"
                f"STDOUT:\n{stdout}\nSTDERR:\n{stderr}"
            )
        try:
            request = Request(f"{address}/stats", method="GET")
            with opener.open(request, timeout=1) as response:
                if response.status == 200:
                    return
        except (HTTPError, URLError, TimeoutError) as exc:
            last_error = exc
        time.sleep(0.2)
    raise RuntimeError(f"{node['id']} did not become ready: {last_error}")


def _stop_api_nodes(nodes: list[dict[str, object]]) -> None:
    processes = [
        node["process"]
        for node in nodes
        if isinstance(node.get("process"), subprocess.Popen)
    ]
    for process in processes:
        if process.poll() is None:
            process.kill()
    for process in processes:
        try:
            process.communicate(timeout=5)
        except subprocess.TimeoutExpired:
            process.terminate()
            process.communicate(timeout=5)


def percentile(values: list[float], pct: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, int(round((pct / 100.0) * (len(ordered) - 1)))))
    return ordered[index]


def run_cluster_profile(
    *,
    namespace_count: int,
    node_count: int,
    replication_factor: int,
    simulated_memories: int,
) -> dict[str, object]:
    namespaces = [f"tenant:{index}" for index in range(namespace_count)]
    nodes = [
        ClusterNode(
            id=f"node-{index}",
            address=f"wavemind-{index}.wavemind.svc.cluster.local:8000",
            zone=f"zone-{index % 3}",
        )
        for index in range(node_count)
    ]
    started = time.perf_counter()
    plan = build_cluster_plan(
        namespaces=namespaces,
        nodes=nodes,
        replication_factor=replication_factor,
    )
    placement_ms = (time.perf_counter() - started) * 1000.0
    loads = list(plan.node_load.values())
    primary_loads = list(plan.primary_load.values())
    losses = [plan.simulate_node_loss(node.id) for node in nodes]
    min_availability = min(float(loss["availability_ratio"]) for loss in losses)
    quorum = plan.quorum_report()
    repair_cronjob = plan.kubernetes_repair_cronjob(api_key_secret="wavemind-api-key")
    repair_container = repair_cronjob["spec"]["jobTemplate"]["spec"]["template"]["spec"]["containers"][0]
    repair_args = list(repair_container["args"])
    return {
        "engine": "WaveMind cluster planner",
        "simulated_memories": simulated_memories,
        "namespaces": namespace_count,
        "nodes": node_count,
        "replication_factor": replication_factor,
        "placement_ms": placement_ms,
        "max_replica_load": max(loads) if loads else 0,
        "min_replica_load": min(loads) if loads else 0,
        "replica_load_stdev": statistics.pstdev(loads) if len(loads) > 1 else 0.0,
        "max_primary_load": max(primary_loads) if primary_loads else 0,
        "min_primary_load": min(primary_loads) if primary_loads else 0,
        "node_loss_min_availability": min_availability,
        "zone_loss_min_availability": quorum["zone_loss_min_availability"],
        "read_quorum": quorum["read_quorum"],
        "write_quorum": quorum["write_quorum"],
        "kubernetes_manifest_kind": plan.kubernetes_manifest()["kind"],
        "kubernetes_repair_cronjob_kind": repair_cronjob["kind"],
        "kubernetes_repair_cronjob_namespaces": repair_args.count("--namespace"),
    }


def run_cluster_autoscale_profile(
    *,
    namespace_count: int,
    node_count: int,
    replication_factor: int,
    target_memories: int,
) -> dict[str, object]:
    namespaces = [f"tenant:{index}" for index in range(namespace_count)]
    nodes = [
        ClusterNode(
            id=f"node-{index}",
            address=f"https://wavemind-{index}.internal",
            zone=f"zone-{index % 3}",
        )
        for index in range(node_count)
    ]
    started = time.perf_counter()
    plan = build_cluster_autoscale_plan(
        namespaces=namespaces,
        nodes=nodes,
        replication_factor=max(3, replication_factor),
        target_memories=target_memories,
        max_memories_per_node=1_000_000,
        headroom=0.70,
        node_prefix="wavemind",
        address_template="https://{node_id}.internal",
        zones=("zone-0", "zone-1", "zone-2"),
        max_moves=namespace_count,
    )
    rebalance = plan.rebalance_plan(
        batch_size=50,
        max_node_moves_per_batch=50,
    )
    plan_ms = (time.perf_counter() - started) * 1000.0
    return {
        "engine": "WaveMind cluster autoscaler",
        "status": plan.status,
        "namespace_count": namespace_count,
        "current_nodes": len(plan.current_nodes),
        "required_nodes": plan.required_nodes,
        "additional_nodes": plan.additional_nodes,
        "replication_factor": plan.replication_factor,
        "target_memories": plan.target_memories,
        "max_memories_per_node": plan.max_memories_per_node,
        "headroom": plan.headroom,
        "current_max_node_memories": plan.current_max_node_memories,
        "target_max_node_memories": plan.target_max_node_memories,
        "target_within_headroom": plan.target_max_node_memories
        <= int(plan.max_memories_per_node * plan.headroom),
        "move_sample": len(plan.moves),
        "omitted_moves": plan.omitted_moves,
        "has_scale_action": any("Add" in action for action in plan.actions),
        "rebalance_status": rebalance.status,
        "rebalance_full_plan": rebalance.full_plan,
        "rebalance_batches": len(rebalance.batches),
        "rebalance_move_count": rebalance.move_count,
        "rebalance_write_quorum": rebalance.write_quorum,
        "rebalance_read_quorum": rebalance.read_quorum,
        "rebalance_estimated_steps": rebalance.estimated_steps,
        "rebalance_max_batch_node_pressure": rebalance.max_batch_node_pressure,
        "rebalance_all_batches_checkpointed": all(
            batch.requires_checkpoint for batch in rebalance.batches
        ),
        "rebalance_all_batches_repaired": all(batch.requires_repair for batch in rebalance.batches),
        "rebalance_all_batches_validated": all(
            batch.requires_validation for batch in rebalance.batches
        ),
        "plan_ms": plan_ms,
    }


def run_operator_profile(
    *,
    namespace_count: int,
    node_count: int,
    replication_factor: int,
    target_memories: int,
) -> dict[str, object]:
    spec = WaveMindClusterSpec(
        name="wavemind",
        namespace="wavemind-system",
        image="ghcr.io/caspiang/wavemind:latest",
        replicas=node_count,
        replication_factor=replication_factor,
        namespace_count=namespace_count,
        auth_secret="wavemind-api-key",
        redis_url="redis://redis.wavemind-system.svc.cluster.local:6379/0",
        autoscaling_enabled=True,
        autoscaling_min_replicas=node_count,
        autoscaling_max_replicas=max(node_count * 4, node_count + 1),
        autoscaling_target_cpu_utilization=70,
        autoscaling_target_memory_utilization=80,
        autoscaling_target_memories=target_memories,
        autoscaling_max_memories_per_node=1_000_000,
        autoscaling_headroom=0.70,
        memory_os_enabled=True,
        memory_os_cache_mode="auto",
        memory_os_target_memories=target_memories,
        memory_os_run_on_all_replicas=False,
    )
    bundle = operator_bundle(namespace="wavemind-system", sample=spec)
    custom_resource = spec.custom_resource()
    reconciled = operator_reconcile(custom_resource)
    status = operator_status(
        custom_resource,
        observed={
            "readyReplicas": spec.replicas,
            "currentReplicas": spec.replicas,
            "currentMemories": target_memories,
            "degradedNodes": 0,
            "unavailableNodes": 0,
            "hpaDesiredReplicas": spec.replicas,
        },
    )
    conditions = {
        condition["type"]: condition["status"]
        for condition in status["conditions"]
    }
    resources = list(reconciled["items"])
    kinds = [str(resource["kind"]) for resource in resources]
    names = [str(resource["metadata"]["name"]) for resource in resources]
    paths = [kubernetes_resource_path(resource).api_path for resource in resources]
    cronjobs = {
        str(resource["metadata"]["name"]): resource
        for resource in resources
        if resource["kind"] == "CronJob"
    }
    repair_cronjob = cronjobs[f"{spec.name}-cluster-repair"]
    memory_os_cronjob = cronjobs[f"{spec.name}-memory-os"]
    cronjob_container = repair_cronjob["spec"]["jobTemplate"]["spec"]["template"]["spec"]["containers"][0]
    memory_os_container = memory_os_cronjob["spec"]["jobTemplate"]["spec"]["template"]["spec"]["containers"][0]
    memory_os_script = str(memory_os_container["args"][0])
    hpa = next(resource for resource in resources if resource["kind"] == "HorizontalPodAutoscaler")
    statefulset = next(resource for resource in resources if resource["kind"] == "StatefulSet")
    rebalance_configmap = next(resource for resource in resources if resource["kind"] == "ConfigMap")
    capacity_annotations = dict(statefulset["metadata"].get("annotations") or {})
    rebalance_annotations = dict(rebalance_configmap["metadata"].get("annotations") or {})
    rebalance_summary = json.loads(rebalance_configmap["data"]["rebalance-summary.json"])
    rebalance_preview = json.loads(rebalance_configmap["data"]["rebalance-batches-preview.json"])
    return {
        "engine": "WaveMind Kubernetes operator",
        "bundle_resources": len(bundle["items"]),
        "bundle_has_crd": any(item["kind"] == "CustomResourceDefinition" for item in bundle["items"]),
        "bundle_has_operator_deployment": any(item["kind"] == "Deployment" for item in bundle["items"]),
        "sample_kind": spec.custom_resource()["kind"],
        "reconciled_resources": len(resources),
        "has_service": "Service" in kinds,
        "has_statefulset": "StatefulSet" in kinds,
        "has_hpa": "HorizontalPodAutoscaler" in kinds,
        "has_rebalance_configmap": "ConfigMap" in kinds,
        "has_repair_cronjob": "CronJob" in kinds,
        "has_memory_os_cronjob": f"{spec.name}-memory-os" in names,
        "headless_service": spec.headless_service_name in names,
        "autoscaling_min_replicas": hpa["spec"]["minReplicas"],
        "autoscaling_max_replicas": hpa["spec"]["maxReplicas"],
        "statefulset_replicas": statefulset["spec"]["replicas"],
        "capacity_target_memories": target_memories,
        "capacity_required_replicas": int(
            capacity_annotations.get("memory.wavemind.ai/capacity-required-replicas", 0)
        ),
        "capacity_target_max_node_memories": int(
            capacity_annotations.get("memory.wavemind.ai/capacity-target-max-node-memories", 0)
        ),
        "capacity_headroom": float(
            capacity_annotations.get("memory.wavemind.ai/capacity-headroom", 0)
        ),
        "capacity_annotations": capacity_annotations,
        "rebalance_configmap_name": rebalance_configmap["metadata"]["name"],
        "rebalance_status": rebalance_summary["status"],
        "rebalance_full_plan": rebalance_summary["full_plan"],
        "rebalance_move_count": rebalance_summary["move_count"],
        "rebalance_batches": rebalance_summary["batch_count"],
        "rebalance_preview_batches": rebalance_summary["preview_batches"],
        "rebalance_preview_batch_count": len(rebalance_preview),
        "rebalance_write_quorum": rebalance_summary["write_quorum"],
        "rebalance_estimated_steps": rebalance_summary["estimated_steps"],
        "rebalance_checkpoint_required": all(
            batch["requires_checkpoint"] for batch in rebalance_preview
        ),
        "rebalance_repair_required": all(batch["requires_repair"] for batch in rebalance_preview),
        "rebalance_validation_required": all(
            batch["requires_validation"] for batch in rebalance_preview
        ),
        "rebalance_annotations": rebalance_annotations,
        "status_ready": status["ready"],
        "status_phase": status["phase"],
        "status_ready_replicas": status["readyReplicas"],
        "status_desired_replicas": status["desiredReplicas"],
        "status_required_replicas": status["capacity"]["requiredReplicas"],
        "status_capacity_within_headroom": status["capacity"]["withinHeadroom"],
        "status_rebalance_ready": status["rebalance"]["ready"],
        "status_rebalance_full_plan": status["rebalance"]["fullPlan"],
        "status_rebalance_move_count": status["rebalance"]["moveCount"],
        "status_rebalance_batches": status["rebalance"]["batchCount"],
        "status_rebalance_configmap": status["rebalance"]["configMapName"],
        "status_degraded_nodes": status["degradedNodes"],
        "status_unavailable_nodes": status["unavailableNodes"],
        "status_memory_os_ready": status["memoryOs"]["ready"],
        "status_memory_os_redis_required": status["memoryOs"]["redisRequired"],
        "status_memory_os_redis_configured": status["memoryOs"]["redisConfigured"],
        "status_memory_os_cronjob": status["memoryOs"]["cronJobName"],
        "control_plane_ready": status["controlPlane"]["ready"],
        "control_plane_voters": status["controlPlane"]["profile"]["voters_initial"],
        "control_plane_final_revision": status["controlPlane"]["profile"]["final_revision"],
        "control_plane_minority_blocked": status["controlPlane"]["profile"]["minority_commit_blocked"],
        "status_conditions_true": [
            key for key, value in sorted(conditions.items()) if value == "True"
        ],
        "status_action_count": len(status["actions"]),
        "autoscaling_metrics": [
            metric["resource"]["name"]
            for metric in hpa["spec"]["metrics"]
        ],
        "repair_namespaces": list(cronjob_container["args"]).count("--namespace"),
        "memory_os_calls_plan": "/memory-os/plan" in memory_os_script,
        "memory_os_calls_run": "/memory-os/run" in memory_os_script,
        "memory_os_applies_plan_lock": "plan_requires_lock" in memory_os_script,
        "memory_os_blocks_missing_redis": "spec.cache.redisUrl is not configured" in memory_os_script,
        "memory_os_run_on_all_replicas": "run_nodes = nodes if False else nodes[:1]" not in memory_os_script,
        "api_paths": paths,
    }


def run_serverless_profile() -> dict[str, object]:
    spec = WaveMindServerlessSpec(
        name="wavemind-serverless",
        namespace="wavemind-system",
        image="ghcr.io/caspiang/wavemind:latest",
        min_scale=0,
        max_scale=256,
        target_concurrency=80,
    )
    bundle = serverless_sample_bundle(spec)
    kinds = [resource["kind"] for resource in bundle["items"]]
    service = next(
        resource
        for resource in bundle["items"]
        if resource["apiVersion"] == "serving.knative.dev/v1"
    )
    deployment_names = {
        resource["metadata"]["name"]
        for resource in bundle["items"]
        if resource["kind"] == "Deployment"
    }
    scaled_object = next(
        resource for resource in bundle["items"] if resource["kind"] == "ScaledObject"
    )
    keda_target = scaled_object["spec"]["scaleTargetRef"]["name"]
    container = service["spec"]["template"]["spec"]["containers"][0]
    env_names = [item["name"] for item in container["env"]]
    annotations = service["spec"]["template"]["metadata"]["annotations"]
    readiness = spec.readiness_report()
    return {
        "engine": "WaveMind serverless plan",
        "has_knative_service": "Service" in kinds,
        "has_keda_scaled_object": "ScaledObject" in kinds,
        "scale_to_zero": readiness["scale_to_zero"],
        "max_scale": readiness["max_scale"],
        "target_concurrency": readiness["target_concurrency"],
        "uses_postgres": readiness["uses_postgres"],
        "uses_external_qdrant": readiness["uses_external_qdrant"],
        "uses_shared_cache": readiness["uses_shared_cache"],
        "safe_for_pod_eviction": readiness["safe_for_pod_eviction"],
        "keda_scale_target": readiness["keda_scale_target"],
        "keda_scale_target_kind": readiness["keda_scale_target_kind"],
        "valid_keda_scale_target": keda_target in deployment_names,
        "knative_min_scale": int(annotations["autoscaling.knative.dev/min-scale"]),
        "knative_max_scale": int(annotations["autoscaling.knative.dev/max-scale"]),
        "knative_target_concurrency": int(annotations["autoscaling.knative.dev/target"]),
        "env_has_postgres_dsn": "WAVEMIND_POSTGRES_DSN" in env_names,
        "env_has_qdrant_url": "WAVEMIND_QDRANT_URL" in env_names,
        "env_has_redis_url": "WAVEMIND_REDIS_URL" in env_names,
    }


def run_serverless_operational_profile() -> dict[str, object]:
    spec = WaveMindServerlessSpec(
        name="wavemind-serverless",
        namespace="wavemind-system",
        image="ghcr.io/caspiang/wavemind:latest",
        min_scale=0,
        max_scale=256,
        target_concurrency=80,
    )
    target = ServerlessWorkloadTarget(
        requests_per_second=3200.0,
        avg_request_ms=80.0,
        p99_request_ms=320.0,
        cold_start_ms=900.0,
        target_p99_ms=500.0,
        cold_start_budget_ms=3500.0,
        active_fraction=0.35,
        replica_hourly_cost_usd=0.08,
        monthly_budget_usd=750.0,
        max_error_rate=0.01,
        max_scale_out_seconds=60.0,
    )
    observed_path = serverless_observed_telemetry_path()
    observed_payload = json.loads(observed_path.read_text(encoding="utf-8"))
    observed = ServerlessObservedTelemetry.from_mapping(observed_payload)
    profile = spec.operational_profile(target, observed=observed)
    profile.update(
        {
            "observed_telemetry_path": display_path(observed_path),
            "observed_telemetry_methodology": observed_payload.get("methodology", ""),
            "observed_measured_pool_requests_per_second": observed_payload.get(
                "measured_pool_requests_per_second"
            ),
            "observed_per_replica_requests_per_second": observed_payload.get(
                "per_replica_requests_per_second"
            ),
            "observed_measured_replicas": observed_payload.get("measured_replicas"),
            "observed_configured_max_scale": observed_payload.get("configured_max_scale"),
            "observed_node_mode": observed_payload.get("node_mode", "unknown"),
            "observed_external_node_count": observed_payload.get("external_node_count"),
            "observed_seed_mode": observed_payload.get("seed_mode"),
            "observed_cold_start_measured": observed_payload.get("cold_start_measured"),
        }
    )
    return {
        "engine": "WaveMind serverless operational profile",
        **profile,
    }


def run_cache_profile(*, queries: int, capacity: int) -> dict[str, object]:
    cache = HotMemoryCache(capacity=capacity, ttl_seconds=120)
    latencies: list[float] = []
    hot_queries = [
        "budget preference",
        "support escalation",
        "trading profile",
        "security requirements",
        "reporting cadence",
    ]
    namespace_mod = max(1, min(32, capacity // max(1, len(hot_queries))))
    namespaces = [f"tenant:{index % namespace_mod}" for index in range(queries)]
    result = [
        QueryResult(
            id=1,
            text="cached hot memory",
            score=1.0,
            vector_score=1.0,
            field_score=0.0,
            graph_score=0.0,
            namespace="tenant:0",
        )
    ]
    for index, namespace in enumerate(namespaces):
        query = hot_queries[index % len(hot_queries)]
        started = time.perf_counter()
        cached = cache.get(namespace, query, top_k=3)
        if cached is None:
            cache.put(namespace, query, result, top_k=3)
        latencies.append((time.perf_counter() - started) * 1000.0)
    stats = cache.stats()
    prewarm_report_warmed = 0
    prewarm_hit = False
    with tempfile.TemporaryDirectory() as directory:
        memory = WaveMind(
            db_path=Path(directory) / "prewarm.sqlite3",
            encoder=HashingTextEncoder(vector_dim=64),
            width=16,
            height=16,
            layers=1,
            audit_queries=True,
        )
        prewarm_cache = HotMemoryCache(capacity=32, ttl_seconds=120)
        try:
            memory.remember("hot cached budget preference", namespace="tenant:prewarm")
            memory.query("budget preference", namespace="tenant:prewarm", top_k=1)
            memory.query("budget preference", namespace="tenant:prewarm", top_k=1)
            prewarm = CachePrewarmWorker(memory, prewarm_cache).run_once(
                namespace="tenant:prewarm",
                audit_limit=16,
                max_queries=4,
                min_frequency=2,
                top_k=1,
            )
            prewarm_report_warmed = prewarm.warmed
            cached = query_with_cache(
                memory,
                prewarm_cache,
                "budget preference",
                namespace="tenant:prewarm",
                top_k=1,
            )
            prewarm_hit = bool(cached) and prewarm_cache.stats().hits > 0
        finally:
            memory.close()
    return {
        "engine": "WaveMind hot cache",
        "queries": queries,
        "capacity": capacity,
        "hit_rate": stats.hit_rate,
        "evictions": stats.evictions,
        "prewarm_warmed": prewarm_report_warmed,
        "prewarm_hit": prewarm_hit,
        "avg_lookup_ms": statistics.mean(latencies) if latencies else 0.0,
        "p99_lookup_ms": percentile(latencies, 99),
    }


def run_query_vector_cache_profile(*, queries: int = 200) -> dict[str, object]:
    local_latencies: list[float] = []
    redis_latencies: list[float] = []
    service_latencies: list[float] = []
    client = RedisLikeCacheClient()
    redis_writer = RedisQueryVectorCache(client, prefix="wm:qvec-scale", ttl_seconds=120)
    redis_reader = RedisQueryVectorCache(client, prefix="wm:qvec-scale", ttl_seconds=120)

    with tempfile.TemporaryDirectory() as directory:
        local_encoder = CountingMemoryOSEncoder()
        local_memory = WaveMind(
            db_path=Path(directory) / "query-vector-local.sqlite3",
            encoder=local_encoder,
            width=16,
            height=16,
            layers=1,
        )
        redis_encoder = CountingMemoryOSEncoder()
        redis_memory = WaveMind(
            db_path=Path(directory) / "query-vector-redis.sqlite3",
            encoder=redis_encoder,
            width=16,
            height=16,
            layers=1,
        )
        service_encoder = CountingMemoryOSEncoder()
        service_memory = WaveMind(
            db_path=Path(directory) / "query-vector-service.sqlite3",
            encoder=service_encoder,
            width=16,
            height=16,
            layers=1,
        )
        try:
            namespace = "tenant:qvec"
            local_memory.remember("budget recall should reuse encoded query vectors", namespace=namespace)
            redis_memory.remember("budget recall should reuse redis query vectors", namespace=namespace)
            service_memory.remember(
                "budget recall should reuse service query vectors",
                namespace=namespace,
            )

            local_encoder.calls = 0
            local_cache = QueryVectorCache(capacity=32, ttl_seconds=120)
            for _ in range(max(1, int(queries))):
                started = time.perf_counter()
                query_with_vector_cache(
                    local_memory,
                    local_cache,
                    "budget recall",
                    namespace=namespace,
                    top_k=1,
                )
                local_latencies.append((time.perf_counter() - started) * 1000.0)

            redis_encoder.calls = 0
            started = time.perf_counter()
            writer_results = query_with_vector_cache(
                redis_memory,
                redis_writer,
                "budget recall",
                namespace=namespace,
                top_k=1,
            )
            redis_latencies.append((time.perf_counter() - started) * 1000.0)
            started = time.perf_counter()
            reader_results = query_with_vector_cache(
                redis_memory,
                redis_reader,
                "budget recall",
                namespace=namespace,
                top_k=1,
            )
            redis_latencies.append((time.perf_counter() - started) * 1000.0)

            local_stats = local_cache.stats()
            writer_stats = redis_writer.stats()
            reader_stats = redis_reader.stats()
            redis_cross_worker_hit = (
                bool(writer_results)
                and bool(reader_results)
                and writer_results[0].text == reader_results[0].text
                and reader_stats.hits >= 1
                and redis_encoder.calls == 1
            )
            from fastapi.testclient import TestClient

            service_encoder.calls = 0
            service_cache = QueryVectorCache(capacity=32, ttl_seconds=120)
            app = create_app(mind=service_memory)
            app.state.cache = None
            app.state.vector_cache = service_cache
            service_results_ok = True
            service_query_count = max(1, int(queries))
            with TestClient(app) as api:
                for _ in range(service_query_count):
                    started = time.perf_counter()
                    response = api.post(
                        "/query",
                        json={
                            "text": "budget recall",
                            "namespace": namespace,
                            "top_k": 1,
                        },
                    )
                    service_latencies.append((time.perf_counter() - started) * 1000.0)
                    service_results_ok = (
                        service_results_ok
                        and response.status_code == 200
                        and bool(response.json().get("results"))
                        and response.json()["results"][0]["text"]
                        == "budget recall should reuse service query vectors"
                    )
                metrics_response = api.get("/metrics")
            service_stats = service_cache.stats()
            metrics_text = metrics_response.text if metrics_response.status_code == 200 else ""
            service_metrics_exposed = all(
                token in metrics_text
                for token in (
                    "wavemind_vector_cache_hits_total",
                    "wavemind_vector_cache_misses_total",
                    "wavemind_vector_cache_hit_rate",
                )
            )
            return {
                "engine": "WaveMind query vector cache",
                "queries": int(queries),
                "local_encode_calls": local_encoder.calls,
                "local_cache_hits": local_stats.hits,
                "local_cache_misses": local_stats.misses,
                "local_hit_rate": local_stats.hit_rate,
                "redis_shared_across_workers": redis_cross_worker_hit,
                "redis_encode_calls": redis_encoder.calls,
                "redis_writer_misses": writer_stats.misses,
                "redis_reader_hits": reader_stats.hits,
                "redis_keys": len(client.items),
                "avg_local_query_ms": statistics.mean(local_latencies) if local_latencies else 0.0,
                "p99_local_query_ms": percentile(local_latencies, 99),
                "avg_redis_query_ms": statistics.mean(redis_latencies) if redis_latencies else 0.0,
                "p99_redis_query_ms": percentile(redis_latencies, 99),
                "service_boundary": "FastAPI TestClient",
                "service_queries": service_query_count,
                "service_results_ok": service_results_ok,
                "service_encoder_calls": service_encoder.calls,
                "service_saved_encode_calls": max(
                    0,
                    service_query_count - int(service_encoder.calls),
                ),
                "service_cache_hits": service_stats.hits,
                "service_cache_misses": service_stats.misses,
                "service_hit_rate": service_stats.hit_rate,
                "service_metrics_exposed": service_metrics_exposed,
                "avg_service_query_ms": statistics.mean(service_latencies)
                if service_latencies
                else 0.0,
                "p99_service_query_ms": percentile(service_latencies, 99),
            }
        finally:
            local_memory.close()
            redis_memory.close()
            service_memory.close()


def run_api_batch_query_profile(*, queries: int = 100) -> dict[str, object]:
    from fastapi.testclient import TestClient

    queries = max(1, int(queries))
    namespace = "tenant:api-batch"

    def run_service(db_path: Path, *, batch: bool) -> dict[str, object]:
        encoder = CountingMemoryOSEncoder()
        memory = WaveMind(
            db_path=db_path,
            encoder=encoder,
            width=16,
            height=16,
            layers=1,
        )
        latencies: list[float] = []
        try:
            memory.remember("budget recall should work through batch query", namespace=namespace)
            encoder.calls = 0
            cache = QueryVectorCache(capacity=32, ttl_seconds=120)
            app = create_app(mind=memory)
            app.state.cache = None
            app.state.vector_cache = cache
            success = True
            with TestClient(app) as api:
                if batch:
                    started = time.perf_counter()
                    response = api.post(
                        "/query/batch",
                        json={
                            "queries": [
                                {
                                    "text": "budget recall",
                                    "namespace": namespace,
                                    "top_k": 1,
                                }
                                for _ in range(queries)
                            ]
                        },
                    )
                    latencies.append((time.perf_counter() - started) * 1000.0)
                    payload = response.json() if response.status_code == 200 else {}
                    items = payload.get("items", [])
                    returned_texts = [
                        item.get("results", [{}])[0].get("text")
                        if item.get("results")
                        else None
                        for item in items
                    ]
                    success = (
                        response.status_code == 200
                        and payload.get("count") == queries
                        and len(items) == queries
                        and all(
                            text == "budget recall should work through batch query"
                            for text in returned_texts
                        )
                    )
                else:
                    for _ in range(queries):
                        started = time.perf_counter()
                        response = api.post(
                            "/query",
                            json={
                                "text": "budget recall",
                                "namespace": namespace,
                                "top_k": 1,
                            },
                        )
                        latencies.append((time.perf_counter() - started) * 1000.0)
                        success = (
                            success
                            and response.status_code == 200
                            and response.json()["results"][0]["text"]
                            == "budget recall should work through batch query"
                        )
                metrics_response = api.get("/metrics")
            stats = cache.stats()
            return {
                "success": success,
                "encoder_calls": encoder.calls,
                "cache_hits": stats.hits,
                "cache_misses": stats.misses,
                "hit_rate": stats.hit_rate,
                "total_ms": sum(latencies),
                "avg_ms": statistics.mean(latencies) if latencies else 0.0,
                "p99_ms": percentile(latencies, 99),
                "metrics_text": metrics_response.text if metrics_response.status_code == 200 else "",
            }
        finally:
            memory.close()

    with tempfile.TemporaryDirectory() as directory:
        individual = run_service(Path(directory) / "query-batch-individual.sqlite3", batch=False)
        batched = run_service(Path(directory) / "query-batch-batched.sqlite3", batch=True)

    batch_metrics_exposed = all(
        token in str(batched["metrics_text"])
        for token in (
            "wavemind_api_query_batch_requests_total",
            "wavemind_vector_cache_hits_total",
            "wavemind_vector_cache_misses_total",
        )
    )
    individual_total_ms = float(individual["total_ms"])
    batch_total_ms = float(batched["total_ms"])
    return {
        "engine": "WaveMind API batch query",
        "queries": queries,
        "batch_size": queries,
        "individual_http_requests": queries,
        "batch_http_requests": 1,
        "request_reduction_ratio": 1.0 - (1.0 / float(queries)),
        "individual_success": individual["success"],
        "batch_success": batched["success"],
        "individual_encoder_calls": individual["encoder_calls"],
        "batch_encoder_calls": batched["encoder_calls"],
        "individual_cache_hits": individual["cache_hits"],
        "batch_cache_hits": batched["cache_hits"],
        "batch_cache_misses": batched["cache_misses"],
        "batch_hit_rate": batched["hit_rate"],
        "batch_metrics_exposed": batch_metrics_exposed,
        "individual_total_ms": individual_total_ms,
        "batch_total_ms": batch_total_ms,
        "batch_total_speedup": (
            individual_total_ms / batch_total_ms if batch_total_ms > 0 else 0.0
        ),
        "individual_p99_query_ms": individual["p99_ms"],
        "batch_request_ms": batch_total_ms,
    }


class _RateLimitClient:
    host = "127.0.0.1"


class _RateLimitRequest:
    def __init__(self, api_key: str | None = None):
        self.headers = {"x-api-key": api_key} if api_key else {}
        self.client = _RateLimitClient()


def run_shared_rate_limit_profile() -> dict[str, object]:
    client = RedisLikeCacheClient()
    writer = RedisRateLimiter(
        client,
        requests_per_minute=4,
        prefix="wm:rate-scale",
    )
    reader = RedisRateLimiter(
        client,
        requests_per_minute=4,
        prefix="wm:rate-scale",
    )
    latencies: list[float] = []
    decisions: list[bool] = []
    for index in range(5):
        limiter = writer if index % 2 == 0 else reader
        started = time.perf_counter()
        decisions.append(limiter.allow(_RateLimitRequest(api_key="shared-worker-key")))
        latencies.append((time.perf_counter() - started) * 1000.0)
    writer_stats = writer.stats()
    reader_stats = reader.stats()
    return {
        "engine": "WaveMind shared rate limiter",
        "backend": "redis-compatible fixed window",
        "workers": 2,
        "limit_per_minute": 4,
        "requests": len(decisions),
        "allowed": sum(1 for decision in decisions if decision),
        "limited": sum(1 for decision in decisions if not decision),
        "shared_across_workers": decisions == [True, True, True, True, False],
        "redis_keys": len(client.items),
        "expire_seconds": next(iter(client.expirations.values()), None),
        "writer_allowed": writer_stats.allowed,
        "reader_allowed": reader_stats.allowed,
        "reader_limited": reader_stats.limited,
        "avg_check_ms": statistics.mean(latencies),
        "p99_check_ms": percentile(latencies, 99),
    }


def run_redis_cache_profile() -> dict[str, object]:
    client = RedisLikeCacheClient()
    writer_cache = RedisHotMemoryCache(client, prefix="wm:scale", ttl_seconds=120)
    reader_cache = RedisHotMemoryCache(client, prefix="wm:scale", ttl_seconds=120)
    latencies: list[float] = []

    with tempfile.TemporaryDirectory() as directory:
        memory = WaveMind(
            db_path=Path(directory) / "redis-cache.sqlite3",
            encoder=MemoryOSEncoder(),
            width=16,
            height=16,
            layers=1,
            audit_queries=True,
            graph_weight=1.0,
            graph_steps=2,
            graph_expand_k=10,
            rerank_k=10,
        )
        try:
            namespace = "tenant:redis-cache"
            memory.remember("redis shared cache keeps hot budget recall", namespace=namespace)
            memory.query("budget recall", namespace=namespace, top_k=1)
            memory.query("budget recall", namespace=namespace, top_k=1)
            prewarm = CachePrewarmWorker(memory, writer_cache).run_once(
                namespace=namespace,
                audit_limit=16,
                max_queries=4,
                min_frequency=2,
                top_k=1,
            )
            started = time.perf_counter()
            shared_results = query_with_cache(
                memory,
                reader_cache,
                "budget recall",
                namespace=namespace,
                top_k=1,
            )
            latencies.append((time.perf_counter() - started) * 1000.0)
            shared_hit = (
                bool(shared_results)
                and shared_results[0].text == "redis shared cache keeps hot budget recall"
                and reader_cache.stats().hits >= 1
            )

            os_namespace = "tenant:redis-os"
            memory.remember(
                "User likes Rust systems programming",
                namespace=os_namespace,
                tags=["systems"],
            )
            memory.remember(
                "User studies compiler internals",
                namespace=os_namespace,
                tags=["systems"],
            )
            budget_id = memory.remember(
                "budget recall should be prefetched",
                namespace=os_namespace,
                tags=["preference"],
            )
            memory.remember(
                "risk limits follow budget recall in real sessions",
                namespace=os_namespace,
                tags=["risk"],
            )
            cold_id = memory.remember(
                "unused redis memory os cold note",
                namespace=os_namespace,
                tags=["cold"],
                priority=2.0,
            )
            memory.remember("expired redis memory os stale fact", namespace=os_namespace, ttl_seconds=-1)
            memory.query("systems programming", namespace=os_namespace, top_k=1)
            memory.query("systems programming", namespace=os_namespace, top_k=1)
            memory.query("budget recall", namespace=os_namespace, top_k=1)
            memory.query("risk limits", namespace=os_namespace, top_k=1)
            memory.query("budget recall", namespace=os_namespace, top_k=1)
            feedback_positive_before = memory.store.get(budget_id).priority
            memory.feedback(
                budget_id,
                namespace=os_namespace,
                useful=True,
                strength=0.4,
                query="budget recall",
                reason="scale benchmark accepted recall",
            )
            feedback_positive_after = memory.store.get(budget_id).priority
            feedback_negative_before = memory.store.get(cold_id).priority
            memory.feedback(
                cold_id,
                namespace=os_namespace,
                useful=False,
                strength=0.3,
                query="cold note",
                reason="scale benchmark rejected recall",
            )
            feedback_negative_after = memory.store.get(cold_id).priority

            os_cache = RedisHotMemoryCache(client, prefix="wm:scale", ttl_seconds=120)
            os_reader_cache = RedisHotMemoryCache(client, prefix="wm:scale", ttl_seconds=120)
            os_lock_key = f"wm:scale:memory-os-lock:{os_namespace}"
            os_lock = RedisMemoryOSLock(
                client,
                key=os_lock_key,
                ttl_seconds=300,
                owner="scale-readiness-memory-os",
            )
            os_started = time.perf_counter()
            os_report = MemoryOSWorker(memory, os_cache).run_once(
                namespace=os_namespace,
                audit_limit=16,
                max_hot_queries=8,
                min_frequency=2,
                top_k=1,
                consolidate_steps=2,
                min_concept_energy=0.01,
                min_concept_size=2,
                max_concepts=1,
                memory_pressure_threshold=2,
                forgetting_min_age_seconds=0.0,
                forgetting_priority_decay=0.10,
                forgetting_max_access_count=0,
                target_memories=2_000_000,
                namespace_count=4096,
                node_count=2,
                replication_factor=3,
                read_quorum=1,
                read_fanout=1,
                target_qps=250.0,
                deployment="production",
                multimodal=True,
                lock=os_lock,
                lock_required=True,
            )
            os_ms = (time.perf_counter() - os_started) * 1000.0
            busy_lock_key = f"wm:scale:memory-os-busy:{os_namespace}"
            held_lock = RedisMemoryOSLock(
                client,
                key=busy_lock_key,
                ttl_seconds=300,
                owner="active-worker",
            )
            held_lock.acquire()
            try:
                busy_report = MemoryOSWorker(memory, os_cache).run_once(
                    namespace=os_namespace,
                    audit_limit=16,
                    max_hot_queries=8,
                    min_frequency=2,
                    top_k=1,
                    consolidate_steps=0,
                    consolidate_concepts=False,
                    predict_priorities=False,
                    adaptive_forgetting=False,
                    predictive_prefetch=False,
                    architecture_advice=False,
                    lock=RedisMemoryOSLock(
                        client,
                        key=busy_lock_key,
                        ttl_seconds=300,
                        owner="contending-worker",
                    ),
                    lock_required=True,
                )
            finally:
                held_lock.release()
            started = time.perf_counter()
            os_cached = query_with_cache(
                memory,
                os_reader_cache,
                "budget recall",
                namespace=os_namespace,
                top_k=1,
            )
            latencies.append((time.perf_counter() - started) * 1000.0)
            os_cross_worker_hit = (
                bool(os_cached)
                and os_cached[0].text == "budget recall should be prefetched"
                and os_reader_cache.stats().hits >= 1
            )
            os_transition_cached = os_reader_cache.get(
                os_namespace,
                "risk limits",
                top_k=1,
            )
            os_transition_hit = (
                bool(os_transition_cached)
                and os_transition_cached[0].text == "risk limits follow budget recall in real sessions"
            )

            invalidated = writer_cache.invalidate_namespace(namespace)
            invalidation_removed_key = invalidated >= 1 and reader_cache.get(
                namespace,
                "budget recall",
                top_k=1,
            ) is None

            stats = writer_cache.stats()
            reader_stats = reader_cache.stats()
            os_stats = os_cache.stats()
            os_reader_stats = os_reader_cache.stats()
            return {
                "engine": "WaveMind Redis hot cache",
                "client": "redis-compatible",
                "shared_cache_visible_across_clients": shared_hit,
                "cache_prewarm_warmed": prewarm.warmed,
                "cache_prewarm_cross_worker_hit": shared_hit,
                "memory_os_ok": os_report.ok,
                "memory_os_lock_required": os_report.lock.required,
                "memory_os_lock_acquired": os_report.lock.acquired,
                "memory_os_lock_released": client.get(os_lock_key) is None,
                "memory_os_busy_lock_skipped": (
                    busy_report.lock.required
                    and not busy_report.lock.acquired
                    and busy_report.lock.reason == "lock_already_held"
                    and "lock_skipped" in busy_report.actions
                ),
                "memory_os_hot_queries": len(os_report.hot_queries),
                "memory_os_prewarm_warmed": os_report.prewarm.warmed,
                "memory_os_predictive_generated": os_report.predictive_prefetch.generated_queries,
                "memory_os_predictive_warmed": os_report.predictive_prefetch.warmed,
                "memory_os_transition_prefetch_queries": list(
                    os_report.predictive_prefetch.transition_queries
                ),
                "memory_os_transition_prefetch_edges": [
                    edge.as_dict()
                    for edge in os_report.predictive_prefetch.transition_edges
                ],
                "memory_os_transition_prefetch_hit": os_transition_hit,
                "memory_os_concepts_created": os_report.concepts_created,
                "memory_os_user_feedback_events": len(
                    memory.audit_events(
                        namespace=os_namespace,
                        action="feedback",
                        limit=8,
                    )
                ),
                "memory_os_positive_feedback_priority_delta": (
                    feedback_positive_after - feedback_positive_before
                ),
                "memory_os_negative_feedback_priority_delta": (
                    feedback_negative_after - feedback_negative_before
                ),
                "memory_os_priority_predictions": os_report.priority_predictions,
                "memory_os_priority_boost_total": os_report.priority_boost_total,
                "memory_os_forgetting_demotions": os_report.forgetting_demotions,
                "memory_os_forgetting_decay_total": os_report.forgetting_decay_total,
                "memory_os_architecture_advice_status": os_report.architecture_advice.get("status"),
                "memory_os_architecture_recommendations": [
                    item["id"]
                    for item in os_report.architecture_advice.get("recommendations", [])
                    if isinstance(item, dict) and "id" in item
                ],
                "memory_os_cross_worker_hit": os_cross_worker_hit,
                "memory_os_run_ms": os_ms,
                "namespace_invalidation_removed": invalidation_removed_key,
                "redis_keys": len(client.items),
                "writer_hits": stats.hits,
                "writer_misses": stats.misses,
                "reader_hits": reader_stats.hits,
                "os_hits": os_stats.hits,
                "os_reader_hits": os_reader_stats.hits,
                "avg_lookup_ms": statistics.mean(latencies) if latencies else 0.0,
                "p99_lookup_ms": percentile(latencies, 99),
            }
        finally:
            memory.close()


def run_api_cache_mutation_profile() -> dict[str, object]:
    from fastapi.testclient import TestClient

    from wavemind.api import create_app

    client = RedisLikeCacheClient()
    latencies: list[float] = []

    with tempfile.TemporaryDirectory() as directory:
        memory = WaveMind(
            db_path=Path(directory) / "api-cache-mutations.sqlite3",
            encoder=MemoryOSEncoder(),
            width=16,
            height=16,
            layers=1,
            priority_weight=2.0,
            graph_weight=0.0,
            rerank_k=10,
        )
        app = create_app(mind=memory)
        app.state.cache = RedisHotMemoryCache(client, prefix="wm:api", ttl_seconds=120)
        namespace = "tenant:api-cache"
        try:
            with TestClient(app) as api:
                old_response = api.post(
                    "/remember",
                    json={
                        "text": "old API cache budget recall",
                        "namespace": namespace,
                        "priority": 1.0,
                    },
                )
                old_response.raise_for_status()
                old_id = old_response.json()["id"]

                started = time.perf_counter()
                first_query = api.post(
                    "/query",
                    json={"text": "budget recall", "namespace": namespace, "top_k": 1},
                )
                first_query.raise_for_status()
                latencies.append((time.perf_counter() - started) * 1000.0)
                first_results = first_query.json()["results"]
                cache_keys_after_first_query = len(client.items)

                fresh_response = api.post(
                    "/remember",
                    json={
                        "text": "fresh API cache budget recall",
                        "namespace": namespace,
                        "priority": 10.0,
                    },
                )
                fresh_response.raise_for_status()
                fresh_id = fresh_response.json()["id"]
                cache_keys_after_remember = len(client.items)

                started = time.perf_counter()
                second_query = api.post(
                    "/query",
                    json={"text": "budget recall", "namespace": namespace, "top_k": 1},
                )
                second_query.raise_for_status()
                latencies.append((time.perf_counter() - started) * 1000.0)
                second_results = second_query.json()["results"]
                cache_keys_after_second_query = len(client.items)

                feedback_response = api.post(
                    "/feedback",
                    json={
                        "id": fresh_id,
                        "namespace": namespace,
                        "useful": False,
                        "strength": 10.0,
                        "query": "budget recall",
                        "reason": "scale benchmark rejected stale priority",
                    },
                )
                feedback_response.raise_for_status()
                cache_keys_after_feedback = len(client.items)

                started = time.perf_counter()
                feedback_query = api.post(
                    "/query",
                    json={"text": "budget recall", "namespace": namespace, "top_k": 1},
                )
                feedback_query.raise_for_status()
                latencies.append((time.perf_counter() - started) * 1000.0)
                feedback_results = feedback_query.json()["results"]

                delete_response = api.request(
                    "DELETE",
                    "/forget",
                    json={"id": fresh_id, "namespace": namespace},
                )
                delete_response.raise_for_status()
                cache_keys_after_forget = len(client.items)

                started = time.perf_counter()
                third_query = api.post(
                    "/query",
                    json={"text": "budget recall", "namespace": namespace, "top_k": 3},
                )
                third_query.raise_for_status()
                latencies.append((time.perf_counter() - started) * 1000.0)
                third_results = third_query.json()["results"]

                stale_prevented_after_remember = bool(second_results) and second_results[0]["id"] == fresh_id
                feedback_demoted_fresh = bool(feedback_results) and feedback_results[0]["id"] != fresh_id
                stale_prevented_after_forget = all(result["id"] != fresh_id for result in third_results)
                old_recall_after_forget = any(result["id"] == old_id for result in third_results)
                return {
                    "engine": "WaveMind API cache mutation safety",
                    "client": "fastapi+redis-compatible-cache",
                    "first_query_cached": cache_keys_after_first_query >= 1
                    and bool(first_results)
                    and first_results[0]["id"] == old_id,
                    "cache_invalidated_on_remember": cache_keys_after_remember == 0,
                    "stale_prevented_after_remember": stale_prevented_after_remember,
                    "cache_invalidated_on_feedback": cache_keys_after_feedback == 0,
                    "feedback_demoted_rejected_memory": feedback_demoted_fresh,
                    "cache_invalidated_on_forget": cache_keys_after_forget == 0,
                    "stale_prevented_after_forget": stale_prevented_after_forget,
                    "old_recall_after_forget": old_recall_after_forget,
                    "avg_api_ms": statistics.mean(latencies) if latencies else 0.0,
                    "p99_api_ms": percentile(latencies, 99),
                }
        finally:
            memory.close()


def run_batch_feedback_profile() -> dict[str, object]:
    from fastapi.testclient import TestClient

    from wavemind.api import create_app

    client = RedisLikeCacheClient()
    latencies: list[float] = []
    warmup_api_ms = 0.0

    with tempfile.TemporaryDirectory() as directory:
        memory = WaveMind(
            db_path=Path(directory) / "batch-feedback.sqlite3",
            encoder=MemoryOSEncoder(),
            width=16,
            height=16,
            layers=1,
            audit_queries=True,
        )
        app = create_app(mind=memory)
        app.state.cache = RedisHotMemoryCache(client, prefix="wm:batch-feedback", ttl_seconds=120)
        namespace = "tenant:batch-feedback"
        try:
            with TestClient(app) as api:
                warmup_namespace = "tenant:batch-feedback-warmup"
                warmup_useful = api.post(
                    "/remember",
                    json={
                        "text": "warmup batch feedback useful budget recall",
                        "namespace": warmup_namespace,
                    },
                )
                warmup_stale = api.post(
                    "/remember",
                    json={
                        "text": "warmup batch feedback stale recall",
                        "namespace": warmup_namespace,
                    },
                )
                warmup_useful.raise_for_status()
                warmup_stale.raise_for_status()
                warmup_started = time.perf_counter()
                warmup_response = api.post(
                    "/feedback/batch",
                    json={
                        "namespace": warmup_namespace,
                        "items": [
                            {
                                "id": warmup_useful.json()["id"],
                                "useful": True,
                                "strength": 0.1,
                                "query": "budget recall",
                            },
                            {
                                "id": warmup_stale.json()["id"],
                                "useful": False,
                                "strength": 0.1,
                                "query": "stale recall",
                            },
                        ],
                    },
                )
                warmup_response.raise_for_status()
                warmup_api_ms = (time.perf_counter() - warmup_started) * 1000.0
                operation_metrics_cls = type(app.state.operation_metrics)
                app.state.operation_metrics = operation_metrics_cls(max_samples=512)

                useful = api.post(
                    "/remember",
                    json={"text": "batch feedback useful budget recall", "namespace": namespace},
                )
                stale = api.post(
                    "/remember",
                    json={"text": "batch feedback stale recall", "namespace": namespace},
                )
                useful.raise_for_status()
                stale.raise_for_status()
                useful_id = useful.json()["id"]
                stale_id = stale.json()["id"]

                cached = api.post(
                    "/query",
                    json={"text": "budget recall", "namespace": namespace, "top_k": 1},
                )
                cached.raise_for_status()
                cache_keys_after_query = len(client.items)

                useful_before_record = memory.store.get(useful_id)
                stale_before_record = memory.store.get(stale_id)
                if useful_before_record is None or stale_before_record is None:
                    raise RuntimeError("feedback profile setup did not persist memories")
                useful_before = useful_before_record.priority
                stale_before = stale_before_record.priority
                started = time.perf_counter()
                response = api.post(
                    "/feedback/batch",
                    json={
                        "namespace": namespace,
                        "items": [
                            {
                                "id": useful_id,
                                "useful": True,
                                "strength": 0.5,
                                "query": "budget recall",
                                "reason": "accepted",
                            },
                            {
                                "id": stale_id,
                                "useful": False,
                                "strength": 0.25,
                                "query": "stale recall",
                                "reason": "rejected",
                            },
                            {"id": useful_id, "namespace": "tenant:wrong", "useful": True},
                        ],
                    },
                )
                response.raise_for_status()
                latencies.append((time.perf_counter() - started) * 1000.0)
                payload = response.json()
                useful_after = memory.store.get(useful_id).priority
                stale_after = memory.store.get(stale_id).priority
                events = memory.audit_events(namespace=namespace, action="feedback", limit=8)
                metrics = app.state.operation_metrics.snapshot()
                handler_p99_api_ms = float(
                    metrics.get("api_feedback_batch_max_latency_ms", percentile(latencies, 99))
                )
                return {
                    "engine": "WaveMind batch feedback",
                    "client": "fastapi+redis-compatible-cache",
                    "items": 3,
                    "accepted": payload["accepted"],
                    "rejected": payload["rejected"],
                    "ok": payload["accepted"] == 2 and payload["rejected"] == 1,
                    "cache_was_warmed": cache_keys_after_query >= 1,
                    "cache_invalidated": payload["cache_invalidated"] >= 1,
                    "audit_events": len(events),
                    "positive_feedback_priority_delta": useful_after - useful_before,
                    "negative_feedback_priority_delta": stale_after - stale_before,
                    "avg_api_ms": float(
                        metrics.get(
                            "api_feedback_batch_avg_latency_ms",
                            statistics.mean(latencies) if latencies else 0.0,
                        )
                    ),
                    "p99_api_ms": handler_p99_api_ms,
                    "client_wall_p99_ms": percentile(latencies, 99),
                    "warmup_api_ms": warmup_api_ms,
                    "measured_requests": len(latencies),
                }
        finally:
            memory.close()


def run_memory_os_profile() -> dict[str, object]:
    with tempfile.TemporaryDirectory() as directory:
        memory = WaveMind(
            db_path=Path(directory) / "memory-os.sqlite3",
            encoder=MemoryOSEncoder(),
            width=16,
            height=16,
            layers=1,
            audit_queries=True,
            graph_weight=1.0,
            graph_steps=2,
            graph_expand_k=10,
            rerank_k=10,
        )
        cache = HotMemoryCache(capacity=16, ttl_seconds=120)
        try:
            memory.remember(
                "User likes Rust systems programming",
                namespace="tenant:os",
                tags=["systems"],
            )
            memory.remember(
                "User studies compiler internals",
                namespace="tenant:os",
                tags=["systems"],
            )
            budget_id = memory.remember(
                "budget recall should be prefetched",
                namespace="tenant:os",
                tags=["preference"],
            )
            memory.remember(
                "risk limits follow budget recall in real sessions",
                namespace="tenant:os",
                tags=["risk"],
            )
            cold_id = memory.remember(
                "unused memory os cold note",
                namespace="tenant:os",
                tags=["cold"],
                priority=2.0,
            )
            memory.remember("expired memory os stale fact", namespace="tenant:os", ttl_seconds=-1)
            memory.query("systems programming", namespace="tenant:os", top_k=1)
            memory.query("systems programming", namespace="tenant:os", top_k=1)
            memory.query("budget recall", namespace="tenant:os", top_k=1)
            memory.query("risk limits", namespace="tenant:os", top_k=1)
            memory.query("budget recall", namespace="tenant:os", top_k=1)
            feedback_positive_before = memory.store.get(budget_id).priority
            memory.feedback(
                budget_id,
                namespace="tenant:os",
                useful=True,
                strength=0.4,
                query="budget recall",
                reason="scale benchmark accepted recall",
            )
            feedback_positive_after = memory.store.get(budget_id).priority
            feedback_negative_before = memory.store.get(cold_id).priority
            memory.feedback(
                cold_id,
                namespace="tenant:os",
                useful=False,
                strength=0.3,
                query="cold note",
                reason="scale benchmark rejected recall",
            )
            feedback_negative_after = memory.store.get(cold_id).priority

            started = time.perf_counter()
            report = MemoryOSWorker(memory, cache).run_once(
                namespace="tenant:os",
                audit_limit=16,
                max_hot_queries=8,
                min_frequency=2,
                top_k=1,
                consolidate_steps=2,
                min_concept_energy=0.01,
                min_concept_size=2,
                max_concepts=1,
                memory_pressure_threshold=2,
                forgetting_min_age_seconds=0.0,
                forgetting_priority_decay=0.10,
                forgetting_max_access_count=0,
                target_memories=2_000_000,
                namespace_count=4096,
                node_count=2,
                replication_factor=3,
                read_quorum=1,
                read_fanout=1,
                target_qps=250.0,
                deployment="production",
                multimodal=True,
            )
            elapsed_ms = (time.perf_counter() - started) * 1000.0
            cached = cache.get("tenant:os", "budget recall", top_k=1)
            transition_cached = cache.get("tenant:os", "risk limits", top_k=1)
            concept_results = memory.query(
                "systems programming",
                namespace="tenant:os",
                tags=["concept"],
                top_k=1,
            )
            schedule = MemoryOSScheduler(memory).plan(
                namespace="tenant:os",
                audit_limit=16,
                max_hot_queries=8,
                min_frequency=2,
                top_k=1,
                target_memories=2_000_000,
                namespace_count=4096,
                node_count=2,
                replication_factor=3,
                read_quorum=1,
                read_fanout=1,
                target_qps=250.0,
                observed_p99_ms=125.0,
                deployment="production",
                cache_mode="auto",
                multimodal=True,
                memory_pressure_threshold=2,
            )
            execution = schedule.execution_plan
            execution_required_environment = sorted(
                {
                    name
                    for step in execution.steps
                    for name in step.required_environment
                }
            )
            return {
                "engine": "WaveMind Memory OS",
                "ok": report.ok,
                "hot_queries": len(report.hot_queries),
                "prewarm_warmed": report.prewarm.warmed,
                "prewarm_hit": bool(cached),
                "predictive_prefetch_generated": report.predictive_prefetch.generated_queries,
                "predictive_prefetch_warmed": report.predictive_prefetch.warmed,
                "predictive_prefetch_queries": list(report.predictive_prefetch.queries),
                "transition_prefetch_queries": list(
                    report.predictive_prefetch.transition_queries
                ),
                "transition_prefetch_edges": [
                    edge.as_dict()
                    for edge in report.predictive_prefetch.transition_edges
                ],
                "transition_prefetch_hit": (
                    bool(transition_cached)
                    and transition_cached[0].text == "risk limits follow budget recall in real sessions"
                ),
                "expired_purged": report.expired_purged,
                "concepts_created": report.concepts_created,
                "concept_recall": bool(concept_results),
                "user_feedback_events": len(
                    memory.audit_events(
                        namespace="tenant:os",
                        action="feedback",
                        limit=8,
                    )
                ),
                "positive_feedback_priority_delta": (
                    feedback_positive_after - feedback_positive_before
                ),
                "negative_feedback_priority_delta": (
                    feedback_negative_after - feedback_negative_before
                ),
                "priority_predictions": report.priority_predictions,
                "priority_boost_total": report.priority_boost_total,
                "forgetting_demotions": report.forgetting_demotions,
                "forgetting_decay_total": report.forgetting_decay_total,
                "architecture_advice_status": report.architecture_advice.get("status"),
                "architecture_advice_recommendation_ids": [
                    item["id"]
                    for item in report.architecture_advice.get("recommendations", [])
                    if isinstance(item, dict) and "id" in item
                ],
                "architecture_next_commands": len(
                    report.architecture_advice.get("next_commands", [])
                ),
                "suggestion_count": len(report.suggestions),
                "suggestion_ids": [suggestion.id for suggestion in report.suggestions],
                "suggestion_severities": [
                    suggestion.severity for suggestion in report.suggestions
                ],
                "suggestions_with_evidence": sum(
                    1 for suggestion in report.suggestions if suggestion.evidence
                ),
                "policy_status": report.policy_manifest.status,
                "policy_decision_count": len(report.policy_manifest.decisions),
                "policy_decision_ids": [
                    decision.id for decision in report.policy_manifest.decisions
                ],
                "policy_decision_statuses": [
                    decision.status for decision in report.policy_manifest.decisions
                ],
                "policy_decision_strategies": {
                    decision.id: decision.strategy
                    for decision in report.policy_manifest.decisions
                },
                "policy_history_trend": report.policy_history.trend,
                "policy_history_previous_runs": report.policy_history.previous_runs,
                "policy_repeated_required_ids": list(
                    report.policy_history.repeated_required_ids
                ),
                "policy_history_escalations": len(
                    [
                        suggestion
                        for suggestion in report.suggestions
                        if suggestion.id.startswith("policy-history:")
                    ]
                ),
                "scheduler_status": schedule.status,
                "scheduler_effective_cache_mode": schedule.effective_cache_mode,
                "execution_safe_to_run": execution.safe_to_run,
                "execution_requires_shared_cache": execution.requires_shared_cache,
                "execution_requires_distributed_lock": execution.requires_distributed_lock,
                "execution_max_parallel_workers": execution.max_parallel_workers,
                "execution_step_count": len(execution.steps),
                "execution_worker_pool_tasks": list(execution.worker_pool_task_ids),
                "execution_singleton_tasks": list(execution.singleton_task_ids),
                "execution_state_mutating_tasks": list(execution.state_mutating_task_ids),
                "execution_blocked_tasks": list(execution.blocked_task_ids),
                "execution_warnings": list(execution.warnings),
                "execution_required_environment": execution_required_environment,
                "execution_run_scopes": {
                    step.task_id: step.run_scope for step in execution.steps
                },
                "index_rebuilt": report.index_rebuilt,
                "actions": list(report.actions),
                "recommendations": list(report.recommendations),
                "run_ms": elapsed_ms,
            }
        finally:
            memory.close()


def run_distributed_sharding_profile() -> dict[str, object]:
    with tempfile.TemporaryDirectory() as directory:
        client = LocalWaveMindServiceClient(Path(directory) / "services")
        memory = DistributedShardedWaveMind(
            nodes=[
                ClusterNode(id="node-a", address="node-a", zone="zone-a"),
                ClusterNode(id="node-b", address="node-b", zone="zone-b"),
                ClusterNode(id="node-c", address="node-c", zone="zone-c"),
            ],
            replication_factor=2,
            client=client,
        )
        try:
            namespace = "tenant:distributed"
            started = time.perf_counter()
            write = memory.remember(
                "distributed service shard keeps tenant memory",
                namespace=namespace,
            )
            write_ms = (time.perf_counter() - started) * 1000.0
            placement = memory.placement(namespace)
            memory.set_node_available(placement.primary, False)
            query_started = time.perf_counter()
            results = memory.query("tenant memory", namespace=namespace, top_k=1)
            query_after_primary_loss_ms = (time.perf_counter() - query_started) * 1000.0
            recalled_after_primary_loss = bool(results) and results[0].text == (
                "distributed service shard keeps tenant memory"
            )
            memory.set_node_available(placement.primary, True)
            stale_node = next(node for node in placement.replicas if node != placement.primary)
            client._mind(stale_node).forget(
                namespace=namespace,
                text="distributed service shard keeps tenant memory",
            )
            memory.set_node_available(placement.primary, False)
            missing_before_repair = (
                memory.query("tenant memory", namespace=namespace, top_k=1) == []
            )
            memory.set_node_available(placement.primary, True)
            repair = memory.repair_namespace(namespace)
            memory.set_node_available(placement.primary, False)
            repaired_results = memory.query("tenant memory", namespace=namespace, top_k=1)
            recalled_after_repair = bool(repaired_results) and repaired_results[0].text == (
                "distributed service shard keeps tenant memory"
            )
            memory.set_node_available(placement.primary, True)
            forget = memory.forget(
                namespace=namespace,
                text="distributed service shard keeps tenant memory",
            )

            tombstone_memory = DistributedShardedWaveMind(
                nodes=[
                    ClusterNode(id="node-a", address="node-a", zone="zone-a"),
                    ClusterNode(id="node-b", address="node-b", zone="zone-b"),
                    ClusterNode(id="node-c", address="node-c", zone="zone-c"),
                ],
                replication_factor=3,
                client=client,
            )
            tombstone_namespace = "tenant:distributed-tombstone"
            tombstone_text = "service repair must not resurrect deleted memory"
            tombstone_memory.remember(tombstone_text, namespace=tombstone_namespace)
            tombstone_placement = tombstone_memory.placement(tombstone_namespace)
            missed_delete = tombstone_placement.replicas[-1]
            tombstone_memory.set_node_available(missed_delete, False)
            tombstone_memory.forget(namespace=tombstone_namespace, text=tombstone_text)
            tombstone_memory.set_node_available(missed_delete, True)
            tombstone_stale_records_before = client._mind(missed_delete).store.count(
                namespace=tombstone_namespace
            )
            tombstone_suppressed_before_repair = (
                tombstone_memory.query(
                    "resurrect deleted memory",
                    namespace=tombstone_namespace,
                    top_k=1,
                )
                == []
            )
            tombstone_repair = tombstone_memory.repair_namespace(tombstone_namespace)
            tombstone_stale_records_after = client._mind(missed_delete).store.count(
                namespace=tombstone_namespace
            )
            tombstone_suppressed_after_repair = (
                tombstone_memory.query(
                    "resurrect deleted memory",
                    namespace=tombstone_namespace,
                    top_k=1,
                )
                == []
            )

            worker_memory = DistributedShardedWaveMind(
                nodes=[
                    ClusterNode(id="node-a", address="node-a", zone="zone-a"),
                    ClusterNode(id="node-b", address="node-b", zone="zone-b"),
                    ClusterNode(id="node-c", address="node-c", zone="zone-c"),
                ],
                replication_factor=3,
                client=client,
            )
            worker_repair_namespace = "tenant:distributed-worker-repair"
            worker_repair_write = worker_memory.remember(
                "anti entropy worker copies missing service replica",
                namespace=worker_repair_namespace,
            )
            worker_missing_node = next(
                node
                for node in worker_repair_write.writes
                if node != worker_repair_write.primary_node
            )
            client._mind(worker_missing_node).forget(
                namespace=worker_repair_namespace,
                text="anti entropy worker copies missing service replica",
            )
            worker_tombstone_namespace = "tenant:distributed-worker-tombstone"
            worker_tombstone_text = "anti entropy worker removes stale deleted memory"
            worker_memory.remember(worker_tombstone_text, namespace=worker_tombstone_namespace)
            worker_tombstone_placement = worker_memory.placement(worker_tombstone_namespace)
            worker_missed_delete = worker_tombstone_placement.replicas[-1]
            worker_memory.set_node_available(worker_missed_delete, False)
            worker_memory.forget(
                namespace=worker_tombstone_namespace,
                text=worker_tombstone_text,
            )
            worker_memory.set_node_available(worker_missed_delete, True)
            worker_report = DistributedRepairWorker(worker_memory).run_once(
                namespaces=(worker_repair_namespace, worker_tombstone_namespace)
            )
            return {
                "engine": "WaveMind distributed sharding",
                "nodes": len(memory.nodes),
                "replication_factor": memory.replication_factor,
                "write_quorum": memory.write_quorum,
                "read_quorum": memory.read_quorum,
                "writes": len(write.writes),
                "primary_node": placement.primary,
                "replica_nodes": list(placement.replicas),
                "recalled_after_primary_loss": recalled_after_primary_loss,
                "repair_missing_before": missing_before_repair,
                "repair_repaired_total": repair.repaired_total,
                "repair_ok": repair.ok,
                "recalled_after_repair": recalled_after_repair,
                "forget_replicated_deletes": forget.deleted,
                "tombstone_replication_factor": tombstone_memory.replication_factor,
                "tombstone_write_quorum": tombstone_memory.write_quorum,
                "tombstone_missed_delete_replica_records": tombstone_stale_records_before,
                "tombstone_suppressed_before_repair": tombstone_suppressed_before_repair,
                "tombstone_repair_canonical_records": tombstone_repair.canonical_records,
                "tombstone_repair_deleted_records": tombstone_repair.tombstone_deleted,
                "tombstone_stale_records_after_repair": tombstone_stale_records_after,
                "tombstone_suppressed_after_repair": tombstone_suppressed_after_repair,
                "anti_entropy_worker_ok": worker_report.ok,
                "anti_entropy_worker_repaired_total": worker_report.repaired_total,
                "anti_entropy_worker_tombstone_deleted": worker_report.tombstone_deleted,
                "write_ms": write_ms,
                "query_after_primary_loss_ms": query_after_primary_loss_ms,
            }
        finally:
            client.close()


def run_distributed_http_sharding_profile() -> dict[str, object]:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        nodes = [
            _start_api_node(root, "node-a"),
            _start_api_node(root, "node-b"),
            _start_api_node(root, "node-c"),
        ]
        client = HTTPNamespaceShardClient(timeout=15.0)
        memory = DistributedShardedWaveMind(
            nodes=[
                ClusterNode(id=node["id"], address=node["address"], zone=node["zone"])
                for node in nodes
            ],
            replication_factor=2,
            client=client,
        )
        by_id = {str(node["id"]): node for node in nodes}
        namespace = "tenant:http-distributed"
        text = "http service shard keeps tenant memory"
        try:
            started = time.perf_counter()
            write = memory.remember(text, namespace=namespace, tags=("ops",), priority=2.0)
            write_ms = (time.perf_counter() - started) * 1000.0
            placement = memory.placement(namespace)
            memory.set_node_available(placement.primary, False)
            query_started = time.perf_counter()
            failover_results = memory.query("tenant memory", namespace=namespace, top_k=1)
            query_after_primary_loss_ms = (time.perf_counter() - query_started) * 1000.0
            recalled_after_primary_loss = bool(failover_results) and failover_results[0].text == text
            memory.set_node_available(placement.primary, True)

            stale_node = next(node for node in write.writes if node != write.primary_node)
            client.forget(
                str(by_id[stale_node]["address"]),
                namespace=namespace,
                text=text,
            )
            memory.set_node_available(write.primary_node, False)
            missing_before_repair = memory.query("tenant memory", namespace=namespace, top_k=1) == []
            memory.set_node_available(write.primary_node, True)

            repair_started = time.perf_counter()
            repair = memory.repair_namespace(namespace, tags=("ops",))
            repair_ms = (time.perf_counter() - repair_started) * 1000.0
            memory.set_node_available(write.primary_node, False)
            repaired_results = memory.query("tenant memory", namespace=namespace, top_k=1)
            recalled_after_repair = bool(repaired_results) and repaired_results[0].text == text
            memory.set_node_available(write.primary_node, True)

            tombstone_memory = DistributedShardedWaveMind(
                nodes=[
                    ClusterNode(id=node["id"], address=node["address"], zone=node["zone"])
                    for node in nodes
                ],
                replication_factor=3,
                client=client,
            )
            tombstone_namespace = "tenant:http-distributed-tombstone"
            tombstone_text = "http service repair must not resurrect deleted memory"
            tombstone_write = tombstone_memory.remember(
                tombstone_text,
                namespace=tombstone_namespace,
            )
            missed_delete = next(
                node for node in tombstone_write.writes if node != tombstone_write.primary_node
            )
            tombstone_memory.set_node_available(missed_delete, False)
            tombstone_memory.forget(namespace=tombstone_namespace, text=tombstone_text)
            tombstone_memory.set_node_available(missed_delete, True)
            stale_before = client.export_namespace(
                str(by_id[missed_delete]["address"]),
                namespace=tombstone_namespace,
            )
            tombstone_suppressed_before_repair = (
                tombstone_memory.query(
                    "resurrect deleted memory",
                    namespace=tombstone_namespace,
                    top_k=1,
                )
                == []
            )
            tombstone_repair = tombstone_memory.repair_namespace(tombstone_namespace)
            stale_after = client.export_namespace(
                str(by_id[missed_delete]["address"]),
                namespace=tombstone_namespace,
            )
            concurrent_namespace = "tenant:http-distributed-concurrent"
            concurrent_texts = [
                f"http concurrent tenant memory item {index:02d}"
                for index in range(12)
            ]
            concurrent_started = time.perf_counter()
            with ThreadPoolExecutor(max_workers=6) as pool:
                concurrent_writes = list(
                    pool.map(
                        lambda item: tombstone_memory.remember(
                            item,
                            namespace=concurrent_namespace,
                        ),
                        concurrent_texts,
                    )
                )
            with ThreadPoolExecutor(max_workers=6) as pool:
                concurrent_hits = list(
                    pool.map(
                        lambda item: any(
                            result.text == item
                            for result in tombstone_memory.query(
                                item,
                                namespace=concurrent_namespace,
                                top_k=3,
                            )
                        ),
                        concurrent_texts,
                    )
                )
            concurrent_ms = (time.perf_counter() - concurrent_started) * 1000.0

            return {
                "engine": "WaveMind distributed HTTP sharding",
                "nodes": len(nodes),
                "replication_factor": tombstone_memory.replication_factor,
                "write_quorum": tombstone_memory.write_quorum,
                "read_quorum": tombstone_memory.read_quorum,
                "proxy_bypass_default": client.trust_env is False,
                "writes": len(write.writes),
                "recalled_after_primary_loss": recalled_after_primary_loss,
                "repair_missing_before": missing_before_repair,
                "repair_ok": repair.ok,
                "repair_repaired_total": repair.repaired_total,
                "recalled_after_repair": recalled_after_repair,
                "tombstone_missed_delete_replica_records": len(stale_before),
                "tombstone_suppressed_before_repair": tombstone_suppressed_before_repair,
                "tombstone_repair_canonical_records": tombstone_repair.canonical_records,
                "tombstone_repair_deleted_records": tombstone_repair.tombstone_deleted,
                "tombstone_stale_records_after_repair": len(stale_after),
                "tombstone_suppressed_after_repair": (
                    tombstone_memory.query(
                        "resurrect deleted memory",
                        namespace=tombstone_namespace,
                        top_k=1,
                    )
                    == []
                ),
                "concurrent_writes": len(concurrent_writes),
                "concurrent_write_ok": all(write.ok for write in concurrent_writes),
                "concurrent_query_hit_rate": sum(1 for hit in concurrent_hits if hit) / len(concurrent_hits),
                "concurrent_ms": concurrent_ms,
                "write_ms": write_ms,
                "query_after_primary_loss_ms": query_after_primary_loss_ms,
                "repair_ms": repair_ms,
            }
        finally:
            _stop_api_nodes(nodes)


def run_sustained_http_cluster_workload(
    nodes: list[ClusterNode | dict[str, object] | str],
    *,
    client: HTTPNamespaceShardClient | None = None,
    engine: str = "WaveMind sustained HTTP cluster load",
    namespace_prefix: str = "tenant:sustained",
    namespace_count: int = 4,
    memories_per_namespace: int = 2,
    replication_factor: int = 3,
    write_quorum: int | None = None,
    read_quorum: int = 1,
    read_fanout: int | None = None,
    max_workers: int = 2,
) -> dict[str, object]:
    if namespace_count <= 0:
        raise ValueError("namespace_count must be positive")
    if memories_per_namespace < 2:
        raise ValueError("memories_per_namespace must be at least 2")
    if max_workers <= 0:
        raise ValueError("max_workers must be positive")

    client = client or HTTPNamespaceShardClient(timeout=15.0)
    memory = DistributedShardedWaveMind(
        nodes=nodes,
        replication_factor=replication_factor,
        write_quorum=write_quorum,
        read_quorum=read_quorum,
        read_fanout=read_fanout,
        client=client,
    )
    by_id = {node.id: node for node in memory.nodes}
    namespaces = [f"{namespace_prefix}:{index:04d}" for index in range(namespace_count)]
    texts = {
        namespace: [
            f"sustained cluster memory {namespace.rsplit(':', 1)[-1]} item {item:04d}"
            for item in range(memories_per_namespace)
        ]
        for namespace in namespaces
    }
    write_latencies: list[float] = []
    query_latencies: list[float] = []
    failover_latencies: list[float] = []
    repair_latencies: list[float] = []
    forget_latencies: list[float] = []
    errors: list[str] = []
    started = time.perf_counter()

    def _address(node_id: str) -> str:
        return str(by_id[node_id].address)

    def _rate(values: list[bool]) -> float:
        return sum(1 for value in values if value) / len(values) if values else 0.0

    write_tasks = [
        (namespace, text)
        for namespace in namespaces
        for text in texts[namespace]
    ]
    write_batch_report = None
    write_started = time.perf_counter()
    try:
        write_batch_report = memory.remember_batch(
            [
                {
                    "text": text,
                    "namespace": namespace,
                    "tags": ["sustained"],
                }
                for namespace, text in write_tasks
            ]
        )
        write_results = [
            result.ok and len(result.writes) >= memory.write_quorum
            for result in write_batch_report.results
        ]
    except Exception as exc:  # pragma: no cover - service boundary
        errors.append(f"write batch: {exc}")
        write_results = [False for _ in write_tasks]
    finally:
        write_latencies.append((time.perf_counter() - write_started) * 1000.0)

    def batch_query_tasks(
        tasks: list[tuple[str, str]],
        latency_bucket: list[float],
        label: str,
        *,
        expect_absent: bool = False,
    ) -> tuple[list[bool], object | None]:
        op_started = time.perf_counter()
        try:
            batch = memory.query_batch(
                [
                    {
                        "text": text,
                        "namespace": namespace,
                        "top_k": 3,
                        "tags": ["sustained"],
                    }
                    for namespace, text in tasks
                ]
            )
            checks = []
            for item_results, (_, text) in zip(batch.results, tasks):
                if expect_absent:
                    checks.append(all(result.text != text for result in item_results))
                else:
                    checks.append(any(result.text == text for result in item_results))
            return checks, batch
        except Exception as exc:  # pragma: no cover - service boundary
            errors.append(f"{label}: {exc}")
            return [False for _ in tasks], None
        finally:
            latency_bucket.append((time.perf_counter() - op_started) * 1000.0)

    query_results, query_batch_report = batch_query_tasks(
        write_tasks,
        query_latencies,
        "query batch",
    )

    failed_node = sorted(node.id for node in memory.nodes)[1]
    memory.set_node_available(failed_node, False)

    failover_results, failover_batch_report = batch_query_tasks(
        write_tasks,
        failover_latencies,
        "failover query batch",
    )
    memory.set_node_available(failed_node, True)

    repair_namespace = namespaces[0]
    repair_text = texts[repair_namespace][0]
    missing_before_repair = False
    repaired_replica = False
    repair_ok = False
    repair_repaired_total = 0
    try:
        repair_placement = memory.placement(repair_namespace)
        missing_replica = next(
            node for node in repair_placement.replicas if node != repair_placement.primary
        )
        client.forget(
            _address(missing_replica),
            namespace=repair_namespace,
            text=repair_text,
        )
        missing_before_repair = not any(
            record.get("text") == repair_text
            for record in client.export_namespace(
                _address(missing_replica),
                namespace=repair_namespace,
            )
        )
        repair_started = time.perf_counter()
        repair_report = memory.repair_namespace(repair_namespace, tags=("sustained",))
        repair_latencies.append((time.perf_counter() - repair_started) * 1000.0)
        repair_ok = repair_report.ok
        repair_repaired_total = repair_report.repaired_total
        repaired_replica = any(
            record.get("text") == repair_text
            for record in client.export_namespace(
                _address(missing_replica),
                namespace=repair_namespace,
            )
        )
    except Exception as exc:  # pragma: no cover - service boundary
        errors.append(f"repair {repair_namespace}: {exc}")

    deleted_tasks = [(namespace, texts[namespace][-1]) for namespace in namespaces]
    forget_batch_report = None
    forget_started = time.perf_counter()
    try:
        forget_batch_report = memory.forget_batch(
            [
                {
                    "namespace": namespace,
                    "text": text,
                }
                for namespace, text in deleted_tasks
            ]
        )
        forget_results = [
            result.deleted >= memory.write_quorum
            for result in forget_batch_report.results
        ]
    except Exception as exc:  # pragma: no cover - service boundary
        errors.append(f"forget batch: {exc}")
        forget_results = [False for _ in deleted_tasks]
    finally:
        forget_latencies.append((time.perf_counter() - forget_started) * 1000.0)

    deletion_suppression, delete_batch_report = batch_query_tasks(
        deleted_tasks,
        query_latencies,
        "delete suppression batch",
        expect_absent=True,
    )

    elapsed_ms = (time.perf_counter() - started) * 1000.0
    all_latencies = (
        write_latencies
        + query_latencies
        + failover_latencies
        + repair_latencies
        + forget_latencies
    )
    successful_checks = (
        sum(1 for ok in write_results if ok)
        + sum(1 for ok in query_results if ok)
        + sum(1 for ok in failover_results if ok)
        + sum(1 for ok in forget_results if ok)
        + sum(1 for ok in deletion_suppression if ok)
        + int(missing_before_repair)
        + int(repair_ok)
        + int(repair_repaired_total >= 1)
        + int(repaired_replica)
    )
    total_checks = (
        len(write_results)
        + len(query_results)
        + len(failover_results)
        + len(forget_results)
        + len(deletion_suppression)
        + 4
    )
    return {
        "engine": engine,
        "nodes": len(memory.nodes),
        "namespaces": len(namespaces),
        "memories_per_namespace": memories_per_namespace,
        "replication_factor": memory.replication_factor,
        "write_quorum": memory.write_quorum,
        "read_quorum": memory.read_quorum,
        "read_fanout": memory.read_fanout,
        "workers": max_workers,
        "writes": len(write_results),
        "queries": len(query_results),
        "failover_queries": len(failover_results),
        "forgets": len(forget_results),
        "write_batches": int(write_batch_report is not None),
        "write_batch_http_requests": (
            int(getattr(write_batch_report, "write_http_requests", 0))
            if write_batch_report is not None
            else 0
        ),
        "write_batch_individual_http_requests": (
            int(getattr(write_batch_report, "individual_write_http_requests", 0))
            if write_batch_report is not None
            else 0
        ),
        "write_batch_request_reduction_ratio": (
            float(getattr(write_batch_report, "request_reduction_ratio", 0.0))
            if write_batch_report is not None
            else 0.0
        ),
        "query_batches": int(query_batch_report is not None),
        "failover_query_batches": int(failover_batch_report is not None),
        "delete_suppression_query_batches": int(delete_batch_report is not None),
        "query_batch_http_requests": (
            int(getattr(query_batch_report, "query_http_requests", 0))
            if query_batch_report is not None
            else 0
        ),
        "query_batch_individual_http_requests": (
            int(getattr(query_batch_report, "individual_query_http_requests", 0))
            if query_batch_report is not None
            else 0
        ),
        "query_batch_request_reduction_ratio": (
            float(getattr(query_batch_report, "request_reduction_ratio", 0.0))
            if query_batch_report is not None
            else 0.0
        ),
        "forget_batches": int(forget_batch_report is not None),
        "forget_batch_http_requests": (
            int(getattr(forget_batch_report, "forget_http_requests", 0))
            if forget_batch_report is not None
            else 0
        ),
        "forget_batch_individual_http_requests": (
            int(getattr(forget_batch_report, "individual_forget_http_requests", 0))
            if forget_batch_report is not None
            else 0
        ),
        "tombstone_batch_http_requests": (
            int(getattr(forget_batch_report, "tombstone_http_requests", 0))
            if forget_batch_report is not None
            else 0
        ),
        "tombstone_batch_individual_http_requests": (
            int(getattr(forget_batch_report, "individual_tombstone_http_requests", 0))
            if forget_batch_report is not None
            else 0
        ),
        "forget_tombstone_batch_http_requests": (
            int(getattr(forget_batch_report, "total_http_requests", 0))
            if forget_batch_report is not None
            else 0
        ),
        "forget_tombstone_batch_individual_http_requests": (
            int(getattr(forget_batch_report, "individual_total_http_requests", 0))
            if forget_batch_report is not None
            else 0
        ),
        "forget_tombstone_batch_request_reduction_ratio": (
            float(getattr(forget_batch_report, "request_reduction_ratio", 0.0))
            if forget_batch_report is not None
            else 0.0
        ),
        "failover_batch_http_requests": (
            int(getattr(failover_batch_report, "query_http_requests", 0))
            if failover_batch_report is not None
            else 0
        ),
        "failover_batch_individual_http_requests": (
            int(getattr(failover_batch_report, "individual_query_http_requests", 0))
            if failover_batch_report is not None
            else 0
        ),
        "failover_batch_request_reduction_ratio": (
            float(getattr(failover_batch_report, "request_reduction_ratio", 0.0))
            if failover_batch_report is not None
            else 0.0
        ),
        "delete_suppression_batch_http_requests": (
            int(getattr(delete_batch_report, "query_http_requests", 0))
            if delete_batch_report is not None
            else 0
        ),
        "delete_suppression_batch_individual_http_requests": (
            int(getattr(delete_batch_report, "individual_query_http_requests", 0))
            if delete_batch_report is not None
            else 0
        ),
        "delete_suppression_batch_request_reduction_ratio": (
            float(getattr(delete_batch_report, "request_reduction_ratio", 0.0))
            if delete_batch_report is not None
            else 0.0
        ),
        "failed_node": failed_node,
        "write_success_rate": _rate(write_results),
        "query_hit_rate": _rate(query_results),
        "failover_hit_rate": _rate(failover_results),
        "forget_success_rate": _rate(forget_results),
        "delete_suppression_rate": _rate(deletion_suppression),
        "repair_missing_before": missing_before_repair,
        "repair_ok": repair_ok,
        "repair_repaired_total": repair_repaired_total,
        "repaired_replica": repaired_replica,
        "success_rate": successful_checks / total_checks if total_checks else 0.0,
        "total_checks": total_checks,
        "errors": errors[:20],
        "error_count": len(errors),
        "elapsed_ms": elapsed_ms,
        "avg_operation_ms": statistics.mean(all_latencies) if all_latencies else 0.0,
        "p95_operation_ms": percentile(all_latencies, 95),
        "p99_operation_ms": percentile(all_latencies, 99),
        "write_avg_ms": statistics.mean(write_latencies) if write_latencies else 0.0,
        "write_p99_ms": percentile(write_latencies, 99),
        "query_batch_avg_ms": statistics.mean(query_latencies) if query_latencies else 0.0,
        "query_batch_p99_ms": percentile(query_latencies, 99),
        "failover_batch_avg_ms": (
            statistics.mean(failover_latencies) if failover_latencies else 0.0
        ),
        "failover_batch_p99_ms": percentile(failover_latencies, 99),
        "repair_avg_ms": statistics.mean(repair_latencies) if repair_latencies else 0.0,
        "repair_p99_ms": percentile(repair_latencies, 99),
        "forget_avg_ms": statistics.mean(forget_latencies) if forget_latencies else 0.0,
        "forget_p99_ms": percentile(forget_latencies, 99),
    }


def run_sustained_http_cluster_load_profile() -> dict[str, object]:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        nodes = [
            _start_api_node(root, "node-a"),
            _start_api_node(root, "node-b"),
            _start_api_node(root, "node-c"),
            _start_api_node(root, "node-d"),
        ]
        try:
            return run_sustained_http_cluster_workload(
                [
                    ClusterNode(id=node["id"], address=node["address"], zone=node["zone"])
                    for node in nodes
                ],
                client=HTTPNamespaceShardClient(timeout=15.0),
                engine="WaveMind sustained HTTP cluster load",
                namespace_prefix="tenant:sustained",
                namespace_count=4,
                memories_per_namespace=2,
                replication_factor=3,
                read_fanout=1,
                max_workers=2,
            )
        finally:
            _stop_api_nodes(nodes)


def run_replication_runtime_profile() -> dict[str, object]:
    latencies: list[float] = []
    with tempfile.TemporaryDirectory() as directory:
        memory = ReplicatedWaveMind(
            root_path=Path(directory) / "replicas",
            nodes=[
                {"id": "node-a", "address": "127.0.0.1:8101", "zone": "zone-a"},
                {"id": "node-b", "address": "127.0.0.1:8102", "zone": "zone-b"},
                {"id": "node-c", "address": "127.0.0.1:8103", "zone": "zone-c"},
            ],
            replication_factor=3,
            width=16,
            height=16,
            layers=1,
            encoder=HashingTextEncoder(vector_dim=64),
        )
        try:
            namespace = "tenant:replicated"
            write = memory.remember(
                "replicated user memory survives one node loss",
                namespace=namespace,
            )
            placement = memory.placement(namespace)
            lost_node = placement.primary
            memory.set_node_available(lost_node, False)
            started = time.perf_counter()
            results = memory.query("survives node loss", namespace=namespace, top_k=1)
            latencies.append((time.perf_counter() - started) * 1000.0)
            recalled_after_loss = bool(results) and results[0].text == (
                "replicated user memory survives one node loss"
            )

            partial = ReplicatedWaveMind(
                root_path=Path(directory) / "partial",
                nodes=[
                    {"id": "node-a", "address": "127.0.0.1:8101", "zone": "zone-a"},
                    {"id": "node-b", "address": "127.0.0.1:8102", "zone": "zone-b"},
                    {"id": "node-c", "address": "127.0.0.1:8103", "zone": "zone-c"},
                ],
                replication_factor=3,
                write_quorum=1,
                width=16,
                height=16,
                layers=1,
                encoder=HashingTextEncoder(vector_dim=64),
            )
            try:
                partial_placement = partial.placement(namespace)
                recovering_node = partial_placement.replicas[-1]
                partial.set_node_available(recovering_node, False)
                partial.remember("repair copies missing replica state", namespace=namespace)
                partial.set_node_available(recovering_node, True)
                repair = partial.repair_namespace(namespace)
            finally:
                partial.close()

            tombstone = ReplicatedWaveMind(
                root_path=Path(directory) / "tombstone",
                nodes=[
                    {"id": "node-a", "address": "127.0.0.1:8101", "zone": "zone-a"},
                    {"id": "node-b", "address": "127.0.0.1:8102", "zone": "zone-b"},
                    {"id": "node-c", "address": "127.0.0.1:8103", "zone": "zone-c"},
                ],
                replication_factor=3,
                width=16,
                height=16,
                layers=1,
                encoder=HashingTextEncoder(vector_dim=64),
            )
            try:
                tombstone_placement = tombstone.placement(namespace)
                missed_delete = tombstone_placement.replicas[-1]
                tombstone.remember("repair must not resurrect deleted memory", namespace=namespace)
                tombstone.set_node_available(missed_delete, False)
                tombstone.forget(
                    text="repair must not resurrect deleted memory",
                    namespace=namespace,
                )
                tombstone.set_node_available(missed_delete, True)
                suppressed_before_repair = (
                    tombstone.query("resurrect deleted memory", namespace=namespace, top_k=1)
                    == []
                )
                tombstone_repair = tombstone.repair_namespace(namespace)
                suppressed_after_repair = (
                    tombstone.query("resurrect deleted memory", namespace=namespace, top_k=1)
                    == []
                )
            finally:
                tombstone.close()

            concurrent = ReplicatedWaveMind(
                root_path=Path(directory) / "concurrent",
                nodes=[
                    {"id": "node-a", "address": "127.0.0.1:8101", "zone": "zone-a"},
                    {"id": "node-b", "address": "127.0.0.1:8102", "zone": "zone-b"},
                    {"id": "node-c", "address": "127.0.0.1:8103", "zone": "zone-c"},
                ],
                replication_factor=3,
                width=16,
                height=16,
                layers=1,
                encoder=HashingTextEncoder(vector_dim=64),
            )
            try:
                concurrent_namespace = "tenant:replicated-concurrent"
                concurrent_texts = [
                    f"replicated concurrent memory item {index:02d}"
                    for index in range(12)
                ]

                def write_concurrent(text: str):
                    return concurrent.remember(text, namespace=concurrent_namespace)

                def query_concurrent(text: str) -> bool:
                    results = concurrent.query(
                        text,
                        namespace=concurrent_namespace,
                        top_k=1,
                    )
                    return bool(results) and results[0].text == text

                concurrent_started = time.perf_counter()
                with ThreadPoolExecutor(max_workers=6) as pool:
                    concurrent_writes = list(pool.map(write_concurrent, concurrent_texts))
                with ThreadPoolExecutor(max_workers=6) as pool:
                    concurrent_hits = list(pool.map(query_concurrent, concurrent_texts))
                concurrent_ms = (time.perf_counter() - concurrent_started) * 1000.0
            finally:
                concurrent.close()

            return {
                "engine": "WaveMind replicated runtime",
                "nodes": 3,
                "replication_factor": 3,
                "write_quorum": memory.write_quorum,
                "read_quorum": memory.read_quorum,
                "writes": len(write.writes),
                "recalled_after_node_loss": recalled_after_loss,
                "repair_copied_records": repair.copied_records,
                "tombstone_suppressed_before_repair": suppressed_before_repair,
                "tombstone_suppressed_after_repair": suppressed_after_repair,
                "tombstone_repair_deleted_records": tombstone_repair.deleted_records,
                "concurrent_writes": len(concurrent_writes),
                "concurrent_write_ok": all(write.ok for write in concurrent_writes),
                "concurrent_query_hit_rate": (
                    sum(1 for hit in concurrent_hits if hit) / len(concurrent_hits)
                ),
                "concurrent_ms": concurrent_ms,
                "avg_query_after_loss_ms": statistics.mean(latencies),
                "p99_query_after_loss_ms": percentile(latencies, 99),
            }
        finally:
            memory.close()


def run_active_active_delta_profile() -> dict[str, object]:
    with tempfile.TemporaryDirectory() as directory:
        kwargs = {
            "replication_factor": 3,
            "width": 16,
            "height": 16,
            "layers": 1,
            "encoder": HashingTextEncoder(vector_dim=64),
        }
        region_a = ReplicatedWaveMind(
            root_path=Path(directory) / "region-a",
            nodes=[
                {"id": "region-a-1", "address": "127.0.0.1:8101", "zone": "zone-a"},
                {"id": "region-a-2", "address": "127.0.0.1:8102", "zone": "zone-b"},
                {"id": "region-a-3", "address": "127.0.0.1:8103", "zone": "zone-c"},
            ],
            **kwargs,
        )
        region_b = ReplicatedWaveMind(
            root_path=Path(directory) / "region-b",
            nodes=[
                {"id": "region-b-1", "address": "127.0.0.1:8201", "zone": "zone-a"},
                {"id": "region-b-2", "address": "127.0.0.1:8202", "zone": "zone-b"},
                {"id": "region-b-3", "address": "127.0.0.1:8203", "zone": "zone-c"},
            ],
            **kwargs,
        )
        try:
            namespace = "tenant:active-active"
            region_a.remember("region a billing preference", namespace=namespace)
            region_b.remember("region b support preference", namespace=namespace)
            sync_started = time.perf_counter()
            sync_b = sync_namespace_delta(region_a, region_b, namespace)
            sync_a = sync_namespace_delta(region_b, region_a, namespace)
            sync_ms = (time.perf_counter() - sync_started) * 1000.0
            converged = (
                region_a.query("support preference", namespace=namespace, top_k=1)
                and region_b.query("billing preference", namespace=namespace, top_k=1)
            )

            region_a.remember("region a latency preference", namespace=namespace)
            incremental = sync_namespace_delta(
                region_a,
                region_b,
                namespace,
                since=sync_b.to_cursor,
            )
            incremental_converged = (
                region_b.query("latency preference", namespace=namespace, top_k=1)[0].text
                == "region a latency preference"
            )
            region_a.query("latency preference", namespace=namespace, top_k=1)
            field_only_delta = region_a.export_namespace_delta(
                namespace,
                since=incremental.to_cursor,
            )
            field_only = sync_namespace_delta(
                region_a,
                region_b,
                namespace,
                since=incremental.to_cursor,
            )

            stale_delta = region_b.export_namespace_delta(namespace)
            region_a.forget(text="region a billing preference", namespace=namespace)
            region_a.import_namespace_delta(stale_delta)
            suppressed_stale_import = all(
                result.text != "region a billing preference"
                for result in region_a.query("billing preference", namespace=namespace, top_k=3)
            )
            tombstone_delta = region_a.export_namespace_delta(namespace)
            tombstone_report = region_b.import_namespace_delta(tombstone_delta)
            tombstone_converged = all(
                result.text != "region a billing preference"
                for result in region_b.query("billing preference", namespace=namespace, top_k=3)
            )
            return {
                "engine": "WaveMind active-active delta sync",
                "regions": 2,
                "replication_factor_per_region": 3,
                "records_imported": sync_a.imported_records + sync_b.imported_records,
                "converged_after_bidirectional_sync": bool(converged),
                "sync_ms": sync_ms,
                "incremental_from_cursor": sync_b.to_cursor,
                "incremental_to_cursor": incremental.to_cursor,
                "incremental_records_exported": incremental.exported_records,
                "incremental_records_imported": incremental.imported_records,
                "incremental_skipped_records": incremental.skipped_records,
                "incremental_converged": incremental_converged,
                "field_only_records_exported": len(field_only_delta["records"]),
                "field_only_keys_exported": field_only.exported_field_keys,
                "field_only_imported_records": field_only.imported_records,
                "suppressed_stale_import_after_delete": suppressed_stale_import,
                "tombstone_deleted_records": tombstone_report.deleted_records,
                "tombstone_converged": tombstone_converged,
            }
        finally:
            region_a.close()
            region_b.close()


def _benchmark_active_region(root: Path, name: str) -> ReplicatedWaveMind:
    return ReplicatedWaveMind(
        root_path=root / name,
        nodes=[
            {"id": f"{name}-a", "address": f"{name}-a.internal", "zone": "zone-a"},
            {"id": f"{name}-b", "address": f"{name}-b.internal", "zone": "zone-b"},
            {"id": f"{name}-c", "address": f"{name}-c.internal", "zone": "zone-c"},
        ],
        replication_factor=3,
        width=16,
        height=16,
        layers=1,
        encoder=HashingTextEncoder(vector_dim=64),
    )


def run_sustained_active_active_sync_profile() -> dict[str, object]:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        regions = {
            name: _benchmark_active_region(root, name)
            for name in ("region-a", "region-b", "region-c")
        }
        namespaces = tuple(f"tenant:active-active-sustained:{index}" for index in range(3))
        expected: dict[str, set[str]] = {namespace: set() for namespace in namespaces}
        reports = []
        sync_latencies: list[float] = []
        write_count = 0
        try:
            worker = ActiveActiveSyncWorker(regions)
            for round_index in range(2):
                for region_name, region in regions.items():
                    for namespace_index, namespace in enumerate(namespaces):
                        text = (
                            f"{region_name} sustained round {round_index} "
                            f"namespace {namespace_index} memory"
                        )
                        region.remember(text, namespace=namespace)
                        expected[namespace].add(text)
                        write_count += 1
                report = worker.run_once(namespaces=namespaces)
                reports.append(report)
                sync_latencies.append(report.duration_ms)

            total_expected = 0
            total_hits = 0
            for namespace, texts in expected.items():
                for text in texts:
                    total_expected += len(regions)
                    for region in regions.values():
                        results = region.query(text, namespace=namespace, top_k=3)
                        if any(result.text == text for result in results):
                            total_hits += 1
            convergence_rate = total_hits / total_expected if total_expected else 0.0

            deleted_namespace = namespaces[0]
            deleted_text = "region-b sustained round 0 namespace 0 memory"
            regions["region-b"].forget(text=deleted_text, namespace=deleted_namespace)
            expected[deleted_namespace].discard(deleted_text)
            tombstone_report = worker.run_once(namespaces=namespaces)
            reports.append(tombstone_report)
            sync_latencies.append(tombstone_report.duration_ms)
            delete_checks = []
            for region in regions.values():
                results = region.query(deleted_text, namespace=deleted_namespace, top_k=3)
                delete_checks.append(all(result.text != deleted_text for result in results))
            delete_suppression_rate = sum(1 for item in delete_checks if item) / len(delete_checks)

            hot_text = "region-c sustained round 1 namespace 1 memory"
            for _ in range(3):
                regions["region-c"].query(hot_text, namespace=namespaces[1], top_k=1)
            field_report = worker.run_once(namespaces=namespaces)
            reports.append(field_report)
            sync_latencies.append(field_report.duration_ms)

            final_report = worker.run_once(namespaces=namespaces)
            reports.append(final_report)
            sync_latencies.append(final_report.duration_ms)

            pair_reports = [
                pair
                for report in reports
                for pair in report.pair_reports
            ]
            total_pairs = len(pair_reports)
            ok_pairs = sum(1 for pair in pair_reports if pair.ok)
            success_rate = ok_pairs / total_pairs if total_pairs else 0.0
            return {
                "engine": "WaveMind sustained active-active sync",
                "regions": len(regions),
                "namespaces": len(namespaces),
                "replication_factor_per_region": 3,
                "writes": write_count,
                "sync_cycles": len(reports),
                "pair_syncs": total_pairs,
                "cursor_count": len(worker.cursors),
                "records_imported": sum(report.records_imported for report in reports),
                "tombstones_imported": sum(report.tombstones_imported for report in reports),
                "deleted_records": sum(report.deleted_records for report in reports),
                "field_keys_exported": sum(report.exported_field_keys for report in reports),
                "final_noop_records_imported": final_report.records_imported,
                "final_noop_failed_pairs": final_report.failed_pairs,
                "convergence_rate": convergence_rate,
                "delete_suppression_rate": delete_suppression_rate,
                "success_rate": success_rate,
                "failed_pairs": sum(report.failed_pairs for report in reports),
                "has_more_pairs": sum(report.has_more_pairs for report in reports),
                "p99_sync_ms": percentile(sync_latencies, 99),
                "avg_sync_ms": statistics.mean(sync_latencies) if sync_latencies else 0.0,
            }
        finally:
            for region in regions.values():
                region.close()


def run_http_active_active_service_region_profile() -> dict[str, object]:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        memories = {
            name: _benchmark_active_region(root, name)
            for name in ("svc-region-a", "svc-region-b", "svc-region-c")
        }
        addresses = {
            name: f"http://{name}.local"
            for name in memories
        }
        client = FastAPIReplicatedRegionClient(
            {addresses[name]: memory for name, memory in memories.items()}
        )
        namespaces = tuple(f"tenant:http-active-active:{index}" for index in range(2))
        expected: dict[str, set[str]] = {namespace: set() for namespace in namespaces}
        reports = []
        sync_latencies: list[float] = []
        write_count = 0
        try:
            worker = HTTPActiveActiveSyncWorker(addresses, client=client)
            for region_name, memory in memories.items():
                for namespace_index, namespace in enumerate(namespaces):
                    text = f"{region_name} service region namespace {namespace_index} memory"
                    memory.remember(text, namespace=namespace)
                    expected[namespace].add(text)
                    write_count += 1

            first_report = worker.run_once(namespaces=namespaces)
            reports.append(first_report)
            sync_latencies.append(first_report.duration_ms)

            total_expected = 0
            total_hits = 0
            for namespace, texts in expected.items():
                for text in texts:
                    total_expected += len(memories)
                    for memory in memories.values():
                        results = memory.query(text, namespace=namespace, top_k=3)
                        if any(result.text == text for result in results):
                            total_hits += 1
            convergence_rate = total_hits / total_expected if total_expected else 0.0

            deleted_namespace = namespaces[0]
            deleted_text = "svc-region-b service region namespace 0 memory"
            memories["svc-region-b"].forget(text=deleted_text, namespace=deleted_namespace)
            expected[deleted_namespace].discard(deleted_text)
            tombstone_report = worker.run_once(namespaces=namespaces)
            reports.append(tombstone_report)
            sync_latencies.append(tombstone_report.duration_ms)
            delete_checks = []
            for memory in memories.values():
                results = memory.query(deleted_text, namespace=deleted_namespace, top_k=3)
                delete_checks.append(all(result.text != deleted_text for result in results))
            delete_suppression_rate = sum(1 for item in delete_checks if item) / len(delete_checks)

            hot_text = "svc-region-c service region namespace 1 memory"
            for _ in range(2):
                memories["svc-region-c"].query(hot_text, namespace=namespaces[1], top_k=1)
            field_report = worker.run_once(namespaces=namespaces)
            reports.append(field_report)
            sync_latencies.append(field_report.duration_ms)

            final_report = worker.run_once(namespaces=namespaces)
            reports.append(final_report)
            sync_latencies.append(final_report.duration_ms)

            pair_reports = [
                pair
                for report in reports
                for pair in report.pair_reports
            ]
            total_pairs = len(pair_reports)
            ok_pairs = sum(1 for pair in pair_reports if pair.ok)
            success_rate = ok_pairs / total_pairs if total_pairs else 0.0
            return {
                "engine": "WaveMind HTTP active-active service-region sync",
                "service_boundary": "FastAPI TestClient",
                "api_export_endpoint": "/namespace-delta/export",
                "api_import_endpoint": "/namespace-delta/import",
                "regions": len(memories),
                "namespaces": len(namespaces),
                "replication_factor_per_region": 3,
                "writes": write_count,
                "sync_cycles": len(reports),
                "pair_syncs": total_pairs,
                "cursor_count": len(worker.cursors),
                "export_calls": client.export_calls,
                "import_calls": client.import_calls,
                "records_imported": sum(report.records_imported for report in reports),
                "tombstones_imported": sum(report.tombstones_imported for report in reports),
                "deleted_records": sum(report.deleted_records for report in reports),
                "field_keys_exported": sum(report.exported_field_keys for report in reports),
                "final_noop_records_imported": final_report.records_imported,
                "final_noop_failed_pairs": final_report.failed_pairs,
                "convergence_rate": convergence_rate,
                "delete_suppression_rate": delete_suppression_rate,
                "success_rate": success_rate,
                "failed_pairs": sum(report.failed_pairs for report in reports),
                "has_more_pairs": sum(report.has_more_pairs for report in reports),
                "p99_sync_ms": percentile(sync_latencies, 99),
                "avg_sync_ms": statistics.mean(sync_latencies) if sync_latencies else 0.0,
            }
        finally:
            client.close()
            for memory in memories.values():
                memory.close()


def run_field_crdt_profile() -> dict[str, object]:
    namespace = "tenant:field-crdt"
    budget_key = stable_memory_key(namespace=namespace, text="user budget is 2000")
    stale_key = stable_memory_key(namespace=namespace, text="user old city is Berlin")
    report_key = stable_memory_key(namespace=namespace, text="user wants weekly reports")

    region_a = FieldStateCRDT(namespace=namespace, actor="region-a")
    region_b = FieldStateCRDT(namespace=namespace, actor="region-b")
    region_c = FieldStateCRDT(namespace=namespace, actor="region-c")

    started = time.perf_counter()
    region_a.boost(budget_key, 3.0, observed_at=10.0)
    region_a.boost(report_key, 1.0, observed_at=11.0)
    region_b.boost(budget_key, 2.0, observed_at=12.0)
    region_b.suppress(report_key, 0.25, observed_at=13.0)
    region_c.boost(stale_key, 5.0, observed_at=14.0)
    region_a.tombstone(stale_key, deleted_at=100.0)

    left = FieldStateCRDT(namespace=namespace, actor="left")
    left.merge(region_a.delta())
    left.merge(region_b.delta())
    left.merge(region_c.delta())
    left.merge(region_b.delta())

    right = FieldStateCRDT(namespace=namespace, actor="right")
    right.merge(region_c.delta())
    right.merge(region_b.delta())
    right.merge(region_a.delta())
    right.merge(region_a.delta())
    merge_ms = (time.perf_counter() - started) * 1000.0

    left_payload = left.to_dict()
    right_payload = right.to_dict()
    same_state = (
        left_payload["positive"] == right_payload["positive"]
        and left_payload["negative"] == right_payload["negative"]
        and left_payload["tombstones"] == right_payload["tombstones"]
        and left_payload["watermarks"] == right_payload["watermarks"]
    )
    partial_budget_delta = left.delta(keys=[budget_key])
    healthy_watermarks = audit_field_state_watermarks(
        {"left": left, "right": right},
        expected_actors=left.covered_actors(),
    )
    lagging_region = FieldStateCRDT(namespace=namespace, actor="lagging")
    lagging_region.merge(region_a.delta())
    missing_watermarks = audit_field_state_watermarks(
        {"left": left, "lagging": lagging_region},
        expected_actors=left.covered_actors(),
    )
    stale_region = FieldStateCRDT(namespace=namespace, actor="stale")
    stale_region.boost(budget_key, actor="region-a", observed_at=90.0)
    stale_region.boost(budget_key, actor="region-b", observed_at=13.0)
    stale_region.boost(stale_key, actor="region-c", observed_at=14.0)
    stale_watermarks = audit_field_state_watermarks(
        {"left": left, "stale": stale_region},
        expected_actors=left.covered_actors(),
        max_lag_seconds=5.0,
    )
    return {
        "engine": "WaveMind field-state CRDT",
        "regions": 3,
        "commutative_convergence": same_state,
        "idempotent_remerge": left.merge(region_b.delta()).changed is False,
        "tombstone_wins": left.activation(stale_key) == 0.0 and left.is_tombstoned(stale_key),
        "top_key_converged": left.top(limit=1) == right.top(limit=1),
        "watermark_convergence": left_payload["watermarks"] == right_payload["watermarks"],
        "watermark_actors": len(left.covered_actors()),
        "max_watermark": left.watermark(),
        "partial_delta_watermark_actors": sorted(partial_budget_delta.watermarks),
        "watermark_health_ok": healthy_watermarks.healthy,
        "watermark_health_status": healthy_watermarks.status,
        "watermark_health_regions": healthy_watermarks.region_count,
        "watermark_health_max_observed_lag": healthy_watermarks.max_observed_lag_seconds,
        "watermark_missing_detected": bool(missing_watermarks.missing_by_region["lagging"]),
        "watermark_lag_detected": bool(stale_watermarks.stale_by_region["stale"]),
        "budget_activation": left.activation(budget_key),
        "suppressed_report_activation": left.activation(report_key),
        "merge_ms": merge_ms,
    }


def run_replicated_snapshot_profile() -> dict[str, object]:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        memory = ReplicatedWaveMind(
            root_path=root / "replicas",
            nodes=[
                {"id": "node-a", "address": "127.0.0.1:8101", "zone": "zone-a"},
                {"id": "node-b", "address": "127.0.0.1:8102", "zone": "zone-b"},
                {"id": "node-c", "address": "127.0.0.1:8103", "zone": "zone-c"},
            ],
            replication_factor=3,
            width=16,
            height=16,
            layers=1,
            encoder=HashingTextEncoder(vector_dim=64),
        )
        try:
            namespace = "tenant:snapshot"
            memory.remember(
                "replicated snapshot restore survives node loss",
                namespace=namespace,
            )
            snapshot_started = time.perf_counter()
            object_store = S3SnapshotStore.from_uri(
                "s3://wavemind-benchmark/replicated",
                client=InMemoryS3Client(),
            )
            for index in range(2):
                old_archive = root / f"old-object-archive-{index}.tar.gz"
                old_archive.write_bytes(f"old-object-archive-{index}".encode("utf-8"))
                object_store.upload_archive(old_archive)
            snapshot_job = ReplicatedSnapshotWorker(memory).run_once(
                destination=root / "snapshots",
                offsite_destination=root / "offsite",
                archive_destination=root / "archives",
                object_store_destination="s3://wavemind-benchmark/replicated",
                object_store=object_store,
                keep_last=2,
                object_store_keep_last=1,
            )
            snapshot_ms = (time.perf_counter() - snapshot_started) * 1000.0
            health = ReplicatedWaveMind.verify_snapshot(snapshot_job.snapshot_path)
            latest_object_archive = object_store.latest_archive()

            restore_started = time.perf_counter()
            drill = ReplicatedObjectStoreDrillWorker(object_store).run_once(
                source="s3://wavemind-benchmark/replicated",
                destination=root / "restored",
                download_destination=root / "object-store-downloads",
                namespace=namespace,
                query="snapshot restore node loss",
                expected_text="replicated snapshot restore survives node loss",
                width=16,
                height=16,
                layers=1,
                encoder=HashingTextEncoder(vector_dim=64),
            )
            restore_ms = (time.perf_counter() - restore_started) * 1000.0
            return {
                "engine": "WaveMind replicated snapshot",
                "nodes": len(snapshot_job.nodes),
                "manifest_healthy": health["healthy"],
                "offsite_verified": snapshot_job.offsite_verified,
                "archive_verified": snapshot_job.archive_verified,
                "object_store_verified": bool(
                    snapshot_job.object_store_upload
                    and snapshot_job.object_store_upload.verified
                ),
                "object_store_latest_verified": bool(
                    latest_object_archive and latest_object_archive.verified
                ),
                "object_store_pruned": len(snapshot_job.pruned_object_store),
                "object_store_download_verified": (
                    drill.download_matches_object and drill.archive_verified
                ),
                "object_store_drill_ok": drill.ok,
                "total_bytes": snapshot_job.total_bytes,
                "snapshot_ms": snapshot_ms,
                "restore_ms": restore_ms,
                "restored_files": drill.restored_files,
                "recalled_after_restore_node_loss": bool(
                    drill.recalled_after_primary_loss
                ),
            }
        finally:
            memory.close()


def run_recovery_journal_profile() -> dict[str, object]:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        journal_path = root / "recovery.jsonl"
        namespace = "tenant:pitr"
        memory = WaveMind(
            db_path=root / "source.sqlite3",
            encoder=HashingTextEncoder(vector_dim=64),
            width=16,
            height=16,
            layers=1,
            recovery_journal_path=journal_path,
        )
        full_restored = None
        point_restored = None
        try:
            first_id = memory.remember(
                "point in time recovery keeps the first checkpoint",
                namespace=namespace,
                tags=["pitr"],
                metadata={"checkpoint": "first"},
            )
            journal_entries = [
                json.loads(line)
                for line in journal_path.read_text(encoding="utf-8").splitlines()
                if line.strip()
            ]
            first_checkpoint = float(journal_entries[-1]["created_at"])
            time.sleep(0.001)
            second_id = memory.remember(
                "full replay keeps the second durable memory",
                namespace=namespace,
                tags=["pitr"],
            )
            expired_id = memory.remember(
                "expired pitr memory should not survive full replay",
                namespace=namespace,
                ttl_seconds=-1,
            )
            forgotten = memory.forget(id=first_id, namespace=namespace)
            purged = memory.purge_expired()

            full_started = time.perf_counter()
            full_report = SQLiteMemoryStore.restore_recovery_journal(
                journal_path,
                root / "full-restore.sqlite3",
            )
            full_restore_ms = (time.perf_counter() - full_started) * 1000.0
            full_restored = WaveMind(
                db_path=root / "full-restore.sqlite3",
                encoder=HashingTextEncoder(vector_dim=64),
                width=16,
                height=16,
                layers=1,
            )
            full_results = full_restored.query(
                "second durable memory",
                namespace=namespace,
                top_k=1,
            )
            full_restore_ok = (
                forgotten == 1
                and purged == 1
                and full_report.deleted_records == 2
                and full_report.restored_records == 1
                and full_restored.store.get(first_id) is None
                and full_restored.store.get(expired_id) is None
                and bool(full_results)
                and full_results[0].id == second_id
            )

            point_started = time.perf_counter()
            point_report = SQLiteMemoryStore.restore_recovery_journal(
                journal_path,
                root / "point-restore.sqlite3",
                until=first_checkpoint,
            )
            point_restore_ms = (time.perf_counter() - point_started) * 1000.0
            point_restored = WaveMind(
                db_path=root / "point-restore.sqlite3",
                encoder=HashingTextEncoder(vector_dim=64),
                width=16,
                height=16,
                layers=1,
            )
            point_record = point_restored.store.get(first_id)
            point_restore_ok = (
                point_report.applied_entries == 1
                and point_report.skipped_entries >= 1
                and point_report.restored_records == 1
                and point_record is not None
                and point_record.metadata == {"checkpoint": "first"}
                and point_restored.store.get(second_id) is None
            )

            entries = [
                json.loads(line)
                for line in journal_path.read_text(encoding="utf-8").splitlines()
                if line.strip()
            ]
            return {
                "engine": "WaveMind recovery journal",
                "journal_entries": len(entries),
                "journal_bytes": journal_path.stat().st_size,
                "actions": [entry["action"] for entry in entries],
                "full_restore_ok": full_restore_ok,
                "point_in_time_restore_ok": point_restore_ok,
                "full_restore_ms": full_restore_ms,
                "point_in_time_restore_ms": point_restore_ms,
                "full_applied_entries": full_report.applied_entries,
                "full_deleted_records": full_report.deleted_records,
                "full_restored_records": full_report.restored_records,
                "point_applied_entries": point_report.applied_entries,
                "point_skipped_entries": point_report.skipped_entries,
                "point_restored_records": point_report.restored_records,
                "vector_dim_preserved": (
                    int(point_record.vector.shape[0])
                    if point_record is not None
                    else 0
                ),
                "pattern_shape_preserved": (
                    list(point_record.pattern.shape)
                    if point_record is not None
                    else []
                ),
            }
        finally:
            memory.close()
            if full_restored is not None:
                full_restored.close()
            if point_restored is not None:
                point_restored.close()


def run_multimodal_profile() -> dict[str, object]:
    with tempfile.TemporaryDirectory() as directory:
        memory = WaveMind(
            db_path=Path(directory) / "payloads.sqlite3",
            encoder=HashingTextEncoder(vector_dim=64),
            width=16,
            height=16,
            layers=1,
        )
        try:
            layer = CrossModalMemoryLayer(memory, vector_dim=64)
            asset_store = S3AssetStore.from_uri(
                "s3://wavemind-assets/media",
                client=InMemoryS3Client(),
            )
            demo_video_asset = asset_store.put_asset_bytes(
                b"memory-field-demo-video-bytes",
                filename="memory-field-demo.mp4",
                media_type="video/mp4",
                kind="video",
            )
            described_video_asset = asset_store.describe_asset(demo_video_asset.uri)
            expected = {
                "enterprise expansion chart": layer.remember(
                    image_payload(
                        "s3://demo/revenue-chart.png",
                        caption="enterprise expansion revenue chart",
                        tags=["report"],
                    ),
                    namespace="scale",
                ),
                "SSO audit log call": layer.remember(
                    audio_payload(
                        "support-call.wav",
                        transcript="customer requested SSO and audit log export",
                        tags=["call"],
                    ),
                    namespace="scale",
                ),
                "ARR enterprise table": layer.remember(
                    table_payload(
                        [{"segment": "enterprise", "arr": 2000}],
                        title="ARR by segment",
                        tags=["table"],
                    ),
                    namespace="scale",
                ),
                "upgraded enterprise plan": layer.remember(
                    event_payload(
                        "account upgraded to enterprise plan",
                        actor="tenant:acme",
                        properties={"plan": "enterprise"},
                        tags=["event"],
                    ),
                    namespace="scale",
                ),
                "memory graph stale fact suppression": layer.remember(
                    video_payload(
                        demo_video_asset.uri,
                        summary="agent memory graph heatmap demo",
                        transcript="the agent suppresses stale facts after user corrections",
                        scenes=["memory graph heatmap", "stale fact suppression"],
                        duration_seconds=38.0,
                        metadata=demo_video_asset.payload_metadata(),
                        tags=["video"],
                    ),
                    namespace="scale",
                ),
                "warehouse robot arm picking": layer.remember(
                    asset3d_payload(
                        "s3://demo/robot-arm.glb",
                        description="3D robot arm for warehouse picking simulation",
                        format="glb",
                        labels=["robot arm", "warehouse", "picking"],
                        dimensions={"unit": "m", "height": 1.2},
                        tags=["asset"],
                    ),
                    namespace="scale",
                ),
                "trading agent uses WaveMind memory": layer.remember(
                    graph_payload(
                        [
                            ("Andrey", "works_on", "trading agent"),
                            ("trading agent", "uses", "WaveMind memory"),
                        ],
                        title="agent knowledge graph",
                        summary="Andrey's trading agent uses WaveMind memory",
                        tags=["graph"],
                    ),
                    namespace="scale",
                ),
            }
            latencies = []
            correct = 0
            for query, expected_id in expected.items():
                started = time.perf_counter()
                results = memory.query(query, namespace="scale", top_k=1)
                latencies.append((time.perf_counter() - started) * 1000.0)
                if results and results[0].id == expected_id:
                    correct += 1
            cross_modal_checks = [
                ("visual chart for enterprise revenue expansion", "image", expected["enterprise expansion chart"]),
                ("voice call where customer requested SSO audit logs", "audio", expected["SSO audit log call"]),
                ("spreadsheet rows for enterprise ARR metrics", "table", expected["ARR enterprise table"]),
                ("timeline event where account upgraded plan", "event", expected["upgraded enterprise plan"]),
                ("video scene about stale fact suppression", "video", expected["memory graph stale fact suppression"]),
                ("3D warehouse robot arm model", "3d", expected["warehouse robot arm picking"]),
                ("knowledge graph relation trading agent uses memory", "graph", expected["trading agent uses WaveMind memory"]),
            ]
            cross_latencies = []
            cross_correct = 0
            provenance_complete = 0
            asset_manifest_provenance = 0
            for query, modality, expected_id in cross_modal_checks:
                started = time.perf_counter()
                results = layer.query(
                    query,
                    namespace="scale",
                    target_modality=modality,
                    top_k=1,
                )
                cross_latencies.append((time.perf_counter() - started) * 1000.0)
                if results and results[0].id == expected_id:
                    cross_correct += 1
                if results and results[0].provenance.get("memory_id") == results[0].id:
                    provenance_complete += 1
                if (
                    results
                    and modality == "video"
                    and results[0].provenance.get("asset_sha256") == demo_video_asset.sha256
                    and results[0].provenance.get("asset_bytes") == demo_video_asset.total_bytes
                    and results[0].provenance.get("asset_media_type") == "video/mp4"
                    and results[0].provenance.get("asset_verified") is True
                ):
                    asset_manifest_provenance += 1
            descriptor_records = memory.store.list(namespace="scale", tags=["multimodal"])
            persisted_vectors = sum(
                1
                for record in descriptor_records
                if isinstance(record.metadata.get("cross_modal_vector"), list)
                and len(record.metadata["cross_modal_vector"]) == layer.vector_dim
            )

            precomputed_layer = CrossModalMemoryLayer(
                memory,
                cross_modal_encoder=PrecomputedCrossModalEncoder(
                    vector_dim=4,
                    name="external-precomputed",
                ),
            )
            precomputed_expected = {
                "image": precomputed_layer.remember(
                    image_payload(
                        "s3://demo/external-chart.png",
                        caption="external image encoder result",
                        metadata={"cross_modal_vector": [1.0, 0.0, 0.0, 0.0]},
                    ),
                    namespace="precomputed",
                ),
                "audio": precomputed_layer.remember(
                    audio_payload(
                        "s3://demo/external-call.wav",
                        transcript="external audio encoder result",
                        metadata={"cross_modal_vector": [0.0, 1.0, 0.0, 0.0]},
                    ),
                    namespace="precomputed",
                ),
                "video": precomputed_layer.remember(
                    video_payload(
                        "s3://demo/external-demo.mp4",
                        summary="external video encoder result",
                        metadata={"cross_modal_vector": [0.0, 0.0, 1.0, 0.0]},
                    ),
                    namespace="precomputed",
                ),
                "3d": precomputed_layer.remember(
                    asset3d_payload(
                        "s3://demo/external-asset.glb",
                        description="external 3D encoder result",
                        metadata={"cross_modal_vector": [0.0, 0.0, 0.0, 1.0]},
                    ),
                    namespace="precomputed",
                ),
            }
            precomputed_checks = [
                ("image", [1.0, 0.0, 0.0, 0.0]),
                ("audio", [0.0, 1.0, 0.0, 0.0]),
                ("video", [0.0, 0.0, 1.0, 0.0]),
                ("3d", [0.0, 0.0, 0.0, 1.0]),
            ]
            precomputed_correct = 0
            precomputed_persisted = 0
            precomputed_latencies = []
            for modality, query_vector in precomputed_checks:
                started = time.perf_counter()
                results = precomputed_layer.query(
                    "external encoder query",
                    namespace="precomputed",
                    target_modality=modality,
                    top_k=1,
                    query_vector=query_vector,
                )
                precomputed_latencies.append((time.perf_counter() - started) * 1000.0)
                if results and results[0].id == precomputed_expected[modality]:
                    precomputed_correct += 1
                if results and results[0].metadata.get("cross_modal_vector"):
                    precomputed_persisted += 1

            temporal_layer = TemporalEventMemoryLayer(
                memory,
                base_weight=0.30,
                temporal_weight=0.70,
            )
            morning_risk_id = temporal_layer.remember(
                "risk limits reviewed",
                namespace="timeline",
                actor="agent:trading",
                timestamp="2026-07-07T09:00:00Z",
                properties={"window": "morning"},
                tags=["risk"],
            )
            midday_risk_id = temporal_layer.remember(
                "risk limits reviewed",
                namespace="timeline",
                actor="agent:trading",
                timestamp="2026-07-07T12:00:00Z",
                properties={"window": "midday"},
                tags=["risk"],
            )
            latest_risk_id = temporal_layer.remember(
                "risk limits reviewed",
                namespace="timeline",
                actor="agent:trading",
                timestamp="2026-07-08T12:00:00Z",
                properties={"window": "latest"},
                tags=["risk"],
            )
            incident_id = temporal_layer.remember(
                "customer incident response bridge",
                namespace="timeline",
                actor="support:lead",
                timestamp="2026-07-07T10:00:00Z",
                duration_seconds=3600,
                properties={"severity": "high"},
                tags=["incident"],
            )
            temporal_checks = [
                (
                    "around",
                    "risk limits",
                    {"actor": "agent:trading", "around": "2026-07-07T12:10:00Z", "tolerance_seconds": 1800},
                    midday_risk_id,
                ),
                (
                    "window",
                    "risk limits",
                    {"start": "2026-07-07T08:00:00Z", "end": "2026-07-07T10:00:00Z"},
                    morning_risk_id,
                ),
                (
                    "recency",
                    "risk limits",
                    {
                        "actor": "agent:trading",
                        "recency_anchor": "2026-07-08T13:00:00Z",
                        "recency_half_life_seconds": 24 * 3600,
                    },
                    latest_risk_id,
                ),
                (
                    "interval",
                    "incident response",
                    {"start": "2026-07-07T10:30:00Z", "end": "2026-07-07T10:45:00Z"},
                    incident_id,
                ),
            ]
            temporal_latencies = []
            temporal_correct = 0
            temporal_kind_correct: dict[str, int] = {}
            temporal_provenance = 0
            for kind, query, kwargs, expected_id in temporal_checks:
                started = time.perf_counter()
                results = temporal_layer.query(
                    query,
                    namespace="timeline",
                    top_k=1,
                    **kwargs,
                )
                temporal_latencies.append((time.perf_counter() - started) * 1000.0)
                ok = bool(results and results[0].id == expected_id)
                temporal_kind_correct[kind] = int(ok)
                if ok:
                    temporal_correct += 1
                if (
                    results
                    and results[0].provenance.get("memory_id") == results[0].id
                    and results[0].provenance.get("timestamp")
                ):
                    temporal_provenance += 1

            knowledge_graph_layer = KnowledgeGraphMemoryLayer(memory)
            knowledge_graph_layer.remember_triples(
                [("Andrey", "works_on", "trading agent")],
                namespace="kg",
                title="person project edge",
                summary="Andrey works on a trading agent",
                tags=["agent"],
            )
            memory_edge_id = knowledge_graph_layer.remember_triples(
                [
                    ("trading agent", "uses", "WaveMind memory"),
                    ("WaveMind memory", "stores", "dynamic preferences"),
                ],
                namespace="kg",
                title="agent memory graph",
                summary="trading agent uses WaveMind memory for dynamic preferences",
                tags=["agent"],
            )
            knowledge_graph_checks = [
                (
                    "direct",
                    "what does the trading agent use?",
                    {"subject": "trading agent", "predicate": "uses"},
                    memory_edge_id,
                    1,
                ),
                (
                    "two-hop",
                    "how is Andrey connected to WaveMind memory?",
                    {"subject": "Andrey", "object": "WaveMind memory", "max_depth": 2},
                    memory_edge_id,
                    2,
                ),
                (
                    "three-hop",
                    "what does Andrey's memory system store?",
                    {"subject": "Andrey", "object": "dynamic preferences", "max_depth": 3},
                    memory_edge_id,
                    3,
                ),
                (
                    "predicate",
                    "what stores dynamic preferences?",
                    {"subject": "WaveMind memory", "predicate": "stores"},
                    memory_edge_id,
                    1,
                ),
            ]
            knowledge_graph_latencies = []
            knowledge_graph_correct = 0
            knowledge_graph_path_correct = 0
            knowledge_graph_kind_correct: dict[str, int] = {}
            knowledge_graph_provenance = 0
            for kind, query, kwargs, expected_id, expected_depth in knowledge_graph_checks:
                started = time.perf_counter()
                results = knowledge_graph_layer.query(
                    query,
                    namespace="kg",
                    top_k=1,
                    **kwargs,
                )
                knowledge_graph_latencies.append((time.perf_counter() - started) * 1000.0)
                ok = bool(results and results[0].id == expected_id)
                depth_ok = bool(ok and results[0].depth == expected_depth)
                knowledge_graph_kind_correct[kind] = int(ok and depth_ok)
                if ok:
                    knowledge_graph_correct += 1
                if depth_ok:
                    knowledge_graph_path_correct += 1
                if (
                    results
                    and results[0].provenance.get("memory_id") == results[0].id
                    and results[0].provenance.get("path")
                    and results[0].provenance.get("triple")
                ):
                    knowledge_graph_provenance += 1

            reopened = WaveMind(
                db_path=Path(directory) / "payloads.sqlite3",
                encoder=HashingTextEncoder(vector_dim=64),
                width=16,
                height=16,
                layers=1,
            )
            try:
                persisted_layer = TemporalEventMemoryLayer(
                    reopened,
                    base_weight=0.30,
                    temporal_weight=0.70,
                )
                persisted = persisted_layer.query(
                    "risk limits",
                    namespace="timeline",
                    actor="agent:trading",
                    recency_anchor="2026-07-08T13:00:00Z",
                    recency_half_life_seconds=24 * 3600,
                    top_k=1,
                )
                temporal_persistence_rate = float(bool(persisted and persisted[0].id == latest_risk_id))
                persisted_graph_layer = KnowledgeGraphMemoryLayer(reopened)
                persisted_graph = persisted_graph_layer.query(
                    "how is Andrey connected to WaveMind memory?",
                    namespace="kg",
                    subject="Andrey",
                    object="WaveMind memory",
                    max_depth=2,
                    top_k=1,
                )
                knowledge_graph_persistence_rate = float(
                    bool(
                        persisted_graph
                        and persisted_graph[0].id == memory_edge_id
                        and persisted_graph[0].depth == 2
                    )
                )
            finally:
                reopened.close()

            encoder_contract = validate_precomputed_cross_modal_contract(
                memory,
                namespace="encoder-contract",
                encoder_name="scale-readiness-precomputed-contract",
            )
            encoder_health = check_cross_modal_encoder_health(
                layer.cross_modal_encoder,
                min_required_margin=0.01,
                max_payload_encode_ms=50.0,
                max_query_encode_ms=50.0,
            )

            return {
                "engine": "WaveMind structured payloads",
                "modalities": ["image", "audio", "table", "event", "video", "3d", "graph"],
                "queries": len(expected),
                "precision_at_1": correct / len(expected),
                "cross_modal_queries": len(cross_modal_checks),
                "cross_modal_precision_at_1": cross_correct / len(cross_modal_checks),
                "cross_modal_target_modalities": [modality for _, modality, _ in cross_modal_checks],
                "cross_modal_embedding_dim": layer.vector_dim,
                "cross_modal_vectors_persisted_rate": persisted_vectors / len(descriptor_records),
                "cross_modal_provenance_rate": provenance_complete / len(cross_modal_checks),
                "asset_manifest_verified": described_video_asset.verified,
                "asset_manifest_sha256_present": bool(described_video_asset.sha256),
                "asset_manifest_media_type": described_video_asset.media_type,
                "asset_manifest_provenance_rate": asset_manifest_provenance,
                "precomputed_vector_queries": len(precomputed_checks),
                "precomputed_vector_precision_at_1": precomputed_correct / len(precomputed_checks),
                "precomputed_vector_embedding_dim": precomputed_layer.vector_dim,
                "precomputed_vector_persisted_rate": precomputed_persisted / len(precomputed_checks),
                "precomputed_vector_target_modalities": [modality for modality, _ in precomputed_checks],
                "encoder_contract_ok": encoder_contract.ok,
                "encoder_contract_encoder": encoder_contract.encoder_name,
                "encoder_contract_modalities": list(encoder_contract.modalities),
                "encoder_contract_payloads": encoder_contract.payloads,
                "encoder_contract_target_precision_at_1": encoder_contract.target_precision_at_1,
                "encoder_contract_global_precision_at_1": encoder_contract.global_precision_at_1,
                "encoder_contract_target_modality_routing_rate": encoder_contract.target_modality_routing_rate,
                "encoder_contract_persisted_vector_rate": encoder_contract.persisted_vector_rate,
                "encoder_contract_normalized_vector_rate": encoder_contract.normalized_vector_rate,
                "encoder_contract_finite_vector_rate": encoder_contract.finite_vector_rate,
                "encoder_contract_provenance_rate": encoder_contract.provenance_rate,
                "encoder_contract_min_global_margin": encoder_contract.min_global_margin,
                "encoder_contract_min_required_margin": encoder_contract.min_required_margin,
                "encoder_contract_failures": list(encoder_contract.failures),
                "encoder_health_ok": encoder_health.ok,
                "encoder_health_encoder": encoder_health.encoder_name,
                "encoder_health_payloads": encoder_health.payloads,
                "encoder_health_queries": encoder_health.queries,
                "encoder_health_global_precision_at_1": encoder_health.global_precision_at_1,
                "encoder_health_target_modality_routing_rate": encoder_health.target_modality_routing_rate,
                "encoder_health_finite_payload_vector_rate": encoder_health.finite_payload_vector_rate,
                "encoder_health_normalized_payload_vector_rate": encoder_health.normalized_payload_vector_rate,
                "encoder_health_finite_query_vector_rate": encoder_health.finite_query_vector_rate,
                "encoder_health_normalized_query_vector_rate": encoder_health.normalized_query_vector_rate,
                "encoder_health_dimension_match_rate": encoder_health.dimension_match_rate,
                "encoder_health_payload_encode_p95_ms": encoder_health.payload_encode_p95_ms,
                "encoder_health_query_encode_p95_ms": encoder_health.query_encode_p95_ms,
                "encoder_health_min_global_margin": encoder_health.min_global_margin,
                "encoder_health_min_required_margin": encoder_health.min_required_margin,
                "encoder_health_failures": list(encoder_health.failures),
                "temporal_event_queries": len(temporal_checks),
                "temporal_event_precision_at_1": temporal_correct / len(temporal_checks),
                "temporal_event_around_precision_at_1": temporal_kind_correct.get("around", 0),
                "temporal_event_window_precision_at_1": temporal_kind_correct.get("window", 0),
                "temporal_event_recency_precision_at_1": temporal_kind_correct.get("recency", 0),
                "temporal_event_interval_precision_at_1": temporal_kind_correct.get("interval", 0),
                "temporal_event_persistence_rate": temporal_persistence_rate,
                "temporal_event_provenance_rate": temporal_provenance / len(temporal_checks),
                "knowledge_graph_queries": len(knowledge_graph_checks),
                "knowledge_graph_precision_at_1": knowledge_graph_correct / len(knowledge_graph_checks),
                "knowledge_graph_path_precision_at_1": knowledge_graph_path_correct / len(knowledge_graph_checks),
                "knowledge_graph_direct_precision_at_1": knowledge_graph_kind_correct.get("direct", 0),
                "knowledge_graph_two_hop_precision_at_1": knowledge_graph_kind_correct.get("two-hop", 0),
                "knowledge_graph_three_hop_precision_at_1": knowledge_graph_kind_correct.get("three-hop", 0),
                "knowledge_graph_predicate_precision_at_1": knowledge_graph_kind_correct.get("predicate", 0),
                "knowledge_graph_persistence_rate": knowledge_graph_persistence_rate,
                "knowledge_graph_provenance_rate": knowledge_graph_provenance / len(knowledge_graph_checks),
                "avg_latency_ms": statistics.mean(latencies),
                "p99_latency_ms": percentile(latencies, 99),
                "cross_modal_avg_latency_ms": statistics.mean(cross_latencies),
                "cross_modal_p99_latency_ms": percentile(cross_latencies, 99),
                "precomputed_vector_avg_latency_ms": statistics.mean(precomputed_latencies),
                "precomputed_vector_p99_latency_ms": percentile(precomputed_latencies, 99),
                "temporal_event_avg_latency_ms": statistics.mean(temporal_latencies),
                "temporal_event_p99_latency_ms": percentile(temporal_latencies, 99),
                "knowledge_graph_avg_latency_ms": statistics.mean(knowledge_graph_latencies),
                "knowledge_graph_p99_latency_ms": percentile(knowledge_graph_latencies, 99),
            }
        finally:
            memory.close()


def run_100m_capacity_profile() -> dict[str, object]:
    target_memories = 100_000_000
    namespace_count = 32_768
    node_count = 128
    replication_factor = 3
    vector_dim = 384
    payload_kb = 2.0
    vector_dtype_bytes = 1
    memory_payload_bytes = payload_kb * 1024.0
    vector_bytes = vector_dim * vector_dtype_bytes
    logical_storage_gb = target_memories * (memory_payload_bytes + vector_bytes) / float(1024**3)
    replicated_storage_gb = logical_storage_gb * replication_factor
    nodes = [
        ClusterNode(
            id=f"node-{index:03d}",
            address=f"https://wavemind-{index:03d}.internal",
            zone=f"zone-{index % 8}",
        )
        for index in range(node_count)
    ]
    namespaces = [f"tenant:{index:06d}" for index in range(namespace_count)]
    started = time.perf_counter()
    plan = build_cluster_plan(
        namespaces=namespaces,
        nodes=nodes,
        replication_factor=replication_factor,
    )
    expanded_nodes = [
        ClusterNode(
            id=f"node-{index:03d}",
            address=f"https://wavemind-{index:03d}.internal",
            zone=f"zone-{index % 8}",
        )
        for index in range(node_count + 32)
    ]
    expanded_plan = build_cluster_plan(
        namespaces=namespaces,
        nodes=expanded_nodes,
        replication_factor=replication_factor,
    )
    placement_ms = (time.perf_counter() - started) * 1000.0
    quorum = plan.quorum_report()
    health = plan.placement_health_report()
    expanded_health = expanded_plan.placement_health_report()
    scale_out_movement = plan.movement_report(expanded_plan)
    primary_load = list(plan.primary_load.values())
    replica_load = list(plan.node_load.values())
    avg_primary_load = statistics.mean(primary_load)
    avg_replica_load = statistics.mean(replica_load)
    max_primary_load = max(primary_load)
    max_replica_load = max(replica_load)
    min_primary_load = min(primary_load)
    min_replica_load = min(replica_load)
    max_memory_per_node = (
        max_replica_load / max(1, namespace_count) * target_memories
    )
    avg_memory_per_node = target_memories * replication_factor / node_count
    max_storage_per_node_gb = replicated_storage_gb * max_replica_load / sum(replica_load)
    primary_skew = max_primary_load / max(avg_primary_load, 1.0)
    replica_skew = max_replica_load / max(avg_replica_load, 1.0)
    recommended_autoscaling_max_replicas = max(
        node_count,
        int(np.ceil(node_count * 1.5)),
    )
    return {
        "engine": "WaveMind 100M capacity envelope",
        "placement_algorithm": "weighted-rendezvous-zone-aware",
        "target_memories": target_memories,
        "namespace_count": namespace_count,
        "node_count": node_count,
        "zones": len({node.zone for node in nodes}),
        "replication_factor": replication_factor,
        "write_quorum": quorum["write_quorum"],
        "read_quorum": quorum["read_quorum"],
        "node_loss_min_availability": quorum["node_loss_min_availability"],
        "zone_loss_min_availability": quorum["zone_loss_min_availability"],
        "logical_storage_gb": logical_storage_gb,
        "replicated_storage_gb": replicated_storage_gb,
        "max_storage_per_node_gb": max_storage_per_node_gb,
        "avg_memory_per_node": avg_memory_per_node,
        "max_memory_per_node": max_memory_per_node,
        "primary_load_min": min_primary_load,
        "primary_load_max": max_primary_load,
        "primary_load_skew": primary_skew,
        "replica_load_min": min_replica_load,
        "replica_load_max": max_replica_load,
        "replica_load_skew": replica_skew,
        "distinct_replica_rate": health["distinct_replica_rate"],
        "zone_spread_rate": health["zone_spread_rate"],
        "max_primary_weight_error": health["max_primary_weight_error"],
        "max_replica_weight_error": health["max_replica_weight_error"],
        "scale_out_target_node_count": expanded_health["node_count"],
        "scale_out_new_node_count": scale_out_movement["new_node_count"],
        "scale_out_primary_movement_ratio": scale_out_movement["primary_movement_ratio"],
        "scale_out_replica_set_movement_ratio": scale_out_movement["replica_set_movement_ratio"],
        "scale_out_moved_to_new_node": scale_out_movement["moved_to_new_node"],
        "scale_out_target_replica_load_skew": expanded_health["replica_load_skew"],
        "scale_out_target_zone_spread_rate": expanded_health["zone_spread_rate"],
        "recommended_autoscaling_max_replicas": recommended_autoscaling_max_replicas,
        "placement_ms": placement_ms,
        "valid_capacity_plan": (
            quorum["node_loss_min_availability"] == 1.0
            and quorum["zone_loss_min_availability"] == 1.0
            and replica_skew <= 1.25
            and primary_skew <= 1.25
            and health["distinct_replica_rate"] == 1.0
            and health["zone_spread_rate"] == 1.0
            and expanded_health["zone_spread_rate"] == 1.0
            and max_storage_per_node_gb <= 256.0
        ),
        "scope": (
            "Deterministic 100M-memory capacity envelope. This proves shard "
            "placement, replication overhead, storage envelope, and failure-domain "
            "availability; it is not a 100M vector-query latency benchmark."
        ),
    }


def run_benchmark(
    *,
    simulated_memories: int = 1_000_000,
    namespace_count: int = 4096,
    node_count: int = 4,
    replication_factor: int = 2,
    cache_queries: int = 2000,
    cache_capacity: int = 512,
) -> dict[str, object]:
    results = [
        run_cluster_profile(
            namespace_count=namespace_count,
            node_count=node_count,
            replication_factor=replication_factor,
            simulated_memories=simulated_memories,
        ),
        run_cluster_autoscale_profile(
            namespace_count=namespace_count,
            node_count=node_count,
            replication_factor=replication_factor,
            target_memories=max(simulated_memories * 10, 10_000_000),
        ),
        run_control_plane_consensus_profile(),
        run_operator_profile(
            namespace_count=namespace_count,
            node_count=node_count,
            replication_factor=replication_factor,
            target_memories=max(simulated_memories * 10, 10_000_000),
        ),
        run_serverless_profile(),
        run_serverless_operational_profile(),
        run_cache_profile(queries=cache_queries, capacity=cache_capacity),
        run_query_vector_cache_profile(),
        run_api_batch_query_profile(),
        run_shared_rate_limit_profile(),
        run_redis_cache_profile(),
        run_api_cache_mutation_profile(),
        run_batch_feedback_profile(),
        run_memory_os_profile(),
        run_distributed_sharding_profile(),
        run_distributed_http_sharding_profile(),
        run_sustained_http_cluster_load_profile(),
        run_replication_runtime_profile(),
        run_active_active_delta_profile(),
        run_sustained_active_active_sync_profile(),
        run_http_active_active_service_region_profile(),
        run_field_crdt_profile(),
        run_replicated_snapshot_profile(),
        run_recovery_journal_profile(),
        run_multimodal_profile(),
        run_100m_capacity_profile(),
    ]
    return {
        "schema": "wavemind.scale_readiness_benchmark.v1",
        "generated_at": _utc_now_iso(),
        "scenario": {
            "name": "scale_readiness",
            "simulated_memories": simulated_memories,
            "namespace_count": namespace_count,
            "node_count": node_count,
            "replication_factor": replication_factor,
            "description": (
                "Deterministic scale-readiness profile for cluster placement, "
                "cluster autoscale planning, "
                "control-plane majority lease/config revision safety, "
                "operator-style Kubernetes reconciliation, serverless Knative/KEDA planning, "
                "node/zone loss simulation, quorum-replicated runtime behavior, "
                "service-mode distributed namespace sharding, real HTTP shard transport, "
                "sustained mixed HTTP cluster load, "
                "active-active delta sync, sustained active-active sync, "
                "HTTP service-region active-active sync, "
                "replicated snapshot/offsite/archive "
                "restore, S3-compatible object-store upload/latest-metadata/"
                "download/retention/DR-drill verification, SQLite point-in-time "
                "recovery journal replay, query-vector cache, API batch query, "
                "Redis-compatible shared rate limiting, Memory OS adaptive "
                "prewarm/consolidation/forgetting, local and Redis-compatible "
                "hot-cache behavior, API cache mutation safety, batch recall "
                "feedback updates, and structured "
                "payload retrieval, plus a deterministic 100M-memory capacity envelope. "
                "This is not a 10M-vector database load test."
            ),
        },
        "results": results,
    }


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--simulated-memories", type=int, default=1_000_000)
    parser.add_argument("--namespace-count", type=int, default=4096)
    parser.add_argument("--node-count", type=int, default=4)
    parser.add_argument("--replication-factor", type=int, default=2)
    parser.add_argument("--cache-queries", type=int, default=2000)
    parser.add_argument("--cache-capacity", type=int, default=512)
    parser.add_argument("--output", type=Path, default=Path("benchmarks/scale_readiness_results.json"))
    args = parser.parse_args()

    payload = run_benchmark(
        simulated_memories=args.simulated_memories,
        namespace_count=args.namespace_count,
        node_count=args.node_count,
        replication_factor=args.replication_factor,
        cache_queries=args.cache_queries,
        cache_capacity=args.cache_capacity,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print("| profile | key metric | value |")
    print("|---|---|---:|")
    for result in payload["results"]:
        if result["engine"] == "WaveMind cluster planner":
            print(f"| cluster | node_loss_min_availability | {result['node_loss_min_availability']:.3f} |")
            zone_loss = result["zone_loss_min_availability"]
            print(f"| cluster | zone_loss_min_availability | {zone_loss:.3f} |")
        elif result["engine"] == "WaveMind cluster autoscaler":
            print(f"| cluster autoscaler | status | {result['status']} |")
            print(f"| cluster autoscaler | required_nodes | {result['required_nodes']} |")
            print(f"| cluster autoscaler | rebalance_status | {result['rebalance_status']} |")
            print(f"| cluster autoscaler | rebalance_batches | {result['rebalance_batches']} |")
            print(f"| cluster autoscaler | rebalance_move_count | {result['rebalance_move_count']} |")
        elif result["engine"] == "WaveMind control-plane consensus":
            print(f"| control-plane consensus | ok | {result['ok']} |")
            print(f"| control-plane consensus | final_revision | {result['final_revision']} |")
            print(f"| control-plane consensus | minority_commit_blocked | {result['minority_commit_blocked']} |")
            print(f"| control-plane consensus | stale_leader_blocked | {result['stale_leader_blocked']} |")
        elif result["engine"] == "WaveMind Kubernetes operator":
            print(f"| operator | bundle_has_crd | {result['bundle_has_crd']} |")
            print(f"| operator | bundle_has_operator_deployment | {result['bundle_has_operator_deployment']} |")
            print(f"| operator | has_statefulset | {result['has_statefulset']} |")
            print(f"| operator | has_hpa | {result['has_hpa']} |")
            print(f"| operator | has_repair_cronjob | {result['has_repair_cronjob']} |")
            print(f"| operator | statefulset_replicas | {result['statefulset_replicas']} |")
            print(f"| operator | capacity_required_replicas | {result['capacity_required_replicas']} |")
            print(f"| operator | capacity_target_max_node_memories | {result['capacity_target_max_node_memories']} |")
            print(f"| operator | control_plane_ready | {result['control_plane_ready']} |")
            print(f"| operator | control_plane_voters | {result['control_plane_voters']} |")
            print(f"| operator | control_plane_minority_blocked | {result['control_plane_minority_blocked']} |")
            print(f"| operator | autoscaling_max_replicas | {result['autoscaling_max_replicas']} |")
            print(f"| operator | repair_namespaces | {result['repair_namespaces']} |")
        elif result["engine"] == "WaveMind serverless plan":
            print(f"| serverless | has_knative_service | {result['has_knative_service']} |")
            print(f"| serverless | has_keda_scaled_object | {result['has_keda_scaled_object']} |")
            print(f"| serverless | scale_to_zero | {result['scale_to_zero']} |")
            print(f"| serverless | max_scale | {result['max_scale']} |")
            print(f"| serverless | safe_for_pod_eviction | {result['safe_for_pod_eviction']} |")
            print(f"| serverless | valid_keda_scale_target | {result['valid_keda_scale_target']} |")
        elif result["engine"] == "WaveMind serverless operational profile":
            print(f"| serverless ops | slo_pass | {result['slo_pass']} |")
            print(f"| serverless ops | required_replicas | {result['required_replicas']} |")
            print(f"| serverless ops | burst_capacity_rps | {result['burst_capacity_rps']:.0f} |")
            print(f"| serverless ops | cold_start_budget_ok | {result['cold_start_budget_ok']} |")
            print(f"| serverless ops | monthly_compute_cost_usd | {result['monthly_compute_cost_usd']:.2f} |")
            print(f"| serverless ops | observed_slo_pass | {result.get('observed_slo_pass')} |")
        elif result["engine"] == "WaveMind hot cache":
            print(f"| hot cache | hit_rate | {result['hit_rate']:.3f} |")
            print(f"| hot cache | prewarm_warmed | {result['prewarm_warmed']} |")
            print(f"| hot cache | prewarm_hit | {result['prewarm_hit']} |")
        elif result["engine"] == "WaveMind query vector cache":
            print(f"| query vector cache | local_encode_calls | {result['local_encode_calls']} |")
            print(f"| query vector cache | local_hit_rate | {result['local_hit_rate']:.3f} |")
            print(f"| query vector cache | redis_shared_across_workers | {result['redis_shared_across_workers']} |")
        elif result["engine"] == "WaveMind API batch query":
            print(f"| API batch query | batch_success | {result['batch_success']} |")
            print(f"| API batch query | request_reduction_ratio | {result['request_reduction_ratio']:.3f} |")
            print(f"| API batch query | batch_hit_rate | {result['batch_hit_rate']:.3f} |")
        elif result["engine"] == "WaveMind shared rate limiter":
            print(f"| shared rate limiter | shared_across_workers | {result['shared_across_workers']} |")
            print(f"| shared rate limiter | allowed | {result['allowed']} |")
            print(f"| shared rate limiter | limited | {result['limited']} |")
        elif result["engine"] == "WaveMind Redis hot cache":
            print(f"| redis hot cache | shared_cache_visible | {result['shared_cache_visible_across_clients']} |")
            print(f"| redis hot cache | cache_prewarm_warmed | {result['cache_prewarm_warmed']} |")
            print(f"| redis hot cache | memory_os_prewarm_warmed | {result['memory_os_prewarm_warmed']} |")
            print(f"| redis hot cache | memory_os_transition_prefetch_hit | {result['memory_os_transition_prefetch_hit']} |")
            print(f"| redis hot cache | memory_os_forgetting_demotions | {result['memory_os_forgetting_demotions']} |")
            print(f"| redis hot cache | memory_os_cross_worker_hit | {result['memory_os_cross_worker_hit']} |")
            print(f"| redis hot cache | namespace_invalidation_removed | {result['namespace_invalidation_removed']} |")
        elif result["engine"] == "WaveMind API cache mutation safety":
            print(f"| api cache mutation safety | first_query_cached | {result['first_query_cached']} |")
            print(f"| api cache mutation safety | cache_invalidated_on_remember | {result['cache_invalidated_on_remember']} |")
            print(f"| api cache mutation safety | stale_prevented_after_remember | {result['stale_prevented_after_remember']} |")
            print(f"| api cache mutation safety | cache_invalidated_on_forget | {result['cache_invalidated_on_forget']} |")
            print(f"| api cache mutation safety | stale_prevented_after_forget | {result['stale_prevented_after_forget']} |")
        elif result["engine"] == "WaveMind batch feedback":
            print(f"| batch feedback | ok | {result['ok']} |")
            print(f"| batch feedback | accepted | {result['accepted']} |")
            print(f"| batch feedback | rejected | {result['rejected']} |")
            print(f"| batch feedback | cache_invalidated | {result['cache_invalidated']} |")
            print(f"| batch feedback | audit_events | {result['audit_events']} |")
            print(f"| batch feedback | p99_api_ms | {result['p99_api_ms']:.2f} |")
        elif result["engine"] == "WaveMind Memory OS":
            print(f"| memory os | ok | {result['ok']} |")
            print(f"| memory os | hot_queries | {result['hot_queries']} |")
            print(f"| memory os | prewarm_warmed | {result['prewarm_warmed']} |")
            print(f"| memory os | transition_prefetch_hit | {result['transition_prefetch_hit']} |")
            print(f"| memory os | concepts_created | {result['concepts_created']} |")
            print(f"| memory os | forgetting_demotions | {result['forgetting_demotions']} |")
        elif result["engine"] == "WaveMind distributed sharding":
            print(f"| distributed sharding | writes | {result['writes']} |")
            print(f"| distributed sharding | recalled_after_primary_loss | {result['recalled_after_primary_loss']} |")
            print(f"| distributed sharding | repair_repaired_total | {result['repair_repaired_total']} |")
            print(f"| distributed sharding | recalled_after_repair | {result['recalled_after_repair']} |")
            print(f"| distributed sharding | forget_replicated_deletes | {result['forget_replicated_deletes']} |")
            print(f"| distributed sharding | tombstone_suppressed_before_repair | {result['tombstone_suppressed_before_repair']} |")
            print(f"| distributed sharding | tombstone_repair_deleted_records | {result['tombstone_repair_deleted_records']} |")
            print(f"| distributed sharding | tombstone_suppressed_after_repair | {result['tombstone_suppressed_after_repair']} |")
            print(f"| distributed sharding | anti_entropy_worker_ok | {result['anti_entropy_worker_ok']} |")
        elif result["engine"] == "WaveMind distributed HTTP sharding":
            print(f"| distributed HTTP sharding | proxy_bypass_default | {result['proxy_bypass_default']} |")
            print(f"| distributed HTTP sharding | recalled_after_primary_loss | {result['recalled_after_primary_loss']} |")
            print(f"| distributed HTTP sharding | repair_repaired_total | {result['repair_repaired_total']} |")
            print(f"| distributed HTTP sharding | recalled_after_repair | {result['recalled_after_repair']} |")
            print(f"| distributed HTTP sharding | tombstone_repair_deleted_records | {result['tombstone_repair_deleted_records']} |")
            print(f"| distributed HTTP sharding | tombstone_suppressed_after_repair | {result['tombstone_suppressed_after_repair']} |")
            print(f"| distributed HTTP sharding | concurrent_write_ok | {result['concurrent_write_ok']} |")
            print(f"| distributed HTTP sharding | concurrent_query_hit_rate | {result['concurrent_query_hit_rate']:.3f} |")
        elif result["engine"] == "WaveMind sustained HTTP cluster load":
            print(f"| sustained HTTP cluster | success_rate | {result['success_rate']:.3f} |")
            print(f"| sustained HTTP cluster | failover_hit_rate | {result['failover_hit_rate']:.3f} |")
            print(
                "| sustained HTTP cluster | write_batch_http_requests | "
                f"{result['write_batch_individual_http_requests']} -> "
                f"{result['write_batch_http_requests']} |"
            )
            print(
                "| sustained HTTP cluster | query_batch_http_requests | "
                f"{result['query_batch_individual_http_requests']} -> "
                f"{result['query_batch_http_requests']} |"
            )
            print(
                "| sustained HTTP cluster | failover_batch_http_requests | "
                f"{result['failover_batch_individual_http_requests']} -> "
                f"{result['failover_batch_http_requests']} |"
            )
            print(
                "| sustained HTTP cluster | forget_tombstone_batch_http_requests | "
                f"{result['forget_tombstone_batch_individual_http_requests']} -> "
                f"{result['forget_tombstone_batch_http_requests']} |"
            )
            print(f"| sustained HTTP cluster | p99_operation_ms | {result['p99_operation_ms']:.2f} |")
            print(f"| sustained HTTP cluster | repair_repaired_total | {result['repair_repaired_total']} |")
        elif result["engine"] == "WaveMind replicated runtime":
            print(f"| replicated runtime | recalled_after_node_loss | {result['recalled_after_node_loss']} |")
            print(f"| replicated runtime | repair_copied_records | {result['repair_copied_records']} |")
            print(f"| replicated runtime | tombstone_repair_deleted_records | {result['tombstone_repair_deleted_records']} |")
            print(f"| replicated runtime | concurrent_write_ok | {result['concurrent_write_ok']} |")
            print(f"| replicated runtime | concurrent_query_hit_rate | {result['concurrent_query_hit_rate']:.3f} |")
        elif result["engine"] == "WaveMind active-active delta sync":
            print(f"| active-active delta | converged | {result['converged_after_bidirectional_sync']} |")
            print(f"| active-active delta | tombstone_converged | {result['tombstone_converged']} |")
        elif result["engine"] == "WaveMind sustained active-active sync":
            print(f"| sustained active-active | convergence_rate | {result['convergence_rate']:.3f} |")
            print(f"| sustained active-active | delete_suppression_rate | {result['delete_suppression_rate']:.3f} |")
            print(f"| sustained active-active | success_rate | {result['success_rate']:.3f} |")
            print(f"| sustained active-active | p99_sync_ms | {result['p99_sync_ms']:.2f} |")
        elif result["engine"] == "WaveMind HTTP active-active service-region sync":
            print(f"| HTTP active-active service-region | convergence_rate | {result['convergence_rate']:.3f} |")
            print(f"| HTTP active-active service-region | delete_suppression_rate | {result['delete_suppression_rate']:.3f} |")
            print(f"| HTTP active-active service-region | success_rate | {result['success_rate']:.3f} |")
            print(f"| HTTP active-active service-region | p99_sync_ms | {result['p99_sync_ms']:.2f} |")
        elif result["engine"] == "WaveMind field-state CRDT":
            print(f"| field-state CRDT | commutative_convergence | {result['commutative_convergence']} |")
            print(f"| field-state CRDT | idempotent_remerge | {result['idempotent_remerge']} |")
            print(f"| field-state CRDT | tombstone_wins | {result['tombstone_wins']} |")
            print(f"| field-state CRDT | budget_activation | {result['budget_activation']:.3f} |")
        elif result["engine"] == "WaveMind replicated snapshot":
            print(f"| replicated snapshot | manifest_healthy | {result['manifest_healthy']} |")
            print(f"| replicated snapshot | offsite_verified | {result['offsite_verified']} |")
            print(f"| replicated snapshot | archive_verified | {result['archive_verified']} |")
            print(f"| replicated snapshot | object_store_verified | {result['object_store_verified']} |")
            print(f"| replicated snapshot | object_store_latest_verified | {result['object_store_latest_verified']} |")
            print(f"| replicated snapshot | object_store_pruned | {result['object_store_pruned']} |")
            print(f"| replicated snapshot | object_store_download_verified | {result['object_store_download_verified']} |")
            print(f"| replicated snapshot | object_store_drill_ok | {result['object_store_drill_ok']} |")
            print(f"| replicated snapshot | recalled_after_restore_node_loss | {result['recalled_after_restore_node_loss']} |")
        elif result["engine"] == "WaveMind recovery journal":
            print(f"| recovery journal | full_restore_ok | {result['full_restore_ok']} |")
            print(f"| recovery journal | point_in_time_restore_ok | {result['point_in_time_restore_ok']} |")
            print(f"| recovery journal | journal_entries | {result['journal_entries']} |")
            print(f"| recovery journal | restored_records | {result['full_restored_records']} |")
        elif result["engine"] == "WaveMind structured payloads":
            print(f"| structured payloads | precision@1 | {result['precision_at_1']:.3f} |")
            print(f"| structured payloads | knowledge_graph_precision@1 | {result['knowledge_graph_precision_at_1']:.3f} |")
            print(f"| structured payloads | knowledge_graph_path_precision@1 | {result['knowledge_graph_path_precision_at_1']:.3f} |")
            print(f"| structured payloads | knowledge_graph_persistence | {result['knowledge_graph_persistence_rate']:.3f} |")
        elif result["engine"] == "WaveMind 100M capacity envelope":
            print(f"| 100M capacity | valid_capacity_plan | {result['valid_capacity_plan']} |")
            print(f"| 100M capacity | node_loss_min_availability | {result['node_loss_min_availability']:.3f} |")
            print(f"| 100M capacity | max_storage_per_node_gb | {result['max_storage_per_node_gb']:.2f} |")
    print(f"\nWrote {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
