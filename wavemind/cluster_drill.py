from __future__ import annotations

import hashlib
import json
import time
from datetime import datetime, timezone
from typing import Any, Literal

from .sharding import DistributedShardedWaveMind


ClusterDrillMode = Literal["seed", "verify"]


def build_cluster_drill_items(
    *,
    namespace_prefix: str,
    namespace_count: int,
    memories_per_namespace: int,
) -> list[dict[str, Any]]:
    if not namespace_prefix.strip():
        raise ValueError("namespace_prefix must not be empty")
    if namespace_count <= 0:
        raise ValueError("namespace_count must be positive")
    if memories_per_namespace <= 0:
        raise ValueError("memories_per_namespace must be positive")

    items: list[dict[str, Any]] = []
    for namespace_index in range(namespace_count):
        namespace = f"{namespace_prefix}:{namespace_index:04d}"
        for memory_index in range(memories_per_namespace):
            identity = f"{namespace}:{memory_index:04d}"
            token = hashlib.sha256(identity.encode("utf-8")).hexdigest()[:16]
            text = (
                f"WaveMind cluster drill memory {memory_index:04d} for "
                f"{namespace}; verification token {token}"
            )
            items.append(
                {
                    "text": text,
                    "namespace": namespace,
                    "tags": ["cluster-drill"],
                    "metadata": {
                        "cluster_drill": True,
                        "namespace_index": namespace_index,
                        "memory_index": memory_index,
                        "verification_token": token,
                    },
                    "priority": 1.0,
                }
            )
    return items


def run_cluster_drill(
    memory: DistributedShardedWaveMind,
    *,
    mode: ClusterDrillMode,
    namespace_prefix: str = "cluster-drill",
    namespace_count: int = 32,
    memories_per_namespace: int = 8,
    min_hit_rate: float = 1.0,
) -> dict[str, Any]:
    if mode not in {"seed", "verify"}:
        raise ValueError("mode must be 'seed' or 'verify'")
    if not 0.0 <= min_hit_rate <= 1.0:
        raise ValueError("min_hit_rate must be between 0 and 1")

    started = time.perf_counter()
    items = build_cluster_drill_items(
        namespace_prefix=namespace_prefix,
        namespace_count=namespace_count,
        memories_per_namespace=memories_per_namespace,
    )
    base: dict[str, Any] = {
        "schema": "wavemind.cluster_drill.v1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "mode": mode,
        "namespace_prefix": namespace_prefix,
        "namespace_count": namespace_count,
        "memories_per_namespace": memories_per_namespace,
        "expected_memories": len(items),
        "min_hit_rate": float(min_hit_rate),
        "workload_digest": hashlib.sha256(
            json.dumps(items, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest(),
        "cluster": {
            "nodes": [node.as_dict() for node in memory.nodes],
            "replication_factor": memory.replication_factor,
            "write_quorum": memory.write_quorum,
            "read_quorum": memory.read_quorum,
            "read_fanout": memory.read_fanout,
        },
    }

    try:
        if mode == "seed":
            batch = memory.remember_batch(items)
            node_writes = {node.id: 0 for node in memory.nodes}
            failed_nodes: set[str] = set()
            for result in batch.results:
                for node_id in result.writes:
                    node_writes[node_id] += 1
                failed_nodes.update(result.failed_nodes)
            base.update(
                {
                    "status": "pass" if batch.ok and len(batch.results) == len(items) else "fail",
                    "written_memories": len(batch.results),
                    "write_http_requests": batch.write_http_requests,
                    "individual_write_http_requests": batch.individual_write_http_requests,
                    "request_reduction_ratio": batch.request_reduction_ratio,
                    "node_writes": node_writes,
                    "failed_nodes_seen": sorted(failed_nodes),
                    "node_health": memory.node_health(),
                }
            )
        else:
            probe_health = memory.probe_nodes()
            probe_failed_nodes = sorted(
                node_id
                for node_id, payload in probe_health.items()
                if payload.get("last_error") or payload.get("status") != "healthy"
            )
            for node_id in probe_failed_nodes:
                memory.set_node_available(node_id, False)
            batch = memory.query_batch(
                [
                    {
                        "text": item["text"],
                        "namespace": item["namespace"],
                        "top_k": 3,
                        "tags": ["cluster-drill"],
                        "min_score": 0.0,
                    }
                    for item in items
                ]
            )
            hits = sum(
                1
                for item, results in zip(items, batch.results)
                if any(result.text == item["text"] for result in results)
            )
            hit_rate = hits / len(items)
            failed_nodes = sorted(
                set(probe_failed_nodes)
                | {
                    node_id
                    for failures in batch.failed_nodes
                    for node_id in failures
                }
            )
            base.update(
                {
                    "status": "pass" if hit_rate >= min_hit_rate else "fail",
                    "verified_memories": len(batch.results),
                    "hits": hits,
                    "hit_rate": hit_rate,
                    "query_http_requests": batch.query_http_requests,
                    "individual_query_http_requests": batch.individual_query_http_requests,
                    "request_reduction_ratio": batch.request_reduction_ratio,
                    "failed_nodes_seen": failed_nodes,
                    "probe_health": probe_health,
                    "failed_query_count": sum(bool(value) for value in batch.failed_nodes),
                    "node_health": memory.node_health(),
                }
            )
    except Exception as exc:
        base.update(
            {
                "status": "fail",
                "error": f"{type(exc).__name__}: {exc}",
                "failed_nodes_seen": sorted(
                    node_id
                    for node_id, payload in memory.node_health().items()
                    if payload.get("last_error")
                ),
                "node_health": memory.node_health(),
            }
        )

    base["elapsed_ms"] = round((time.perf_counter() - started) * 1000.0, 3)
    return base
