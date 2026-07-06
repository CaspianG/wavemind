from __future__ import annotations

import json
import ssl
import time
from dataclasses import dataclass, field
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
            required_replicas = self._capacity_required_replicas(
                seed_replicas=max(
                    self.replicas,
                    self.replication_factor,
                    self.autoscaling_min_replicas,
                )
            )
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
        control_plane = dict(spec.get("controlPlane") or {})
        consensus = dict(control_plane.get("consensus") or {})
        autoscaling = dict(spec.get("autoscaling") or {})
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
                }
            )
            if self.autoscaling_target_memory_utilization is not None:
                autoscaling["targetMemoryUtilizationPercentage"] = (
                    self.autoscaling_target_memory_utilization
                )
            spec["autoscaling"] = autoscaling
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

    def reconciled_resources(self) -> list[dict[str, Any]]:
        resources = [
            self._service(headless=False),
            self._service(headless=True),
            self._statefulset(),
        ]
        if self.autoscaling_enabled:
            resources.append(self._horizontal_pod_autoscaler())
        if self.repair_enabled and self.namespace_count:
            resources.append(self._repair_cronjob())
        return resources

    def capacity_autoscale_plan(self):
        if self.autoscaling_target_memories is None:
            return None
        return build_cluster_autoscale_plan(
            namespaces=self.namespaces,
            nodes=self.nodes,
            replication_factor=self.replication_factor,
            target_memories=self.autoscaling_target_memories,
            max_memories_per_node=self.autoscaling_max_memories_per_node,
            headroom=self.autoscaling_headroom,
            node_prefix=self.name,
            address_template=(
                f"http://{{node_id}}.{self.headless_service_name}."
                f"{self.namespace}.svc.cluster.local:{self.service_port}"
            ),
            max_moves=25,
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
                    "spec": {"containers": [container]},
                },
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
                                        "controlPlane": {
                                            "type": "object",
                                            "properties": {
                                                "consensus": {
                                                    "type": "object",
                                                    "properties": {
                                                        "enabled": {"type": "boolean"},
                                                        "leaseTtlSeconds": {
                                                            "type": "number",
                                                            "exclusiveMinimum": 0,
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
                                                    "exclusiveMinimum": 0,
                                                    "maximum": 1,
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
) -> dict[str, Any]:
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
            "replicas": 1,
            "selector": {"matchLabels": {"app.kubernetes.io/name": "wavemind-operator"}},
            "template": {
                "metadata": {"labels": {"app.kubernetes.io/name": "wavemind-operator"}},
                "spec": {
                    "serviceAccountName": "wavemind-operator",
                    "containers": [
                        {
                            "name": "operator",
                            "image": operator_image,
                            "imagePullPolicy": "IfNotPresent",
                            "args": ["operator-loop", "--namespace", namespace],
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
    payload = spec.as_resource_list()
    payload["operatorStatus"] = operator_status(resource)
    return payload


def operator_status(
    resource: dict[str, Any],
    *,
    observed: dict[str, Any] | None = None,
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
    control_plane = spec.control_plane_consensus_report()
    control_plane_ready = bool(control_plane.get("ready"))
    ready = (
        resources_ready
        and capacity_ready
        and autoscaling_ready
        and repair_ready
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
    if degraded_nodes or unavailable_nodes:
        actions.append("Run cluster-health and cluster-repair before declaring the cluster ready.")
    if not repair_ready:
        actions.append("Enable scheduled cluster repair for replicated namespace deployments.")
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
        "controlPlane": control_plane,
        "conditions": conditions,
        "actions": actions,
        "lastTransitionTime": timestamp,
    }


@dataclass(frozen=True)
class KubernetesResourcePath:
    api_path: str
    collection_path: str


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
) -> dict[str, Any]:
    last_report: dict[str, Any] = {}
    while True:
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
            statuses.append(
                {
                    "name": str((cluster.get("metadata") or {}).get("name") or "wavemind"),
                    "namespace": str((cluster.get("metadata") or {}).get("namespace") or namespace),
                    "ready": bool(status.get("ready")),
                    "phase": status.get("phase"),
                    "requiredReplicas": dict(status.get("capacity") or {}).get("requiredReplicas"),
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
    elif kind == "StatefulSet":
        collection = f"/apis/apps/v1/namespaces/{namespace}/statefulsets"
    elif kind == "CronJob":
        collection = f"/apis/batch/v1/namespaces/{namespace}/cronjobs"
    elif kind == "HorizontalPodAutoscaler":
        collection = f"/apis/autoscaling/v2/namespaces/{namespace}/horizontalpodautoscalers"
    else:
        raise ValueError(f"Unsupported reconciled resource kind: {kind}")
    return KubernetesResourcePath(
        api_path=f"{collection}/{name}",
        collection_path=collection,
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
