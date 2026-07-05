from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(frozen=True)
class SecretEnvRef:
    name: str
    key: str

    def __post_init__(self) -> None:
        if not self.name.strip():
            raise ValueError("secret name must not be empty")
        if not self.key.strip():
            raise ValueError("secret key must not be empty")

    def as_dict(self) -> dict[str, str]:
        return asdict(self)


@dataclass(frozen=True)
class WaveMindServerlessSpec:
    """Knative/KEDA deployment plan for stateless WaveMind API workers.

    This intentionally requires external state. Serverless workers can scale to
    zero and move between nodes, so pod-local SQLite is not a safe source of
    truth for production memory.
    """

    name: str = "wavemind"
    namespace: str = "default"
    image: str = "ghcr.io/caspiang/wavemind:latest"
    service_port: int = 8000
    min_scale: int = 0
    max_scale: int = 24
    target_concurrency: int = 50
    scale_down_delay_seconds: int = 300
    store: str = "postgres"
    index: str = "qdrant"
    encoder: str = "hash"
    score_threshold: float = 0.0
    audit_queries: bool = True
    postgres_dsn: SecretEnvRef = field(
        default_factory=lambda: SecretEnvRef("wavemind-postgres", "dsn")
    )
    qdrant_url: SecretEnvRef | None = field(
        default_factory=lambda: SecretEnvRef("wavemind-qdrant", "url")
    )
    qdrant_api_key: SecretEnvRef | None = None
    redis_url: SecretEnvRef | None = field(
        default_factory=lambda: SecretEnvRef("wavemind-redis", "url")
    )
    api_keys: SecretEnvRef | None = field(
        default_factory=lambda: SecretEnvRef("wavemind-auth", "api-keys")
    )
    resources: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.name.strip():
            raise ValueError("name must not be empty")
        if not self.namespace.strip():
            raise ValueError("namespace must not be empty")
        if not self.image.strip():
            raise ValueError("image must not be empty")
        if self.service_port <= 0:
            raise ValueError("service_port must be positive")
        if self.min_scale < 0:
            raise ValueError("min_scale cannot be negative")
        if self.max_scale < max(1, self.min_scale):
            raise ValueError("max_scale must be >= max(1, min_scale)")
        if self.target_concurrency <= 0:
            raise ValueError("target_concurrency must be positive")
        if self.scale_down_delay_seconds < 0:
            raise ValueError("scale_down_delay_seconds cannot be negative")
        if self.store.lower() != "postgres":
            raise ValueError("serverless mode requires store='postgres'")
        if self.index.lower() == "qdrant" and self.qdrant_url is None:
            raise ValueError("serverless qdrant index requires qdrant_url")

    def env(self) -> list[dict[str, Any]]:
        env: list[dict[str, Any]] = [
            {"name": "WAVEMIND_STORE", "value": "postgres"},
            {"name": "WAVEMIND_INDEX", "value": self.index},
            {"name": "WAVEMIND_ENCODER", "value": self.encoder},
            {"name": "WAVEMIND_SCORE_THRESHOLD", "value": str(float(self.score_threshold))},
            {"name": "WAVEMIND_AUDIT_QUERIES", "value": "1" if self.audit_queries else "0"},
            {"name": "WAVEMIND_POSTGRES_DSN", "valueFrom": _secret_key_ref(self.postgres_dsn)},
        ]
        if self.qdrant_url is not None:
            env.append({"name": "WAVEMIND_QDRANT_URL", "valueFrom": _secret_key_ref(self.qdrant_url)})
        if self.qdrant_api_key is not None:
            env.append(
                {
                    "name": "WAVEMIND_QDRANT_API_KEY",
                    "valueFrom": _secret_key_ref(self.qdrant_api_key),
                }
            )
        if self.redis_url is not None:
            env.append({"name": "WAVEMIND_REDIS_URL", "valueFrom": _secret_key_ref(self.redis_url)})
        if self.api_keys is not None:
            env.append({"name": "WAVEMIND_API_KEYS", "valueFrom": _secret_key_ref(self.api_keys)})
        return env

    @property
    def keda_name(self) -> str:
        return f"{self.name}-keda"

    def container(self) -> dict[str, Any]:
        container: dict[str, Any] = {
            "name": "api",
            "image": self.image,
            "ports": [{"name": "http1", "containerPort": self.service_port}],
            "env": self.env(),
            "args": ["serve", "--host", "0.0.0.0", "--port", str(self.service_port)],
            "readinessProbe": {
                "httpGet": {"path": "/stats", "port": self.service_port},
                "periodSeconds": 10,
                "timeoutSeconds": 2,
            },
        }
        if self.resources:
            container["resources"] = dict(self.resources)
        return container

    def knative_service(self) -> dict[str, Any]:
        labels = self._labels()
        return {
            "apiVersion": "serving.knative.dev/v1",
            "kind": "Service",
            "metadata": {
                "name": self.name,
                "namespace": self.namespace,
                "labels": labels,
            },
            "spec": {
                "template": {
                    "metadata": {
                        "labels": labels,
                        "annotations": {
                            "autoscaling.knative.dev/class": "kpa.autoscaling.knative.dev",
                            "autoscaling.knative.dev/metric": "concurrency",
                            "autoscaling.knative.dev/target": str(self.target_concurrency),
                            "autoscaling.knative.dev/min-scale": str(self.min_scale),
                            "autoscaling.knative.dev/max-scale": str(self.max_scale),
                            "autoscaling.knative.dev/scale-down-delay": (
                                f"{self.scale_down_delay_seconds}s"
                            ),
                        },
                    },
                    "spec": {
                        "containers": [self.container()],
                    },
                }
            },
        }

    def keda_deployment(self) -> dict[str, Any]:
        labels = self._labels(component="serverless-api-keda")
        return {
            "apiVersion": "apps/v1",
            "kind": "Deployment",
            "metadata": {
                "name": self.keda_name,
                "namespace": self.namespace,
                "labels": labels,
            },
            "spec": {
                "replicas": max(1, self.min_scale),
                "selector": {"matchLabels": labels},
                "template": {
                    "metadata": {"labels": labels},
                    "spec": {
                        "containers": [self.container()],
                    },
                },
            },
        }

    def keda_service(self) -> dict[str, Any]:
        labels = self._labels(component="serverless-api-keda")
        return {
            "apiVersion": "v1",
            "kind": "Service",
            "metadata": {
                "name": self.keda_name,
                "namespace": self.namespace,
                "labels": labels,
            },
            "spec": {
                "type": "ClusterIP",
                "selector": labels,
                "ports": [
                    {
                        "name": "http",
                        "port": self.service_port,
                        "targetPort": self.service_port,
                    }
                ],
            },
        }

    def keda_scaled_object(self) -> dict[str, Any]:
        return {
            "apiVersion": "keda.sh/v1alpha1",
            "kind": "ScaledObject",
            "metadata": {
                "name": f"{self.keda_name}-scale",
                "namespace": self.namespace,
                "labels": self._labels(component="serverless-api-keda"),
            },
            "spec": {
                "scaleTargetRef": {
                    "apiVersion": "apps/v1",
                    "kind": "Deployment",
                    "name": self.keda_name,
                },
                "minReplicaCount": self.min_scale,
                "maxReplicaCount": self.max_scale,
                "pollingInterval": 10,
                "cooldownPeriod": self.scale_down_delay_seconds,
                "triggers": [
                    {
                        "type": "cpu",
                        "metricType": "Utilization",
                        "metadata": {"value": "70"},
                    }
                ],
            },
        }

    def resource_list(self, *, include_keda: bool = True) -> dict[str, Any]:
        items = [self.knative_service()]
        if include_keda:
            items.extend([self.keda_deployment(), self.keda_service(), self.keda_scaled_object()])
        return {"apiVersion": "v1", "kind": "List", "items": items}

    def readiness_report(self) -> dict[str, Any]:
        return {
            "mode": "serverless",
            "stateless_workers": True,
            "scale_to_zero": self.min_scale == 0,
            "max_scale": self.max_scale,
            "target_concurrency": self.target_concurrency,
            "external_state_required": True,
            "store": self.store,
            "index": self.index,
            "uses_postgres": self.store.lower() == "postgres",
            "uses_external_qdrant": self.index.lower() == "qdrant" and self.qdrant_url is not None,
            "uses_shared_cache": self.redis_url is not None,
            "has_auth_secret": self.api_keys is not None,
            "safe_for_pod_eviction": self.store.lower() == "postgres",
            "keda_scale_target_kind": "Deployment",
            "keda_scale_target": self.keda_name,
            "valid_keda_scale_target": True,
        }

    def _labels(self, *, component: str = "serverless-api") -> dict[str, str]:
        return {
            "app.kubernetes.io/name": "wavemind",
            "app.kubernetes.io/instance": self.name,
            "app.kubernetes.io/component": component,
            "app.kubernetes.io/managed-by": "wavemind-serverless",
        }


def serverless_sample_bundle(spec: WaveMindServerlessSpec | None = None) -> dict[str, Any]:
    return (spec or WaveMindServerlessSpec()).resource_list()


def _secret_key_ref(ref: SecretEnvRef) -> dict[str, Any]:
    return {
        "secretKeyRef": {
            "name": ref.name,
            "key": ref.key,
        }
    }
