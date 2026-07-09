from __future__ import annotations

import json
import ssl
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from .cluster import ClusterNode, build_cluster_autoscale_plan, build_cluster_plan
from .consensus import run_control_plane_consensus_profile


API_GROUP = "memory.wavemind.ai"
API_VERSION = "v1alpha1"
RESOURCE_KIND = "WaveMindCluster"
RESOURCE_PLURAL = "wavemindclusters"
SERVICE_ACCOUNT_ROOT = Path("/var/run/secrets/kubernetes.io/serviceaccount")
PRODUCTION_ADMISSION_MIN_STRICT_MEMORIES = 10_000_000


@dataclass(frozen=True)
class WaveMindClusterSpec:
    """Declarative Kubernetes deployment spec for a WaveMind cluster."""

    name: str = "wavemind"
    namespace: str = "default"
    image: str = "ghcr.io/caspiang/wavemind:latest"
    replicas: int = 3
    replication_factor: int = 2
    namespace_count: int = 128
    namespace_prefix: str = "tenant"
    storage_size: str = "20Gi"
    service_port: int = 8000
    image_pull_policy: str = "IfNotPresent"
    encoder: str = "hash"
    index: str = "faiss-persisted"
    score_threshold: float = 0.0
    cache_capacity: int = 512
    cache_ttl_seconds: float = 60.0
    audit_queries: bool = True
    redis_url: str | None = None
    auth_secret: str | None = None
    auth_secret_key: str = "api-key"
    repair_enabled: bool = True
    repair_schedule: str = "*/15 * * * *"
    repair_limit: int = 1000
    memory_os_enabled: bool = False
    memory_os_schedule: str = "*/10 * * * *"
    memory_os_namespace: str | None = None
    memory_os_audit_limit: int = 512
    memory_os_max_hot_queries: int = 32
    memory_os_min_frequency: int = 2
    memory_os_top_k: int = 3
    memory_os_target_memories: int | None = None
    memory_os_cache_mode: str = "auto"
    memory_os_target_qps: float = 100.0
    memory_os_target_p99_ms: float = 100.0
    memory_os_observed_p99_ms: float | None = None
    memory_os_multimodal: bool = False
    memory_os_strict_plan: bool = True
    memory_os_lock_required: bool = False
    memory_os_lock_ttl_seconds: int = 300
    memory_os_lock_prefix: str = "wavemind:memory-os:lock"
    memory_os_run_on_all_replicas: bool = True
    memory_os_timeout_seconds: float = 30.0
    production_admission_enabled: bool = False
    production_admission_target_memories: int | None = None
    production_admission_engine: str | None = None
    production_admission_deployment: str = "production"
    production_admission_root: str = "/evidence"
    control_plane_consensus_enabled: bool = True
    control_plane_lease_ttl_seconds: float = 30.0
    control_plane_config_revision: int = 0
    autoscaling_enabled: bool = False
    autoscaling_min_replicas: int = 3
    autoscaling_max_replicas: int = 12
    autoscaling_target_cpu_utilization: int = 70
    autoscaling_target_memory_utilization: int | None = None
    autoscaling_target_memories: int | None = None
    autoscaling_max_memories_per_node: int = 1_000_000
    autoscaling_headroom: float = 0.70
    capacity_seed_replicas: int | None = None
    rebalance_batch_size: int = 50
    rebalance_max_node_moves_per_batch: int | None = 50
    rebalance_preview_batches: int = 3
    resources: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.name.strip():
            raise ValueError("name must not be empty")
        if not self.namespace.strip():
            raise ValueError("namespace must not be empty")
        if not self.image.strip():
            raise ValueError("image must not be empty")
        if self.replicas <= 0:
            raise ValueError("replicas must be positive")
        if self.replication_factor <= 0:
            raise ValueError("replication_factor must be positive")
        if self.namespace_count < 0:
            raise ValueError("namespace_count cannot be negative")
        if self.service_port <= 0:
            raise ValueError("service_port must be positive")
        if self.repair_limit <= 0:
            raise ValueError("repair_limit must be positive")
        if self.memory_os_audit_limit <= 0:
            raise ValueError("memory_os_audit_limit must be positive")
        if self.memory_os_max_hot_queries <= 0:
            raise ValueError("memory_os_max_hot_queries must be positive")
        if self.memory_os_min_frequency <= 0:
            raise ValueError("memory_os_min_frequency must be positive")
        if self.memory_os_top_k <= 0:
            raise ValueError("memory_os_top_k must be positive")
        if self.memory_os_target_memories is not None and self.memory_os_target_memories < 0:
            raise ValueError("memory_os_target_memories cannot be negative")
        if self.memory_os_cache_mode not in {"auto", "disabled", "local", "redis"}:
            raise ValueError("memory_os_cache_mode must be auto, disabled, local, or redis")
        if self.memory_os_target_qps <= 0:
            raise ValueError("memory_os_target_qps must be positive")
        if self.memory_os_target_p99_ms <= 0:
            raise ValueError("memory_os_target_p99_ms must be positive")
        if self.memory_os_observed_p99_ms is not None and self.memory_os_observed_p99_ms < 0:
            raise ValueError("memory_os_observed_p99_ms cannot be negative")
        if self.memory_os_lock_ttl_seconds <= 0:
            raise ValueError("memory_os_lock_ttl_seconds must be positive")
        if self.memory_os_timeout_seconds <= 0:
            raise ValueError("memory_os_timeout_seconds must be positive")
        if self.control_plane_lease_ttl_seconds <= 0:
            raise ValueError("control_plane_lease_ttl_seconds must be positive")
        if self.control_plane_config_revision < 0:
            raise ValueError("control_plane_config_revision cannot be negative")
        if self.autoscaling_min_replicas <= 0:
            raise ValueError("autoscaling_min_replicas must be positive")
        if self.autoscaling_max_replicas < self.autoscaling_min_replicas:
            raise ValueError("autoscaling_max_replicas must be >= autoscaling_min_replicas")
        if not 1 <= self.autoscaling_target_cpu_utilization <= 100:
            raise ValueError("autoscaling_target_cpu_utilization must be between 1 and 100")
        if self.autoscaling_target_memory_utilization is not None and not (
            1 <= self.autoscaling_target_memory_utilization <= 100
        ):
            raise ValueError("autoscaling_target_memory_utilization must be between 1 and 100")
        if self.autoscaling_target_memories is not None:
            if self.autoscaling_target_memories < 0:
                raise ValueError("autoscaling_target_memories cannot be negative")
            if self.namespace_count <= 0:
                raise ValueError("namespace_count must be positive when target memories are set")
            if self.autoscaling_max_memories_per_node <= 0:
                raise ValueError("autoscaling_max_memories_per_node must be positive")
            if self.autoscaling_headroom <= 0 or self.autoscaling_headroom > 1:
                raise ValueError("autoscaling_headroom must be in (0, 1]")
            if self.rebalance_batch_size <= 0:
                raise ValueError("rebalance_batch_size must be positive")
            if (
                self.rebalance_max_node_moves_per_batch is not None
                and self.rebalance_max_node_moves_per_batch <= 0
            ):
                raise ValueError("rebalance_max_node_moves_per_batch must be positive")
            if self.rebalance_preview_batches < 0:
                raise ValueError("rebalance_preview_batches cannot be negative")
            seed_replicas = max(
                self.capacity_seed_replicas or self.replicas,
                self.replication_factor,
            )
            object.__setattr__(self, "capacity_seed_replicas", seed_replicas)
            required_replicas = self._capacity_required_replicas(seed_replicas=seed_replicas)
            object.__setattr__(self, "replicas", max(self.replicas, required_replicas))
            object.__setattr__(
                self,
                "autoscaling_min_replicas",
                max(self.autoscaling_min_replicas, required_replicas),
            )
            object.__setattr__(
                self,
                "autoscaling_max_replicas",
                max(self.autoscaling_max_replicas, required_replicas),
            )
        if (
            self.production_admission_target_memories is not None
            and self.production_admission_target_memories < 0
        ):
            raise ValueError("production_admission_target_memories cannot be negative")
        if not self.production_admission_deployment.strip():
            raise ValueError("production_admission_deployment must not be empty")
        if not self.production_admission_root.strip():
            raise ValueError("production_admission_root must not be empty")
        if self.production_admission_enabled and self.production_admission_target() <= 0:
            raise ValueError(
                "production_admission_target_memories is required when production admission is enabled"
            )
        if self.replication_factor > self.replicas:
            raise ValueError("replication_factor cannot exceed replicas")

    @classmethod
    def from_custom_resource(cls, resource: dict[str, Any]) -> "WaveMindClusterSpec":
        metadata = dict(resource.get("metadata") or {})
        spec = dict(resource.get("spec") or {})
        runtime = dict(spec.get("runtime") or {})
        cache = dict(spec.get("cache") or {})
        auth = dict(spec.get("auth") or {})
        repair = dict(spec.get("repair") or {})
        memory_os = dict(spec.get("memoryOs") or {})
        production_admission = dict(spec.get("productionAdmission") or {})
        control_plane = dict(spec.get("controlPlane") or {})
        consensus = dict(control_plane.get("consensus") or {})
        autoscaling = dict(spec.get("autoscaling") or {})
        rebalance = dict(autoscaling.get("rebalance") or {})
        persistence = dict(spec.get("persistence") or {})
        service = dict(spec.get("service") or {})

        return cls(
            name=str(metadata.get("name") or spec.get("name") or "wavemind"),
            namespace=str(metadata.get("namespace") or spec.get("namespace") or "default"),
            image=str(spec.get("image") or "ghcr.io/caspiang/wavemind:latest"),
            replicas=int(spec.get("replicas", 3)),
            replication_factor=int(spec.get("replicationFactor", 2)),
            namespace_count=int(spec.get("namespaceCount", 128)),
            namespace_prefix=str(spec.get("namespacePrefix", "tenant")),
            storage_size=str(persistence.get("size") or spec.get("storageSize") or "20Gi"),
            service_port=int(service.get("port", spec.get("servicePort", 8000))),
            image_pull_policy=str(spec.get("imagePullPolicy", "IfNotPresent")),
            encoder=str(runtime.get("encoder", "hash")),
            index=str(runtime.get("index", "faiss-persisted")),
            score_threshold=float(runtime.get("scoreThreshold", 0.0)),
            cache_capacity=int(cache.get("capacity", runtime.get("cacheCapacity", 512))),
            cache_ttl_seconds=float(cache.get("ttlSeconds", runtime.get("cacheTtlSeconds", 60.0))),
            audit_queries=bool(runtime.get("auditQueries", True)),
            redis_url=_optional_string(cache.get("redisUrl") or runtime.get("redisUrl")),
            auth_secret=_optional_string(auth.get("secretName") or spec.get("authSecret")),
            auth_secret_key=str(auth.get("secretKey", "api-key")),
            repair_enabled=bool(repair.get("enabled", True)),
            repair_schedule=str(repair.get("schedule", "*/15 * * * *")),
            repair_limit=int(repair.get("limit", 1000)),
            memory_os_enabled=bool(memory_os.get("enabled", False)),
            memory_os_schedule=str(memory_os.get("schedule", "*/10 * * * *")),
            memory_os_namespace=_optional_string(memory_os.get("namespace")),
            memory_os_audit_limit=int(memory_os.get("auditLimit", 512)),
            memory_os_max_hot_queries=int(memory_os.get("maxHotQueries", 32)),
            memory_os_min_frequency=int(memory_os.get("minFrequency", 2)),
            memory_os_top_k=int(memory_os.get("topK", 3)),
            memory_os_target_memories=_optional_int(memory_os.get("targetMemories")),
            memory_os_cache_mode=str(memory_os.get("cacheMode", "auto")),
            memory_os_target_qps=float(memory_os.get("targetQps", 100.0)),
            memory_os_target_p99_ms=float(memory_os.get("targetP99Ms", 100.0)),
            memory_os_observed_p99_ms=_optional_float(memory_os.get("observedP99Ms")),
            memory_os_multimodal=bool(memory_os.get("multimodal", False)),
            memory_os_strict_plan=bool(memory_os.get("strictPlan", True)),
            memory_os_lock_required=bool(memory_os.get("lockRequired", False)),
            memory_os_lock_ttl_seconds=int(memory_os.get("lockTtlSeconds", 300)),
            memory_os_lock_prefix=str(memory_os.get("lockPrefix", "wavemind:memory-os:lock")),
            memory_os_run_on_all_replicas=bool(memory_os.get("runOnAllReplicas", True)),
            memory_os_timeout_seconds=float(memory_os.get("timeoutSeconds", 30.0)),
            production_admission_enabled=bool(production_admission.get("enabled", False)),
            production_admission_target_memories=_optional_int(
                production_admission.get("targetMemories")
            ),
            production_admission_engine=_optional_string(production_admission.get("engine")),
            production_admission_deployment=str(
                production_admission.get("deployment", "production")
            ),
            production_admission_root=str(production_admission.get("evidenceRoot", "/evidence")),
            control_plane_consensus_enabled=bool(consensus.get("enabled", True)),
            control_plane_lease_ttl_seconds=float(consensus.get("leaseTtlSeconds", 30.0)),
            control_plane_config_revision=int(consensus.get("configRevision", 0)),
            autoscaling_enabled=bool(autoscaling.get("enabled", False)),
            autoscaling_min_replicas=int(autoscaling.get("minReplicas", spec.get("replicas", 3))),
            autoscaling_max_replicas=int(autoscaling.get("maxReplicas", max(12, int(spec.get("replicas", 3))))),
            autoscaling_target_cpu_utilization=int(autoscaling.get("targetCPUUtilizationPercentage", 70)),
            autoscaling_target_memory_utilization=_optional_int(
                autoscaling.get("targetMemoryUtilizationPercentage")
            ),
            autoscaling_target_memories=_optional_int(autoscaling.get("targetMemories")),
            autoscaling_max_memories_per_node=int(autoscaling.get("maxMemoriesPerNode", 1_000_000)),
            autoscaling_headroom=float(autoscaling.get("headroom", 0.70)),
            capacity_seed_replicas=_optional_int(autoscaling.get("seedReplicas")),
            rebalance_batch_size=int(
                rebalance.get("batchSize", autoscaling.get("rebalanceBatchSize", 50))
            ),
            rebalance_max_node_moves_per_batch=_optional_int(
                rebalance.get(
                    "maxNodeMovesPerBatch",
                    autoscaling.get("rebalanceMaxNodeMovesPerBatch", 50),
                )
            ),
            rebalance_preview_batches=int(
                rebalance.get("previewBatches", autoscaling.get("rebalancePreviewBatches", 3))
            ),
            resources=dict(spec.get("resources") or {}),
        )

    @property
    def headless_service_name(self) -> str:
        return f"{self.name}-headless"

    @property
    def namespaces(self) -> tuple[str, ...]:
        return tuple(
            f"{self.namespace_prefix}:{index}"
            for index in range(self.namespace_count)
        )

    @property
    def nodes(self) -> tuple[ClusterNode, ...]:
        return tuple(
            ClusterNode(
                id=f"{self.name}-{index}",
                address=(
                    f"http://{self.name}-{index}.{self.headless_service_name}."
                    f"{self.namespace}.svc.cluster.local:{self.service_port}"
                ),
            )
            for index in range(self.replicas)
        )

    def custom_resource(self) -> dict[str, Any]:
        spec: dict[str, Any] = {
            "image": self.image,
            "replicas": self.replicas,
            "replicationFactor": self.replication_factor,
            "namespaceCount": self.namespace_count,
            "namespacePrefix": self.namespace_prefix,
            "persistence": {"size": self.storage_size},
            "service": {"port": self.service_port},
            "runtime": {
                "encoder": self.encoder,
                "index": self.index,
                "scoreThreshold": self.score_threshold,
                "auditQueries": self.audit_queries,
            },
            "cache": {
                "capacity": self.cache_capacity,
                "ttlSeconds": self.cache_ttl_seconds,
            },
            "repair": {
                "enabled": self.repair_enabled,
                "schedule": self.repair_schedule,
                "limit": self.repair_limit,
            },
            "controlPlane": {
                "consensus": {
                    "enabled": self.control_plane_consensus_enabled,
                    "leaseTtlSeconds": self.control_plane_lease_ttl_seconds,
                    "configRevision": self.control_plane_config_revision,
                }
            },
        }
        if self.autoscaling_enabled:
            autoscaling: dict[str, Any] = {
                "enabled": True,
                "minReplicas": self.autoscaling_min_replicas,
                "maxReplicas": self.autoscaling_max_replicas,
                "targetCPUUtilizationPercentage": self.autoscaling_target_cpu_utilization,
            }
            if self.autoscaling_target_memory_utilization is not None:
                autoscaling["targetMemoryUtilizationPercentage"] = (
                    self.autoscaling_target_memory_utilization
                )
            spec["autoscaling"] = autoscaling
        if self.autoscaling_target_memories is not None:
            autoscaling = dict(spec.get("autoscaling") or {})
            autoscaling.update(
                {
                    "enabled": self.autoscaling_enabled,
                    "minReplicas": self.autoscaling_min_replicas,
                    "maxReplicas": self.autoscaling_max_replicas,
                    "targetCPUUtilizationPercentage": self.autoscaling_target_cpu_utilization,
                    "targetMemories": self.autoscaling_target_memories,
                    "maxMemoriesPerNode": self.autoscaling_max_memories_per_node,
                    "headroom": self.autoscaling_headroom,
                    "seedReplicas": self.capacity_seed_replicas or self.replicas,
                    "rebalance": {
                        "batchSize": self.rebalance_batch_size,
                        "maxNodeMovesPerBatch": self.rebalance_max_node_moves_per_batch,
                        "previewBatches": self.rebalance_preview_batches,
                    },
                }
            )
            if self.autoscaling_target_memory_utilization is not None:
                autoscaling["targetMemoryUtilizationPercentage"] = (
                    self.autoscaling_target_memory_utilization
                )
            spec["autoscaling"] = autoscaling
        if self.memory_os_enabled:
            memory_os: dict[str, Any] = {
                "enabled": True,
                "schedule": self.memory_os_schedule,
                "auditLimit": self.memory_os_audit_limit,
                "maxHotQueries": self.memory_os_max_hot_queries,
                "minFrequency": self.memory_os_min_frequency,
                "topK": self.memory_os_top_k,
                "cacheMode": self.memory_os_cache_mode,
                "targetQps": self.memory_os_target_qps,
                "targetP99Ms": self.memory_os_target_p99_ms,
                "multimodal": self.memory_os_multimodal,
                "strictPlan": self.memory_os_strict_plan,
                "lockRequired": self.memory_os_lock_required,
                "lockTtlSeconds": self.memory_os_lock_ttl_seconds,
                "lockPrefix": self.memory_os_lock_prefix,
                "runOnAllReplicas": self.memory_os_run_on_all_replicas,
                "timeoutSeconds": self.memory_os_timeout_seconds,
            }
            if self.memory_os_namespace is not None:
                memory_os["namespace"] = self.memory_os_namespace
            if self.memory_os_target_memories is not None:
                memory_os["targetMemories"] = self.memory_os_target_memories
            if self.memory_os_observed_p99_ms is not None:
                memory_os["observedP99Ms"] = self.memory_os_observed_p99_ms
            spec["memoryOs"] = memory_os
        if self.production_admission_enabled or self.production_admission_target_memories is not None:
            production_admission: dict[str, Any] = {
                "enabled": self.production_admission_enabled,
                "deployment": self.production_admission_deployment,
                "evidenceRoot": self.production_admission_root,
            }
            if self.production_admission_target_memories is not None:
                production_admission["targetMemories"] = self.production_admission_target_memories
            if self.production_admission_engine:
                production_admission["engine"] = self.production_admission_engine
            spec["productionAdmission"] = production_admission
        if self.redis_url:
            spec["cache"]["redisUrl"] = self.redis_url
        if self.auth_secret:
            spec["auth"] = {
                "secretName": self.auth_secret,
                "secretKey": self.auth_secret_key,
            }
        if self.resources:
            spec["resources"] = dict(self.resources)
        return {
            "apiVersion": f"{API_GROUP}/{API_VERSION}",
            "kind": RESOURCE_KIND,
            "metadata": {
                "name": self.name,
                "namespace": self.namespace,
            },
            "spec": spec,
        }

    def reconciled_resources(self, *, rebalance_plan: Any | None = None) -> list[dict[str, Any]]:
        resources = [
            self._service(headless=False),
            self._service(headless=True),
            self._statefulset(),
            self._pod_disruption_budget(),
        ]
        if self.autoscaling_enabled:
            resources.append(self._horizontal_pod_autoscaler())
        if self.autoscaling_target_memories is not None:
            resources.append(self._rebalance_configmap(rebalance_plan))
        if self.repair_enabled and self.namespace_count:
            resources.append(self._repair_cronjob())
        if self.memory_os_enabled and self.namespace_count:
            resources.append(self._memory_os_cronjob())
        return resources

    def capacity_autoscale_plan(self, *, max_moves: int = 25, seed_replicas: int | None = None):
        if self.autoscaling_target_memories is None:
            return None
        current_replicas = int(seed_replicas or self.capacity_seed_replicas or self.replicas)
        current_nodes = tuple(
            ClusterNode(
                id=f"{self.name}-{index}",
                address=(
                    f"http://{self.name}-{index}.{self.headless_service_name}."
                    f"{self.namespace}.svc.cluster.local:{self.service_port}"
                ),
            )
            for index in range(current_replicas)
        )
        return build_cluster_autoscale_plan(
            namespaces=self.namespaces,
            nodes=current_nodes,
            replication_factor=self.replication_factor,
            target_memories=self.autoscaling_target_memories,
            max_memories_per_node=self.autoscaling_max_memories_per_node,
            headroom=self.autoscaling_headroom,
            node_prefix=self.name,
            address_template=(
                f"http://{{node_id}}.{self.headless_service_name}."
                f"{self.namespace}.svc.cluster.local:{self.service_port}"
            ),
            max_moves=max_moves,
        )

    def capacity_rebalance_plan(self):
        if self.autoscaling_target_memories is None:
            return None
        plan = self.capacity_autoscale_plan(max_moves=self.namespace_count)
        assert plan is not None
        return plan.rebalance_plan(
            batch_size=self.rebalance_batch_size,
            max_node_moves_per_batch=self.rebalance_max_node_moves_per_batch,
        )

    def control_plane_consensus_report(self) -> dict[str, object]:
        if not self.control_plane_consensus_enabled:
            return {
                "enabled": False,
                "ready": False,
                "reason": "Consensus disabled",
            }
        profile = run_control_plane_consensus_profile(
            self.nodes,
            lease_ttl_seconds=self.control_plane_lease_ttl_seconds,
            config_revision=self.control_plane_config_revision,
        )
        return {
            "enabled": True,
            "ready": bool(profile.get("ok")),
            "profile": profile,
        }

    def memory_os_requires_redis(self) -> bool:
        if not self.memory_os_enabled:
            return False
        if self.memory_os_cache_mode == "redis" or self.memory_os_lock_required:
            return True
        target = (
            self.memory_os_target_memories
            if self.memory_os_target_memories is not None
            else self.autoscaling_target_memories
            if self.autoscaling_target_memories is not None
            else 0
        )
        return self.memory_os_cache_mode == "auto" and (
            self.replicas > 1 or target >= 1_000_000
        )

    def production_admission_target(self) -> int:
        return int(
            self.production_admission_target_memories
            if self.production_admission_target_memories is not None
            else self.autoscaling_target_memories
            if self.autoscaling_target_memories is not None
            else self.memory_os_target_memories
            if self.memory_os_target_memories is not None
            else 0
        )

    def production_admission_required(self) -> bool:
        return self.production_admission_target() >= PRODUCTION_ADMISSION_MIN_STRICT_MEMORIES

    def production_admission_guard_enabled(self) -> bool:
        return self.production_admission_enabled or self.production_admission_required()

    def production_admission_ready(self) -> bool:
        if not self.production_admission_guard_enabled():
            return True
        return self.production_admission_target() > 0 and bool(self.production_admission_root.strip())

    def as_resource_list(self, resources: Iterable[dict[str, Any]] | None = None) -> dict[str, Any]:
        return {
            "apiVersion": "v1",
            "kind": "List",
            "items": list(resources if resources is not None else self.reconciled_resources()),
        }

    def _labels(self) -> dict[str, str]:
        return {
            "app.kubernetes.io/name": "wavemind",
            "app.kubernetes.io/instance": self.name,
            "app.kubernetes.io/component": "api",
            "app.kubernetes.io/managed-by": "wavemind-operator",
        }

    def _service(self, *, headless: bool) -> dict[str, Any]:
        labels = self._labels()
        name = self.headless_service_name if headless else self.name
        spec: dict[str, Any] = {
            "ports": [
                {
                    "name": "http",
                    "port": self.service_port,
                    "targetPort": "http",
                    "protocol": "TCP",
                }
            ],
            "selector": labels,
        }
        if headless:
            spec["clusterIP"] = "None"
            spec["publishNotReadyAddresses"] = True
        else:
            spec["type"] = "ClusterIP"
        return {
            "apiVersion": "v1",
            "kind": "Service",
            "metadata": {
                "name": name,
                "namespace": self.namespace,
                "labels": labels,
                "annotations": self._capacity_annotations(),
            },
            "spec": spec,
        }

    def _statefulset(self) -> dict[str, Any]:
        labels = self._labels()
        env = [
            {"name": "WAVEMIND_DB", "value": "/data/wavemind.sqlite3"},
            {"name": "WAVEMIND_CLUSTER_MODE", "value": "namespace-sharded"},
            {"name": "WAVEMIND_REPLICATION_FACTOR", "value": str(self.replication_factor)},
            {"name": "WAVEMIND_ENCODER", "value": self.encoder},
            {"name": "WAVEMIND_INDEX", "value": self.index},
            {"name": "WAVEMIND_SCORE_THRESHOLD", "value": str(self.score_threshold)},
            {"name": "WAVEMIND_AUDIT_QUERIES", "value": "true" if self.audit_queries else "false"},
            {"name": "WAVEMIND_CACHE_CAPACITY", "value": str(self.cache_capacity)},
            {"name": "WAVEMIND_CACHE_TTL_SECONDS", "value": str(self.cache_ttl_seconds)},
        ]
        if self.redis_url:
            env.append({"name": "WAVEMIND_REDIS_URL", "value": self.redis_url})
        if self.production_admission_guard_enabled():
            env.extend(
                [
                    {"name": "WAVEMIND_REQUIRE_PRODUCTION_ADMISSION", "value": "1"},
                    {
                        "name": "WAVEMIND_PRODUCTION_TARGET_MEMORIES",
                        "value": str(self.production_admission_target()),
                    },
                    {
                        "name": "WAVEMIND_PRODUCTION_DEPLOYMENT",
                        "value": self.production_admission_deployment,
                    },
                    {
                        "name": "WAVEMIND_PRODUCTION_ADMISSION_ROOT",
                        "value": self.production_admission_root,
                    },
                ]
            )
            if self.production_admission_engine:
                env.append(
                    {
                        "name": "WAVEMIND_PRODUCTION_ENGINE",
                        "value": self.production_admission_engine,
                    }
                )
        if self.auth_secret:
            secret_ref = {
                "secretKeyRef": {
                    "name": self.auth_secret,
                    "key": self.auth_secret_key,
                }
            }
            env.extend(
                [
                    {"name": "WAVEMIND_API_KEYS", "valueFrom": secret_ref},
                    {"name": "WAVEMIND_ADMIN_KEYS", "valueFrom": secret_ref},
                ]
            )

        container: dict[str, Any] = {
            "name": "wavemind",
            "image": self.image,
            "imagePullPolicy": self.image_pull_policy,
            "command": ["wavemind"],
            "args": ["serve", "--host", "0.0.0.0", "--port", str(self.service_port)],
            "ports": [{"name": "http", "containerPort": self.service_port, "protocol": "TCP"}],
            "env": env,
            "livenessProbe": {
                "tcpSocket": {"port": "http"},
                "initialDelaySeconds": 10,
                "periodSeconds": 20,
            },
            "readinessProbe": {
                "tcpSocket": {"port": "http"},
                "initialDelaySeconds": 5,
                "periodSeconds": 10,
            },
            "volumeMounts": [{"name": "state", "mountPath": "/data"}],
        }
        if self.resources:
            container["resources"] = dict(self.resources)

        return {
            "apiVersion": "apps/v1",
            "kind": "StatefulSet",
            "metadata": {
                "name": self.name,
                "namespace": self.namespace,
                "labels": labels,
                "annotations": self._capacity_annotations(),
            },
            "spec": {
                "serviceName": self.headless_service_name,
                "replicas": self.replicas,
                "podManagementPolicy": "Parallel",
                "selector": {"matchLabels": labels},
                "template": {
                    "metadata": {"labels": labels},
                    "spec": {
                        "affinity": {
                            "podAntiAffinity": {
                                "preferredDuringSchedulingIgnoredDuringExecution": [
                                    {
                                        "weight": 100,
                                        "podAffinityTerm": {
                                            "topologyKey": "kubernetes.io/hostname",
                                            "labelSelector": {"matchLabels": labels},
                                        },
                                    }
                                ]
                            }
                        },
                        "topologySpreadConstraints": [
                            {
                                "maxSkew": 1,
                                "topologyKey": "kubernetes.io/hostname",
                                "whenUnsatisfiable": "ScheduleAnyway",
                                "labelSelector": {"matchLabels": labels},
                            },
                            {
                                "maxSkew": 1,
                                "topologyKey": "topology.kubernetes.io/zone",
                                "whenUnsatisfiable": "ScheduleAnyway",
                                "labelSelector": {"matchLabels": labels},
                            },
                        ],
                        "terminationGracePeriodSeconds": 30,
                        "containers": [container],
                    },
                },
                "updateStrategy": {"type": "RollingUpdate"},
                "minReadySeconds": 5,
                "volumeClaimTemplates": [
                    {
                        "metadata": {"name": "state"},
                        "spec": {
                            "accessModes": ["ReadWriteOnce"],
                            "resources": {"requests": {"storage": self.storage_size}},
                        },
                    }
                ],
            },
        }

    def _pod_disruption_budget(self) -> dict[str, Any]:
        labels = self._labels()
        return {
            "apiVersion": "policy/v1",
            "kind": "PodDisruptionBudget",
            "metadata": {
                "name": self.name,
                "namespace": self.namespace,
                "labels": labels,
            },
            "spec": {
                "minAvailable": max(1, self.replicas - 1),
                "selector": {"matchLabels": labels},
            },
        }

    def _repair_cronjob(self) -> dict[str, Any]:
        plan = build_cluster_plan(
            namespaces=self.namespaces,
            nodes=self.nodes,
            replication_factor=self.replication_factor,
        )
        manifest = plan.kubernetes_repair_cronjob(
            image=self.image,
            schedule=self.repair_schedule,
            name=f"{self.name}-cluster-repair",
            api_key_secret=self.auth_secret,
            api_key_secret_key=self.auth_secret_key,
            repair_limit=self.repair_limit,
        )
        manifest["metadata"]["namespace"] = self.namespace
        for container in manifest["spec"]["jobTemplate"]["spec"]["template"]["spec"]["containers"]:
            container["imagePullPolicy"] = self.image_pull_policy
        return manifest

    def _memory_os_cronjob(self) -> dict[str, Any]:
        labels = {**self._labels(), "app.kubernetes.io/component": "memory-os"}
        env: list[dict[str, Any]] = []
        if self.auth_secret:
            env.append(
                {
                    "name": "WAVEMIND_API_KEY",
                    "valueFrom": {
                        "secretKeyRef": {
                            "name": self.auth_secret,
                            "key": self.auth_secret_key,
                        }
                    },
                }
            )
        nodes = [node.address for node in self.nodes]
        plan_payload: dict[str, Any] = {
            "namespace": self.memory_os_namespace,
            "audit_limit": self.memory_os_audit_limit,
            "max_hot_queries": self.memory_os_max_hot_queries,
            "min_frequency": self.memory_os_min_frequency,
            "top_k": self.memory_os_top_k,
            "target_memories": (
                self.memory_os_target_memories
                if self.memory_os_target_memories is not None
                else self.autoscaling_target_memories
                if self.autoscaling_target_memories is not None
                else 2_000_000
            ),
            "namespace_count": self.namespace_count,
            "node_count": len(nodes),
            "deployment": "production",
            "cache_mode": self.memory_os_cache_mode,
            "target_qps": self.memory_os_target_qps,
            "target_p99_ms": self.memory_os_target_p99_ms,
            "observed_p99_ms": self.memory_os_observed_p99_ms,
            "multimodal": self.memory_os_multimodal,
        }
        script = f"""
import json
import os
import sys
import urllib.request

nodes = {json.dumps(nodes)}
plan_payload = {json.dumps(plan_payload, sort_keys=True)}
timeout = {float(self.memory_os_timeout_seconds)!r}
api_key = os.environ.get("WAVEMIND_API_KEY")
headers = {{"Content-Type": "application/json"}}
if api_key:
    headers["x-api-key"] = api_key

run_payload = dict(plan_payload)
run_payload.pop("cache_mode", None)
run_payload["lock_ttl_seconds"] = {int(self.memory_os_lock_ttl_seconds)}
run_payload["lock_prefix"] = {json.dumps(self.memory_os_lock_prefix)}

def post(node, path, payload):
    data = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        node.rstrip("/") + path,
        data=data,
        headers=headers,
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))

plan = post(nodes[0], "/memory-os/plan", plan_payload)
print(json.dumps({{"node": nodes[0], "plan": plan}}, ensure_ascii=False))
plan_tasks = {{
    task.get("id"): task
    for task in plan.get("tasks", [])
    if isinstance(task, dict) and task.get("id")
}}
memory_os_task = plan_tasks.get("memory-os") or {{}}
plan_requires_lock = bool(memory_os_task.get("requires_distributed_lock"))
run_payload["lock_required"] = {bool(self.memory_os_lock_required)!r} or plan_requires_lock
if plan.get("effective_cache_mode") == "redis" and not {bool(self.redis_url)!r}:
    print(
        json.dumps(
            {{
                "error": "memory-os-plan requires Redis but spec.cache.redisUrl is not configured",
                "policy_auto_adjustments": plan.get("policy_auto_adjustments", []),
                "policy_escalation_ids": plan.get("policy_escalation_ids", []),
            }},
            ensure_ascii=False,
        ),
        file=sys.stderr,
    )
    raise SystemExit(5)
if {bool(self.memory_os_strict_plan)!r} and plan.get("status") not in {{"ok", "watch"}}:
    raise SystemExit(3)

run_nodes = nodes if {bool(self.memory_os_run_on_all_replicas)!r} else nodes[:1]
failed = []
for node in run_nodes:
    report = post(node, "/memory-os/run", run_payload)
    print(json.dumps({{"node": node, "report": report}}, ensure_ascii=False))
    if not report.get("ok", False):
        failed.append(node)
if failed:
    print(json.dumps({{"failed_nodes": failed}}), file=sys.stderr)
    raise SystemExit(4)
""".strip()
        container: dict[str, Any] = {
            "name": "memory-os",
            "image": self.image,
            "imagePullPolicy": self.image_pull_policy,
            "command": ["python", "-c"],
            "args": [script],
        }
        if env:
            container["env"] = env
        return {
            "apiVersion": "batch/v1",
            "kind": "CronJob",
            "metadata": {
                "name": f"{self.name}-memory-os",
                "namespace": self.namespace,
                "labels": labels,
                "annotations": self._capacity_annotations(),
            },
            "spec": {
                "schedule": self.memory_os_schedule,
                "concurrencyPolicy": "Forbid",
                "successfulJobsHistoryLimit": 3,
                "failedJobsHistoryLimit": 3,
                "jobTemplate": {
                    "spec": {
                        "template": {
                            "metadata": {"labels": labels},
                            "spec": {
                                "restartPolicy": "OnFailure",
                                "containers": [container],
                            },
                        }
                    }
                },
            },
        }

    def _horizontal_pod_autoscaler(self) -> dict[str, Any]:
        labels = self._labels()
        metrics: list[dict[str, Any]] = [
            {
                "type": "Resource",
                "resource": {
                    "name": "cpu",
                    "target": {
                        "type": "Utilization",
                        "averageUtilization": self.autoscaling_target_cpu_utilization,
                    },
                },
            }
        ]
        if self.autoscaling_target_memory_utilization is not None:
            metrics.append(
                {
                    "type": "Resource",
                    "resource": {
                        "name": "memory",
                        "target": {
                            "type": "Utilization",
                            "averageUtilization": self.autoscaling_target_memory_utilization,
                        },
                    },
                }
            )
        return {
            "apiVersion": "autoscaling/v2",
            "kind": "HorizontalPodAutoscaler",
            "metadata": {
                "name": self.name,
                "namespace": self.namespace,
                "labels": labels,
                "annotations": self._capacity_annotations(),
            },
            "spec": {
                "scaleTargetRef": {
                    "apiVersion": "apps/v1",
                    "kind": "StatefulSet",
                    "name": self.name,
                },
                "minReplicas": self.autoscaling_min_replicas,
                "maxReplicas": self.autoscaling_max_replicas,
                "metrics": metrics,
            },
        }

    def _rebalance_configmap(self, rebalance=None) -> dict[str, Any]:
        labels = self._labels()
        rebalance = rebalance or self.capacity_rebalance_plan()
        assert rebalance is not None
        summary = {
            key: value
            for key, value in rebalance.as_dict().items()
            if key != "batches"
        }
        summary.update(
            {
                "target_memories": self.autoscaling_target_memories,
                "required_replicas": self.replicas,
                "preview_batches": min(
                    self.rebalance_preview_batches,
                    len(rebalance.batches),
                ),
            }
        )
        preview = [
            batch.as_dict()
            for batch in rebalance.batches[: self.rebalance_preview_batches]
        ]
        annotations = {
            **self._capacity_annotations(),
            **self._rebalance_annotations(rebalance),
        }
        return {
            "apiVersion": "v1",
            "kind": "ConfigMap",
            "metadata": {
                "name": f"{self.name}-rebalance-plan",
                "namespace": self.namespace,
                "labels": {**labels, "app.kubernetes.io/component": "rebalance-plan"},
                "annotations": annotations,
            },
            "data": {
                "rebalance-summary.json": json.dumps(summary, sort_keys=True),
                "rebalance-batches-preview.json": json.dumps(preview, sort_keys=True),
            },
        }

    def _capacity_required_replicas(self, *, seed_replicas: int) -> int:
        if self.autoscaling_target_memories is None:
            return self.replicas
        seed_nodes = tuple(
            ClusterNode(
                id=f"{self.name}-{index}",
                address=(
                    f"http://{self.name}-{index}.{self.headless_service_name}."
                    f"{self.namespace}.svc.cluster.local:{self.service_port}"
                ),
            )
            for index in range(seed_replicas)
        )
        plan = build_cluster_autoscale_plan(
            namespaces=self.namespaces,
            nodes=seed_nodes,
            replication_factor=self.replication_factor,
            target_memories=self.autoscaling_target_memories,
            max_memories_per_node=self.autoscaling_max_memories_per_node,
            headroom=self.autoscaling_headroom,
            node_prefix=self.name,
            address_template=(
                f"http://{{node_id}}.{self.headless_service_name}."
                f"{self.namespace}.svc.cluster.local:{self.service_port}"
            ),
            max_moves=0,
        )
        return plan.required_nodes

    def _capacity_annotations(self) -> dict[str, str]:
        if self.autoscaling_target_memories is None:
            return {}
        plan = self.capacity_autoscale_plan()
        assert plan is not None
        return {
            "memory.wavemind.ai/capacity-target-memories": str(self.autoscaling_target_memories),
            "memory.wavemind.ai/capacity-required-replicas": str(plan.required_nodes),
            "memory.wavemind.ai/capacity-target-max-node-memories": str(plan.target_max_node_memories),
            "memory.wavemind.ai/capacity-headroom": str(self.autoscaling_headroom),
        }

    def _rebalance_annotations(self, rebalance=None) -> dict[str, str]:
        if self.autoscaling_target_memories is None:
            return {}
        plan = rebalance or self.capacity_rebalance_plan()
        assert plan is not None
        return {
            "memory.wavemind.ai/rebalance-status": str(plan.status),
            "memory.wavemind.ai/rebalance-full-plan": "true" if plan.full_plan else "false",
            "memory.wavemind.ai/rebalance-move-count": str(plan.move_count),
            "memory.wavemind.ai/rebalance-batches": str(len(plan.batches)),
            "memory.wavemind.ai/rebalance-write-quorum": str(plan.write_quorum),
            "memory.wavemind.ai/rebalance-estimated-steps": str(plan.estimated_steps),
        }


def custom_resource_definition() -> dict[str, Any]:
    return {
        "apiVersion": "apiextensions.k8s.io/v1",
        "kind": "CustomResourceDefinition",
        "metadata": {"name": f"{RESOURCE_PLURAL}.{API_GROUP}"},
        "spec": {
            "group": API_GROUP,
            "scope": "Namespaced",
            "names": {
                "plural": RESOURCE_PLURAL,
                "singular": "wavemindcluster",
                "kind": RESOURCE_KIND,
                "shortNames": ["wmc"],
            },
            "versions": [
                {
                    "name": API_VERSION,
                    "served": True,
                    "storage": True,
                    "subresources": {"status": {}},
                    "schema": {
                        "openAPIV3Schema": {
                            "type": "object",
                            "properties": {
                                "spec": {
                                    "type": "object",
                                    "properties": {
                                        "image": {"type": "string"},
                                        "replicas": {"type": "integer", "minimum": 1},
                                        "replicationFactor": {"type": "integer", "minimum": 1},
                                        "namespaceCount": {"type": "integer", "minimum": 0},
                                        "namespacePrefix": {"type": "string"},
                                        "persistence": {
                                            "type": "object",
                                            "properties": {"size": {"type": "string"}},
                                        },
                                        "service": {
                                            "type": "object",
                                            "properties": {"port": {"type": "integer", "minimum": 1}},
                                        },
                                        "runtime": {"type": "object", "x-kubernetes-preserve-unknown-fields": True},
                                        "cache": {"type": "object", "x-kubernetes-preserve-unknown-fields": True},
                                        "auth": {"type": "object", "x-kubernetes-preserve-unknown-fields": True},
                                        "repair": {"type": "object", "x-kubernetes-preserve-unknown-fields": True},
                                        "memoryOs": {
                                            "type": "object",
                                            "properties": {
                                                "enabled": {"type": "boolean"},
                                                "schedule": {"type": "string"},
                                                "namespace": {"type": "string"},
                                                "auditLimit": {"type": "integer", "minimum": 1},
                                                "maxHotQueries": {"type": "integer", "minimum": 1},
                                                "minFrequency": {"type": "integer", "minimum": 1},
                                                "topK": {"type": "integer", "minimum": 1},
                                                "targetMemories": {"type": "integer", "minimum": 0},
                                                "cacheMode": {
                                                    "type": "string",
                                                    "enum": ["auto", "disabled", "local", "redis"],
                                                },
                                                "targetQps": {
                                                    "type": "number",
                                                    "minimum": 0,
                                                    "exclusiveMinimum": True,
                                                },
                                                "targetP99Ms": {
                                                    "type": "number",
                                                    "minimum": 0,
                                                    "exclusiveMinimum": True,
                                                },
                                                "observedP99Ms": {
                                                    "type": "number",
                                                    "minimum": 0,
                                                },
                                                "multimodal": {"type": "boolean"},
                                                "strictPlan": {"type": "boolean"},
                                                "lockRequired": {"type": "boolean"},
                                                "lockTtlSeconds": {
                                                    "type": "integer",
                                                    "minimum": 1,
                                                },
                                                "lockPrefix": {"type": "string"},
                                                "runOnAllReplicas": {"type": "boolean"},
                                                "timeoutSeconds": {
                                                    "type": "number",
                                                    "minimum": 0,
                                                    "exclusiveMinimum": True,
                                                },
                                            },
                                        },
                                        "productionAdmission": {
                                            "type": "object",
                                            "properties": {
                                                "enabled": {"type": "boolean"},
                                                "targetMemories": {
                                                    "type": "integer",
                                                    "minimum": 0,
                                                },
                                                "engine": {"type": "string"},
                                                "deployment": {"type": "string"},
                                                "evidenceRoot": {"type": "string"},
                                            },
                                        },
                                        "controlPlane": {
                                            "type": "object",
                                            "properties": {
                                                "consensus": {
                                                    "type": "object",
                                                    "properties": {
                                                        "enabled": {"type": "boolean"},
                                                        "leaseTtlSeconds": {
                                                            "type": "number",
                                                            "minimum": 0,
                                                            "exclusiveMinimum": True,
                                                        },
                                                        "configRevision": {
                                                            "type": "integer",
                                                            "minimum": 0,
                                                        },
                                                    },
                                                }
                                            },
                                        },
                                        "autoscaling": {
                                            "type": "object",
                                            "properties": {
                                                "enabled": {"type": "boolean"},
                                                "minReplicas": {"type": "integer", "minimum": 1},
                                                "maxReplicas": {"type": "integer", "minimum": 1},
                                                "targetCPUUtilizationPercentage": {
                                                    "type": "integer",
                                                    "minimum": 1,
                                                    "maximum": 100,
                                                },
                                                "targetMemoryUtilizationPercentage": {
                                                    "type": "integer",
                                                    "minimum": 1,
                                                    "maximum": 100,
                                                },
                                                "targetMemories": {"type": "integer", "minimum": 0},
                                                "maxMemoriesPerNode": {"type": "integer", "minimum": 1},
                                                "headroom": {
                                                    "type": "number",
                                                    "minimum": 0,
                                                    "exclusiveMinimum": True,
                                                    "maximum": 1,
                                                },
                                                "rebalance": {
                                                    "type": "object",
                                                    "properties": {
                                                        "batchSize": {
                                                            "type": "integer",
                                                            "minimum": 1,
                                                        },
                                                        "maxNodeMovesPerBatch": {
                                                            "type": "integer",
                                                            "minimum": 1,
                                                        },
                                                        "previewBatches": {
                                                            "type": "integer",
                                                            "minimum": 0,
                                                        },
                                                    },
                                                },
                                            },
                                        },
                                        "resources": {"type": "object", "x-kubernetes-preserve-unknown-fields": True},
                                    },
                                },
                                "status": {
                                    "type": "object",
                                    "x-kubernetes-preserve-unknown-fields": True,
                                },
                            },
                        }
                    },
                }
            ],
        },
    }


def operator_bundle(
    *,
    operator_image: str = "ghcr.io/caspiang/wavemind:latest",
    namespace: str = "default",
    sample: WaveMindClusterSpec | None = None,
    operator_replicas: int = 2,
    operator_interval_seconds: float = 30.0,
    lease_duration_seconds: int = 60,
) -> dict[str, Any]:
    if operator_replicas < 2:
        raise ValueError("operator_replicas must be at least 2 for failover")
    if lease_duration_seconds <= 0:
        raise ValueError("lease_duration_seconds must be positive")
    if operator_interval_seconds <= 0:
        raise ValueError("operator_interval_seconds must be positive")
    if lease_duration_seconds <= operator_interval_seconds:
        raise ValueError("lease_duration_seconds must be greater than operator_interval_seconds")
    sample_spec = sample or WaveMindClusterSpec(namespace=namespace)
    service_account = {
        "apiVersion": "v1",
        "kind": "ServiceAccount",
        "metadata": {"name": "wavemind-operator", "namespace": namespace},
    }
    role = {
        "apiVersion": "rbac.authorization.k8s.io/v1",
        "kind": "ClusterRole",
        "metadata": {"name": "wavemind-operator"},
        "rules": [
            {
                "apiGroups": [API_GROUP],
                "resources": [RESOURCE_PLURAL],
                "verbs": ["get", "list", "watch", "patch", "update"],
            },
            {
                "apiGroups": [API_GROUP],
                "resources": [f"{RESOURCE_PLURAL}/status"],
                "verbs": ["get", "patch", "update"],
            },
            {
                "apiGroups": [""],
                "resources": ["services"],
                "verbs": ["get", "list", "watch", "create", "patch", "update"],
            },
            {
                "apiGroups": [""],
                "resources": ["configmaps"],
                "verbs": ["get", "list", "watch", "create", "patch", "update"],
            },
            {
                "apiGroups": ["apps"],
                "resources": ["statefulsets"],
                "verbs": ["get", "list", "watch", "create", "patch", "update"],
            },
            {
                "apiGroups": ["batch"],
                "resources": ["cronjobs"],
                "verbs": ["get", "list", "watch", "create", "patch", "update"],
            },
            {
                "apiGroups": ["autoscaling"],
                "resources": ["horizontalpodautoscalers"],
                "verbs": ["get", "list", "watch", "create", "patch", "update"],
            },
            {
                "apiGroups": ["policy"],
                "resources": ["poddisruptionbudgets"],
                "verbs": ["get", "list", "watch", "create", "patch", "update"],
            },
            {
                "apiGroups": ["coordination.k8s.io"],
                "resources": ["leases"],
                "verbs": ["get", "list", "watch", "create", "patch", "update"],
            },
        ],
    }
    binding = {
        "apiVersion": "rbac.authorization.k8s.io/v1",
        "kind": "ClusterRoleBinding",
        "metadata": {"name": "wavemind-operator"},
        "subjects": [
            {
                "kind": "ServiceAccount",
                "name": "wavemind-operator",
                "namespace": namespace,
            }
        ],
        "roleRef": {
            "apiGroup": "rbac.authorization.k8s.io",
            "kind": "ClusterRole",
            "name": "wavemind-operator",
        },
    }
    deployment = {
        "apiVersion": "apps/v1",
        "kind": "Deployment",
        "metadata": {"name": "wavemind-operator", "namespace": namespace},
        "spec": {
            "replicas": operator_replicas,
            "strategy": {
                "type": "RollingUpdate",
                "rollingUpdate": {"maxUnavailable": 1, "maxSurge": 1},
            },
            "selector": {"matchLabels": {"app.kubernetes.io/name": "wavemind-operator"}},
            "template": {
                "metadata": {"labels": {"app.kubernetes.io/name": "wavemind-operator"}},
                "spec": {
                    "serviceAccountName": "wavemind-operator",
                    "affinity": {
                        "podAntiAffinity": {
                            "preferredDuringSchedulingIgnoredDuringExecution": [
                                {
                                    "weight": 100,
                                    "podAffinityTerm": {
                                        "topologyKey": "kubernetes.io/hostname",
                                        "labelSelector": {
                                            "matchLabels": {
                                                "app.kubernetes.io/name": "wavemind-operator"
                                            }
                                        },
                                    },
                                }
                            ]
                        }
                    },
                    "containers": [
                        {
                            "name": "operator",
                            "image": operator_image,
                            "imagePullPolicy": "IfNotPresent",
                            "command": ["wavemind"],
                            "env": [
                                {
                                    "name": "POD_NAME",
                                    "valueFrom": {"fieldRef": {"fieldPath": "metadata.name"}},
                                },
                                {
                                    "name": "POD_NAMESPACE",
                                    "valueFrom": {"fieldRef": {"fieldPath": "metadata.namespace"}},
                                },
                            ],
                            "args": [
                                "operator-loop",
                                "--namespace",
                                "$(POD_NAMESPACE)",
                                "--holder-identity",
                                "$(POD_NAME)",
                                "--interval-seconds",
                                str(float(operator_interval_seconds)),
                                "--lease-name",
                                "wavemind-operator",
                                "--lease-duration-seconds",
                                str(int(lease_duration_seconds)),
                            ],
                        }
                    ],
                },
            },
        },
    }
    return {
        "apiVersion": "v1",
        "kind": "List",
        "items": [
            custom_resource_definition(),
            service_account,
            role,
            binding,
            deployment,
            sample_spec.custom_resource(),
        ],
    }


def operator_reconcile(resource: dict[str, Any]) -> dict[str, Any]:
    spec = WaveMindClusterSpec.from_custom_resource(resource)
    rebalance = spec.capacity_rebalance_plan()
    payload = spec.as_resource_list(spec.reconciled_resources(rebalance_plan=rebalance))
    payload["operatorStatus"] = operator_status(resource, rebalance_plan=rebalance)
    return payload


def operator_status(
    resource: dict[str, Any],
    *,
    observed: dict[str, Any] | None = None,
    rebalance_plan: Any | None = None,
) -> dict[str, Any]:
    """Build a WaveMindCluster status payload from spec and observed metrics."""

    spec = WaveMindClusterSpec.from_custom_resource(resource)
    metadata = dict(resource.get("metadata") or {})
    observed_payload = dict(observed or {})
    generation = _optional_int(metadata.get("generation")) or 1
    desired_replicas = int(spec.replicas)
    ready_replicas = _observed_int(
        observed_payload,
        "readyReplicas",
        "ready_replicas",
        default=desired_replicas,
    )
    current_replicas = _observed_int(
        observed_payload,
        "currentReplicas",
        "current_replicas",
        default=ready_replicas,
    )
    hpa_desired_replicas = _observed_int(
        observed_payload,
        "hpaDesiredReplicas",
        "hpa_desired_replicas",
        default=desired_replicas,
    )
    unavailable_nodes = _observed_int(
        observed_payload,
        "unavailableNodes",
        "unavailable_nodes",
        default=max(0, desired_replicas - ready_replicas),
    )
    degraded_nodes = _observed_int(
        observed_payload,
        "degradedNodes",
        "degraded_nodes",
        default=0,
    )
    current_memories = _observed_int(
        observed_payload,
        "currentMemories",
        "current_memories",
        default=0,
    )

    plan = spec.capacity_autoscale_plan()
    required_replicas = int(plan.required_nodes if plan is not None else desired_replicas)
    target_max_node_memories = (
        int(plan.target_max_node_memories)
        if plan is not None
        else None
    )
    capacity_within_headroom = (
        True
        if plan is None
        else bool(plan.target_max_node_memories <= int(plan.max_memories_per_node * plan.headroom))
    )
    capacity_ready = (
        desired_replicas >= required_replicas
        and spec.autoscaling_max_replicas >= required_replicas
        and capacity_within_headroom
    )
    rebalance = rebalance_plan if rebalance_plan is not None else spec.capacity_rebalance_plan()
    rebalance_batches = int(len(rebalance.batches) if rebalance is not None else 0)
    rebalance_full_plan = True if rebalance is None else bool(rebalance.full_plan)
    rebalance_safety_ready = (
        True
        if rebalance is None
        else (
            rebalance.status in {"ready", "noop", "ok"}
            and rebalance.full_plan
            and rebalance.omitted_moves == 0
            and rebalance.write_quorum >= (spec.replication_factor // 2 + 1)
            and all(batch.requires_checkpoint for batch in rebalance.batches)
            and all(batch.requires_repair for batch in rebalance.batches)
            and all(batch.requires_validation for batch in rebalance.batches)
        )
    )
    resources_ready = (
        ready_replicas >= desired_replicas
        and current_replicas >= desired_replicas
        and unavailable_nodes == 0
        and degraded_nodes == 0
    )
    autoscaling_ready = (
        not spec.autoscaling_enabled
        or (
            spec.autoscaling_min_replicas <= desired_replicas <= spec.autoscaling_max_replicas
            and hpa_desired_replicas <= spec.autoscaling_max_replicas
            and spec.autoscaling_max_replicas >= required_replicas
        )
    )
    repair_ready = bool(spec.repair_enabled and spec.namespace_count > 0)
    memory_os_requires_redis = spec.memory_os_requires_redis()
    memory_os_ready = (
        not spec.memory_os_enabled
        or (
            spec.namespace_count > 0
            and (not memory_os_requires_redis or bool(spec.redis_url))
        )
    )
    production_admission_enabled = spec.production_admission_guard_enabled()
    production_admission_required = spec.production_admission_required()
    production_admission_ready = spec.production_admission_ready()
    control_plane = spec.control_plane_consensus_report()
    control_plane_ready = bool(control_plane.get("ready"))
    ready = (
        resources_ready
        and capacity_ready
        and rebalance_safety_ready
        and autoscaling_ready
        and repair_ready
        and memory_os_ready
        and production_admission_ready
        and control_plane_ready
    )
    timestamp = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

    conditions = [
        _operator_condition(
            "ResourcesReady",
            resources_ready,
            "AllReplicasReady" if resources_ready else "ReplicasUnavailable",
            (
                f"{ready_replicas}/{desired_replicas} replicas ready; "
                f"degraded={degraded_nodes}, unavailable={unavailable_nodes}"
            ),
            timestamp,
        ),
        _operator_condition(
            "CapacityPlanned",
            capacity_ready,
            "CapacityWithinHeadroom" if capacity_ready else "CapacityPlanBlocked",
            (
                f"required replicas {required_replicas}; "
                f"target max node memories {target_max_node_memories}"
            ),
            timestamp,
        ),
        _operator_condition(
            "AutoscalingReady",
            autoscaling_ready,
            "AutoscalingConfigured" if autoscaling_ready else "AutoscalingBlocked",
            (
                f"HPA desired {hpa_desired_replicas}; max replicas "
                f"{spec.autoscaling_max_replicas}"
            ),
            timestamp,
        ),
        _operator_condition(
            "RebalancePlanned",
            rebalance_safety_ready,
            (
                "RebalancePlanReady"
                if rebalance_safety_ready and rebalance is not None
                else "RebalanceNotRequired"
                if rebalance is None
                else "RebalancePlanBlocked"
            ),
            (
                f"status={rebalance.status if rebalance is not None else 'not_required'}; "
                f"full={rebalance_full_plan}; batches={rebalance_batches}; "
                f"write_quorum={rebalance.write_quorum if rebalance is not None else None}"
            ),
            timestamp,
        ),
        _operator_condition(
            "RepairScheduled",
            repair_ready,
            "RepairCronJobEnabled" if repair_ready else "RepairDisabled",
            (
                f"repair enabled={spec.repair_enabled}; "
                f"namespaces={spec.namespace_count}"
            ),
            timestamp,
        ),
        _operator_condition(
            "MemoryOSReady",
            memory_os_ready,
            (
                "MemoryOSCronJobReady"
                if spec.memory_os_enabled and memory_os_ready
                else "MemoryOSNotEnabled"
                if not spec.memory_os_enabled
                else "MemoryOSRedisRequired"
            ),
            (
                f"enabled={spec.memory_os_enabled}; "
                f"cache_mode={spec.memory_os_cache_mode}; "
                f"redis_required={memory_os_requires_redis}; "
                f"redis_configured={bool(spec.redis_url)}"
            ),
            timestamp,
        ),
        _operator_condition(
            "ProductionAdmissionReady",
            production_admission_ready,
            (
                "ProductionAdmissionGuardEnabled"
                if production_admission_enabled
                else "ProductionAdmissionNotRequired"
            )
            if production_admission_ready
            else "ProductionAdmissionGuardRequired",
            (
                f"enabled={production_admission_enabled}; "
                f"required={production_admission_required}; "
                f"target_memories={spec.production_admission_target()}; "
                f"evidence_root={spec.production_admission_root}"
            ),
            timestamp,
        ),
        _operator_condition(
            "ControlPlaneReady",
            control_plane_ready,
            "ConsensusLeaseSafe" if control_plane_ready else "ConsensusBlocked",
            (
                f"enabled={control_plane.get('enabled')}; "
                f"ready={control_plane_ready}"
            ),
            timestamp,
        ),
    ]
    actions: list[str] = []
    if not resources_ready:
        actions.append("Wait for StatefulSet replicas to become ready before routing production traffic.")
    if not capacity_ready:
        actions.append("Increase autoscaling maxReplicas or reduce target memories per cluster before growth.")
    elif required_replicas > desired_replicas:
        actions.append("Reconcile StatefulSet replicas to the calculated capacity requirement.")
    if not autoscaling_ready:
        actions.append("Fix HPA min/max bounds so capacity-required replicas fit inside autoscaling limits.")
    if not rebalance_safety_ready:
        actions.append("Generate a full rolling rebalance plan with checkpoint, repair, and validation gates.")
    if degraded_nodes or unavailable_nodes:
        actions.append("Run cluster-health and cluster-repair before declaring the cluster ready.")
    if not repair_ready:
        actions.append("Enable scheduled cluster repair for replicated namespace deployments.")
    if spec.memory_os_enabled and not memory_os_ready:
        actions.append("Configure cache.redisUrl before enabling production Memory OS scheduling.")
    if not production_admission_ready:
        actions.append(
            "Enable productionAdmission before declaring 10M+ clusters ready; "
            "the API startup guard must block unproven large-scale claims."
        )
    if not control_plane_ready:
        actions.append("Enable and pass control-plane consensus safety before applying production config changes.")
    if not actions:
        actions.append("Cluster status is ready; keep readiness, repair, and load gates scheduled.")

    return {
        "observedGeneration": generation,
        "ready": ready,
        "phase": "Ready" if ready else "Degraded",
        "desiredReplicas": desired_replicas,
        "currentReplicas": current_replicas,
        "readyReplicas": ready_replicas,
        "unavailableNodes": unavailable_nodes,
        "degradedNodes": degraded_nodes,
        "currentMemories": current_memories,
        "targetMemories": spec.autoscaling_target_memories,
        "replicationFactor": spec.replication_factor,
        "capacity": {
            "requiredReplicas": required_replicas,
            "maxReplicas": spec.autoscaling_max_replicas,
            "maxMemoriesPerNode": spec.autoscaling_max_memories_per_node,
            "targetMaxNodeMemories": target_max_node_memories,
            "headroom": spec.autoscaling_headroom,
            "withinHeadroom": capacity_within_headroom,
        },
        "autoscaling": {
            "enabled": spec.autoscaling_enabled,
            "minReplicas": spec.autoscaling_min_replicas,
            "maxReplicas": spec.autoscaling_max_replicas,
            "hpaDesiredReplicas": hpa_desired_replicas,
        },
        "rebalance": {
            "required": rebalance is not None,
            "ready": rebalance_safety_ready,
            "status": rebalance.status if rebalance is not None else "not_required",
            "fullPlan": rebalance_full_plan,
            "moveCount": int(rebalance.move_count if rebalance is not None else 0),
            "omittedMoves": int(rebalance.omitted_moves if rebalance is not None else 0),
            "batchSize": int(rebalance.batch_size if rebalance is not None else spec.rebalance_batch_size),
            "batchCount": rebalance_batches,
            "estimatedSteps": int(rebalance.estimated_steps if rebalance is not None else 0),
            "writeQuorum": int(rebalance.write_quorum if rebalance is not None else 0),
            "checkpointRequired": (
                all(batch.requires_checkpoint for batch in rebalance.batches)
                if rebalance is not None
                else False
            ),
            "repairRequired": (
                all(batch.requires_repair for batch in rebalance.batches)
                if rebalance is not None
                else False
            ),
            "validationRequired": (
                all(batch.requires_validation for batch in rebalance.batches)
                if rebalance is not None
                else False
            ),
            "configMapName": (
                f"{spec.name}-rebalance-plan"
                if rebalance is not None
                else None
            ),
        },
        "memoryOs": {
            "enabled": spec.memory_os_enabled,
            "ready": memory_os_ready,
            "cronJobName": f"{spec.name}-memory-os" if spec.memory_os_enabled else None,
            "cacheMode": spec.memory_os_cache_mode,
            "redisRequired": memory_os_requires_redis,
            "redisConfigured": bool(spec.redis_url),
            "lockRequired": spec.memory_os_lock_required,
            "strictPlan": spec.memory_os_strict_plan,
            "runOnAllReplicas": spec.memory_os_run_on_all_replicas,
        },
        "productionAdmission": {
            "enabled": production_admission_enabled,
            "configured": spec.production_admission_enabled,
            "required": production_admission_required,
            "ready": production_admission_ready,
            "targetMemories": spec.production_admission_target(),
            "engine": spec.production_admission_engine,
            "deployment": spec.production_admission_deployment,
            "evidenceRoot": spec.production_admission_root,
        },
        "controlPlane": control_plane,
        "conditions": conditions,
        "actions": actions,
        "lastTransitionTime": timestamp,
    }


@dataclass(frozen=True)
class KubernetesResourcePath:
    api_path: str
    collection_path: str


@dataclass(frozen=True)
class KubernetesLeaderElectionReport:
    namespace: str
    lease_name: str
    holder_identity: str
    current_holder: str | None
    acquired: bool
    renewed: bool
    lease_duration_seconds: int
    lease_transitions: int
    resource_version: str | None = None
    reason: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "namespace": self.namespace,
            "leaseName": self.lease_name,
            "holderIdentity": self.holder_identity,
            "currentHolder": self.current_holder,
            "acquired": self.acquired,
            "renewed": self.renewed,
            "leaseDurationSeconds": self.lease_duration_seconds,
            "leaseTransitions": self.lease_transitions,
            "resourceVersion": self.resource_version,
            "reason": self.reason,
            "backend": "kubernetes-lease-etcd",
        }


class KubernetesApplyClient:
    """Minimal stdlib Kubernetes client for the WaveMind operator loop."""

    def __init__(
        self,
        *,
        host: str,
        token: str,
        ca_cert: str | Path | None = None,
        timeout: float = 10.0,
    ):
        self.host = host.rstrip("/")
        self.token = token
        self.timeout = float(timeout)
        self.ssl_context = None
        if ca_cert:
            self.ssl_context = ssl.create_default_context(cafile=str(ca_cert))

    @classmethod
    def in_cluster(
        cls,
        *,
        service_account_root: str | Path = SERVICE_ACCOUNT_ROOT,
        timeout: float = 10.0,
    ) -> "KubernetesApplyClient":
        root = Path(service_account_root)
        token = (root / "token").read_text(encoding="utf-8").strip()
        host = "https://kubernetes.default.svc"
        return cls(host=host, token=token, ca_cert=root / "ca.crt", timeout=timeout)

    def list_wavemind_clusters(self, namespace: str) -> list[dict[str, Any]]:
        payload = self._request(
            "GET",
            f"/apis/{API_GROUP}/{API_VERSION}/namespaces/{namespace}/{RESOURCE_PLURAL}",
        )
        return [dict(item) for item in payload.get("items", [])]

    def apply(self, resource: dict[str, Any], *, field_manager: str = "wavemind-operator") -> dict[str, Any]:
        path = kubernetes_resource_path(resource)
        query = urlencode({"fieldManager": field_manager, "force": "true"})
        try:
            return self._request(
                "PATCH",
                f"{path.api_path}?{query}",
                payload=resource,
                content_type="application/apply-patch+yaml",
            )
        except HTTPError as exc:
            if exc.code != 404:
                raise
            return self._request(
                "POST",
                path.collection_path,
                payload=resource,
                content_type="application/json",
            )

    def patch_wavemind_cluster_status(
        self,
        *,
        namespace: str,
        name: str,
        status: dict[str, Any],
        field_manager: str = "wavemind-operator",
    ) -> dict[str, Any]:
        query = urlencode({"fieldManager": field_manager, "force": "true"})
        payload = {
            "apiVersion": f"{API_GROUP}/{API_VERSION}",
            "kind": RESOURCE_KIND,
            "metadata": {"name": name, "namespace": namespace},
            "status": status,
        }
        return self._request(
            "PATCH",
            (
                f"/apis/{API_GROUP}/{API_VERSION}/namespaces/{namespace}/"
                f"{RESOURCE_PLURAL}/{name}/status?{query}"
            ),
            payload=payload,
            content_type="application/apply-patch+yaml",
        )

    def acquire_or_renew_operator_lease(
        self,
        *,
        namespace: str,
        lease_name: str,
        holder_identity: str,
        lease_duration_seconds: int = 60,
        now: datetime | None = None,
    ) -> KubernetesLeaderElectionReport:
        """Acquire or renew a Kubernetes Lease with resourceVersion CAS.

        Kubernetes persists Lease objects through its API server/etcd. Updating
        the current resourceVersion makes simultaneous operator replicas race
        safely: only one update succeeds, and followers stay read-only.
        """

        namespace = str(namespace).strip()
        lease_name = str(lease_name).strip()
        holder_identity = str(holder_identity).strip()
        if not namespace or not lease_name or not holder_identity:
            raise ValueError("namespace, lease_name, and holder_identity are required")
        if lease_duration_seconds <= 0:
            raise ValueError("lease_duration_seconds must be positive")

        timestamp = _as_utc_datetime(now)
        collection = f"/apis/coordination.k8s.io/v1/namespaces/{namespace}/leases"
        path = f"{collection}/{lease_name}"
        current = self._get_optional(path)
        if current is None:
            payload = _operator_lease_payload(
                namespace=namespace,
                lease_name=lease_name,
                holder_identity=holder_identity,
                lease_duration_seconds=lease_duration_seconds,
                now=timestamp,
                lease_transitions=0,
            )
            try:
                created = self._request("POST", collection, payload=payload)
            except HTTPError as exc:
                if exc.code != 409:
                    raise
                winner = self._get_optional(path) or {}
                return _lease_conflict_report(
                    namespace=namespace,
                    lease_name=lease_name,
                    holder_identity=holder_identity,
                    lease_duration_seconds=lease_duration_seconds,
                    current=winner,
                    reason="create_conflict",
                )
            return _lease_success_report(
                namespace=namespace,
                lease_name=lease_name,
                holder_identity=holder_identity,
                lease_duration_seconds=lease_duration_seconds,
                current=created or payload,
                renewed=False,
            )

        metadata = dict(current.get("metadata") or {})
        spec = dict(current.get("spec") or {})
        resource_version = _optional_string(metadata.get("resourceVersion"))
        current_holder = _optional_string(spec.get("holderIdentity"))
        current_duration = _optional_int(spec.get("leaseDurationSeconds")) or lease_duration_seconds
        renewed_at = _parse_kubernetes_time(spec.get("renewTime") or spec.get("acquireTime"))
        expired = renewed_at is None or timestamp >= renewed_at + timedelta(seconds=current_duration)
        same_holder = current_holder == holder_identity
        transitions = max(0, _optional_int(spec.get("leaseTransitions")) or 0)
        if current_holder and not same_holder and not expired:
            return KubernetesLeaderElectionReport(
                namespace=namespace,
                lease_name=lease_name,
                holder_identity=holder_identity,
                current_holder=current_holder,
                acquired=False,
                renewed=False,
                lease_duration_seconds=current_duration,
                lease_transitions=transitions,
                resource_version=resource_version,
                reason="lease_held",
            )

        if resource_version is None:
            return KubernetesLeaderElectionReport(
                namespace=namespace,
                lease_name=lease_name,
                holder_identity=holder_identity,
                current_holder=current_holder,
                acquired=False,
                renewed=False,
                lease_duration_seconds=current_duration,
                lease_transitions=transitions,
                resource_version=None,
                reason="missing_resource_version",
            )

        if current_holder and not same_holder:
            transitions += 1
        payload = _operator_lease_payload(
            namespace=namespace,
            lease_name=lease_name,
            holder_identity=holder_identity,
            lease_duration_seconds=lease_duration_seconds,
            now=timestamp,
            lease_transitions=transitions,
            resource_version=resource_version,
            acquire_time=(
                _optional_string(spec.get("acquireTime"))
                if same_holder
                else None
            ),
        )
        try:
            updated = self._request("PUT", path, payload=payload)
        except HTTPError as exc:
            if exc.code != 409:
                raise
            winner = self._get_optional(path) or current
            return _lease_conflict_report(
                namespace=namespace,
                lease_name=lease_name,
                holder_identity=holder_identity,
                lease_duration_seconds=lease_duration_seconds,
                current=winner,
                reason="update_conflict",
            )
        return _lease_success_report(
            namespace=namespace,
            lease_name=lease_name,
            holder_identity=holder_identity,
            lease_duration_seconds=lease_duration_seconds,
            current=updated or payload,
            renewed=same_holder,
        )

    def _get_optional(self, path: str) -> dict[str, Any] | None:
        try:
            return self._request("GET", path)
        except HTTPError as exc:
            if exc.code == 404:
                return None
            raise

    def _request(
        self,
        method: str,
        path: str,
        *,
        payload: dict[str, Any] | None = None,
        content_type: str = "application/json",
    ) -> dict[str, Any]:
        body = None
        headers = {
            "Accept": "application/json",
            "Authorization": f"Bearer {self.token}",
        }
        if payload is not None:
            body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            headers["Content-Type"] = content_type
        request = Request(
            f"{self.host}{path}",
            data=body,
            method=method,
            headers=headers,
        )
        with urlopen(request, timeout=self.timeout, context=self.ssl_context) as response:
            raw = response.read().decode("utf-8")
        return json.loads(raw or "{}")


def operator_loop(
    *,
    namespace: str,
    client: KubernetesApplyClient,
    interval_seconds: float = 30.0,
    once: bool = False,
    leader_election: bool = True,
    holder_identity: str = "wavemind-operator",
    lease_name: str = "wavemind-operator",
    lease_duration_seconds: int = 60,
) -> dict[str, Any]:
    if interval_seconds <= 0:
        raise ValueError("interval_seconds must be positive")
    if leader_election and lease_duration_seconds <= interval_seconds:
        raise ValueError("lease_duration_seconds must be greater than interval_seconds")
    last_report: dict[str, Any] = {}
    while True:
        if leader_election:
            acquire = getattr(client, "acquire_or_renew_operator_lease", None)
            if not callable(acquire):
                raise RuntimeError("Kubernetes client does not support operator leader election")
            election = acquire(
                namespace=namespace,
                lease_name=lease_name,
                holder_identity=holder_identity,
                lease_duration_seconds=lease_duration_seconds,
            )
            election_payload = election.as_dict()
            if not election.acquired:
                last_report = {
                    "namespace": namespace,
                    "clusters": 0,
                    "applied": [],
                    "applied_count": 0,
                    "statuses": [],
                    "leaderElection": election_payload,
                }
                if once:
                    return last_report
                time.sleep(interval_seconds)
                continue
        else:
            election_payload = {
                "namespace": namespace,
                "leaseName": lease_name,
                "holderIdentity": holder_identity,
                "currentHolder": holder_identity,
                "acquired": True,
                "renewed": False,
                "leaseDurationSeconds": lease_duration_seconds,
                "leaseTransitions": 0,
                "resourceVersion": None,
                "reason": "leader_election_disabled",
                "backend": "disabled",
            }
        clusters = client.list_wavemind_clusters(namespace)
        applied: list[dict[str, Any]] = []
        statuses: list[dict[str, Any]] = []
        for cluster in clusters:
            for resource in operator_reconcile(cluster)["items"]:
                client.apply(resource)
                applied.append(
                    {
                        "kind": resource["kind"],
                        "name": resource["metadata"]["name"],
                        "namespace": resource["metadata"].get("namespace", namespace),
                    }
                )
            status = operator_status(cluster)
            status["operatorLeader"] = election_payload
            statuses.append(
                {
                    "name": str((cluster.get("metadata") or {}).get("name") or "wavemind"),
                    "namespace": str((cluster.get("metadata") or {}).get("namespace") or namespace),
                    "ready": bool(status.get("ready")),
                    "phase": status.get("phase"),
                    "requiredReplicas": dict(status.get("capacity") or {}).get("requiredReplicas"),
                    "memoryOsReady": dict(status.get("memoryOs") or {}).get("ready"),
                    "memoryOsRedisRequired": dict(status.get("memoryOs") or {}).get("redisRequired"),
                    "memoryOsRedisConfigured": dict(status.get("memoryOs") or {}).get("redisConfigured"),
                    "productionAdmissionReady": dict(status.get("productionAdmission") or {}).get("ready"),
                    "productionAdmissionEnabled": dict(status.get("productionAdmission") or {}).get("enabled"),
                    "controlPlaneReady": dict(status.get("controlPlane") or {}).get("ready"),
                }
            )
            patch_status = getattr(client, "patch_wavemind_cluster_status", None)
            if callable(patch_status):
                metadata = dict(cluster.get("metadata") or {})
                patch_status(
                    namespace=str(metadata.get("namespace") or namespace),
                    name=str(metadata.get("name") or "wavemind"),
                    status=status,
                )
        last_report = {
            "namespace": namespace,
            "clusters": len(clusters),
            "applied": applied,
            "applied_count": len(applied),
            "statuses": statuses,
            "leaderElection": election_payload,
        }
        if once:
            return last_report
        time.sleep(interval_seconds)


def kubernetes_resource_path(resource: dict[str, Any]) -> KubernetesResourcePath:
    kind = str(resource.get("kind") or "")
    metadata = dict(resource.get("metadata") or {})
    name = str(metadata.get("name") or "")
    namespace = str(metadata.get("namespace") or "default")
    if not kind or not name:
        raise ValueError("Kubernetes resource requires kind and metadata.name")
    if kind == "Service":
        collection = f"/api/v1/namespaces/{namespace}/services"
    elif kind == "ConfigMap":
        collection = f"/api/v1/namespaces/{namespace}/configmaps"
    elif kind == "StatefulSet":
        collection = f"/apis/apps/v1/namespaces/{namespace}/statefulsets"
    elif kind == "CronJob":
        collection = f"/apis/batch/v1/namespaces/{namespace}/cronjobs"
    elif kind == "HorizontalPodAutoscaler":
        collection = f"/apis/autoscaling/v2/namespaces/{namespace}/horizontalpodautoscalers"
    elif kind == "PodDisruptionBudget":
        collection = f"/apis/policy/v1/namespaces/{namespace}/poddisruptionbudgets"
    elif kind == "Lease":
        collection = f"/apis/coordination.k8s.io/v1/namespaces/{namespace}/leases"
    else:
        raise ValueError(f"Unsupported reconciled resource kind: {kind}")
    return KubernetesResourcePath(
        api_path=f"{collection}/{name}",
        collection_path=collection,
    )


def _as_utc_datetime(value: datetime | None) -> datetime:
    if value is None:
        return datetime.now(timezone.utc)
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _format_kubernetes_time(value: datetime) -> str:
    return _as_utc_datetime(value).isoformat(timespec="microseconds").replace("+00:00", "Z")


def _parse_kubernetes_time(value: object) -> datetime | None:
    text = _optional_string(value)
    if text is None:
        return None
    try:
        return _as_utc_datetime(datetime.fromisoformat(text.replace("Z", "+00:00")))
    except ValueError:
        return None


def _operator_lease_payload(
    *,
    namespace: str,
    lease_name: str,
    holder_identity: str,
    lease_duration_seconds: int,
    now: datetime,
    lease_transitions: int,
    resource_version: str | None = None,
    acquire_time: str | None = None,
) -> dict[str, Any]:
    metadata: dict[str, Any] = {"name": lease_name, "namespace": namespace}
    if resource_version:
        metadata["resourceVersion"] = resource_version
    timestamp = _format_kubernetes_time(now)
    return {
        "apiVersion": "coordination.k8s.io/v1",
        "kind": "Lease",
        "metadata": metadata,
        "spec": {
            "holderIdentity": holder_identity,
            "leaseDurationSeconds": int(lease_duration_seconds),
            "acquireTime": acquire_time or timestamp,
            "renewTime": timestamp,
            "leaseTransitions": int(lease_transitions),
        },
    }


def _lease_success_report(
    *,
    namespace: str,
    lease_name: str,
    holder_identity: str,
    lease_duration_seconds: int,
    current: dict[str, Any],
    renewed: bool,
) -> KubernetesLeaderElectionReport:
    metadata = dict(current.get("metadata") or {})
    spec = dict(current.get("spec") or {})
    return KubernetesLeaderElectionReport(
        namespace=namespace,
        lease_name=lease_name,
        holder_identity=holder_identity,
        current_holder=_optional_string(spec.get("holderIdentity")) or holder_identity,
        acquired=True,
        renewed=renewed,
        lease_duration_seconds=_optional_int(spec.get("leaseDurationSeconds")) or lease_duration_seconds,
        lease_transitions=max(0, _optional_int(spec.get("leaseTransitions")) or 0),
        resource_version=_optional_string(metadata.get("resourceVersion")),
        reason="renewed" if renewed else "acquired",
    )


def _lease_conflict_report(
    *,
    namespace: str,
    lease_name: str,
    holder_identity: str,
    lease_duration_seconds: int,
    current: dict[str, Any],
    reason: str,
) -> KubernetesLeaderElectionReport:
    metadata = dict(current.get("metadata") or {})
    spec = dict(current.get("spec") or {})
    return KubernetesLeaderElectionReport(
        namespace=namespace,
        lease_name=lease_name,
        holder_identity=holder_identity,
        current_holder=_optional_string(spec.get("holderIdentity")),
        acquired=False,
        renewed=False,
        lease_duration_seconds=_optional_int(spec.get("leaseDurationSeconds")) or lease_duration_seconds,
        lease_transitions=max(0, _optional_int(spec.get("leaseTransitions")) or 0),
        resource_version=_optional_string(metadata.get("resourceVersion")),
        reason=reason,
    )


def _optional_string(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _optional_int(value: object) -> int | None:
    if value is None or value == "":
        return None
    return int(value)


def _optional_float(value: object) -> float | None:
    if value is None or value == "":
        return None
    return float(value)


def _observed_int(
    observed: dict[str, Any],
    *keys: str,
    default: int,
) -> int:
    for key in keys:
        if key in observed and observed[key] is not None:
            return max(0, int(observed[key]))
    return max(0, int(default))


def _operator_condition(
    type: str,
    status: bool,
    reason: str,
    message: str,
    timestamp: str,
) -> dict[str, str]:
    return {
        "type": type,
        "status": "True" if status else "False",
        "reason": reason,
        "message": message,
        "lastTransitionTime": timestamp,
    }
