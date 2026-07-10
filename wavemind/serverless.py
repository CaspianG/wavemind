from __future__ import annotations

from dataclasses import asdict, dataclass, field
import math
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
class ServerlessWorkloadTarget:
    """Operational target for a stateless serverless WaveMind deployment."""

    requests_per_second: float = 3200.0
    avg_request_ms: float = 80.0
    p99_request_ms: float = 320.0
    cold_start_ms: float = 900.0
    target_p99_ms: float = 500.0
    cold_start_budget_ms: float = 1500.0
    active_fraction: float = 0.35
    replica_hourly_cost_usd: float = 0.08
    monthly_budget_usd: float = 750.0
    max_error_rate: float = 0.01
    max_scale_out_seconds: float = 60.0

    def __post_init__(self) -> None:
        if self.requests_per_second <= 0:
            raise ValueError("requests_per_second must be positive")
        if self.avg_request_ms <= 0:
            raise ValueError("avg_request_ms must be positive")
        if self.p99_request_ms <= 0:
            raise ValueError("p99_request_ms must be positive")
        if self.cold_start_ms < 0:
            raise ValueError("cold_start_ms cannot be negative")
        if self.target_p99_ms <= 0:
            raise ValueError("target_p99_ms must be positive")
        if self.cold_start_budget_ms <= 0:
            raise ValueError("cold_start_budget_ms must be positive")
        if not 0.0 <= self.active_fraction <= 1.0:
            raise ValueError("active_fraction must be between 0 and 1")
        if self.replica_hourly_cost_usd < 0:
            raise ValueError("replica_hourly_cost_usd cannot be negative")
        if self.monthly_budget_usd <= 0:
            raise ValueError("monthly_budget_usd must be positive")
        if not 0.0 <= self.max_error_rate <= 1.0:
            raise ValueError("max_error_rate must be between 0 and 1")
        if self.max_scale_out_seconds < 0:
            raise ValueError("max_scale_out_seconds cannot be negative")


@dataclass(frozen=True)
class ServerlessObservedTelemetry:
    """Observed load-test telemetry for the serverless operational profile."""

    requests_per_second: float
    avg_request_ms: float
    p95_request_ms: float
    p99_request_ms: float
    cold_start_ms: float
    error_rate: float = 0.0
    max_replicas: int = 1
    scale_out_seconds: float = 0.0
    monthly_compute_cost_usd: float | None = None
    source: str = "manual"

    def __post_init__(self) -> None:
        if self.requests_per_second <= 0:
            raise ValueError("observed requests_per_second must be positive")
        if self.avg_request_ms <= 0:
            raise ValueError("observed avg_request_ms must be positive")
        if self.p95_request_ms <= 0:
            raise ValueError("observed p95_request_ms must be positive")
        if self.p99_request_ms <= 0:
            raise ValueError("observed p99_request_ms must be positive")
        if self.p99_request_ms < self.p95_request_ms:
            raise ValueError("observed p99_request_ms must be >= p95_request_ms")
        if self.cold_start_ms < 0:
            raise ValueError("observed cold_start_ms cannot be negative")
        if not 0.0 <= self.error_rate <= 1.0:
            raise ValueError("observed error_rate must be between 0 and 1")
        if self.max_replicas <= 0:
            raise ValueError("observed max_replicas must be positive")
        if self.scale_out_seconds < 0:
            raise ValueError("observed scale_out_seconds cannot be negative")
        if self.monthly_compute_cost_usd is not None and self.monthly_compute_cost_usd < 0:
            raise ValueError("observed monthly_compute_cost_usd cannot be negative")
        if not self.source.strip():
            raise ValueError("observed source must not be empty")

    @classmethod
    def from_mapping(cls, payload: dict[str, Any]) -> "ServerlessObservedTelemetry":
        def pick(name: str, *aliases: str, default: Any = None) -> Any:
            for key in (name, *aliases):
                if key in payload:
                    return payload[key]
            if default is not None:
                return default
            raise ValueError(f"observed telemetry missing {name}")

        monthly_cost = payload.get(
            "monthly_compute_cost_usd",
            payload.get("monthly_cost_usd"),
        )
        return cls(
            requests_per_second=float(pick("requests_per_second", "rps", "observed_rps")),
            avg_request_ms=float(pick("avg_request_ms", "avg_ms", "observed_avg_request_ms")),
            p95_request_ms=float(pick("p95_request_ms", "p95_ms", "observed_p95_request_ms")),
            p99_request_ms=float(pick("p99_request_ms", "p99_ms", "observed_p99_request_ms")),
            cold_start_ms=float(pick("cold_start_ms", "cold_ms", "observed_cold_start_ms")),
            error_rate=float(pick("error_rate", "observed_error_rate", default=0.0)),
            max_replicas=int(pick("max_replicas", "observed_max_replicas", default=1)),
            scale_out_seconds=float(
                pick("scale_out_seconds", "observed_scale_out_seconds", default=0.0)
            ),
            monthly_compute_cost_usd=(
                None if monthly_cost is None else round(float(monthly_cost), 2)
            ),
            source=str(payload.get("source", "manual")),
        )

    def as_dict(self) -> dict[str, Any]:
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
    shared_store_refresh_seconds: float = 0.5
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
        if self.shared_store_refresh_seconds < 0:
            raise ValueError("shared_store_refresh_seconds cannot be negative")
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
            {
                "name": "WAVEMIND_SHARED_STORE_REFRESH_SECONDS",
                "value": str(float(self.shared_store_refresh_seconds)),
            },
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
            "command": ["wavemind"],
            "ports": [{"name": "http1", "containerPort": self.service_port}],
            "env": self.env(),
            "args": ["serve", "--host", "0.0.0.0", "--port", str(self.service_port)],
            "readinessProbe": {
                "httpGet": {"path": "/healthz", "port": self.service_port},
                "periodSeconds": 10,
                "timeoutSeconds": 2,
            },
            "livenessProbe": {
                "httpGet": {"path": "/healthz", "port": self.service_port},
                "initialDelaySeconds": 10,
                "periodSeconds": 20,
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
                # CPU metrics cannot activate a Deployment from zero because no
                # pod exists to report CPU. Knative owns the scale-to-zero path;
                # the KEDA CPU profile keeps one warm replica and scales out.
                "minReplicaCount": max(1, self.min_scale),
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
            "scale_to_zero_provider": "knative",
            "max_scale": self.max_scale,
            "target_concurrency": self.target_concurrency,
            "external_state_required": True,
            "store": self.store,
            "index": self.index,
            "uses_postgres": self.store.lower() == "postgres",
            "uses_external_qdrant": self.index.lower() == "qdrant" and self.qdrant_url is not None,
            "uses_shared_cache": self.redis_url is not None,
            "shared_store_refresh_seconds": self.shared_store_refresh_seconds,
            "bounded_worker_cache_staleness": self.shared_store_refresh_seconds > 0,
            "has_auth_secret": self.api_keys is not None,
            "safe_for_pod_eviction": self.store.lower() == "postgres",
            "keda_scale_target_kind": "Deployment",
            "keda_scale_target": self.keda_name,
            "keda_min_scale": max(1, self.min_scale),
            "keda_scale_to_zero": False,
            "valid_keda_scale_target": True,
        }

    def operational_profile(
        self,
        target: ServerlessWorkloadTarget | None = None,
        observed: ServerlessObservedTelemetry | None = None,
    ) -> dict[str, Any]:
        target = target or ServerlessWorkloadTarget()
        readiness = self.readiness_report()
        avg_request_seconds = target.avg_request_ms / 1000.0
        required_concurrency = target.requests_per_second * avg_request_seconds
        required_replicas = max(1, math.ceil(required_concurrency / self.target_concurrency))
        warm_replicas = max(self.min_scale, min(required_replicas, self.max_scale))
        burst_capacity_rps = (
            self.max_scale * self.target_concurrency / avg_request_seconds
            if avg_request_seconds > 0
            else 0.0
        )
        scale_out_possible = required_replicas <= self.max_scale
        external_state_ok = bool(
            readiness["uses_postgres"]
            and readiness["uses_external_qdrant"]
            and readiness["uses_shared_cache"]
            and readiness["has_auth_secret"]
            and readiness["safe_for_pod_eviction"]
        )
        warm_p99_ok = target.p99_request_ms <= target.target_p99_ms
        cold_start_total_ms = target.cold_start_ms + target.p99_request_ms
        cold_start_budget_ok = cold_start_total_ms <= target.cold_start_budget_ms
        scale_to_zero_safe = bool(readiness["scale_to_zero"] and external_state_ok)
        hours_per_month = 730.0
        active_compute_cost = (
            warm_replicas
            * target.replica_hourly_cost_usd
            * hours_per_month
            * target.active_fraction
        )
        idle_compute_cost = (
            self.min_scale
            * target.replica_hourly_cost_usd
            * hours_per_month
            * (1.0 - target.active_fraction)
        )
        monthly_compute_cost_usd = round(active_compute_cost + idle_compute_cost, 2)
        cost_ok = monthly_compute_cost_usd <= target.monthly_budget_usd
        deterministic_valid = bool(
            external_state_ok
            and scale_out_possible
            and warm_p99_ok
            and cold_start_budget_ok
            and cost_ok
        )
        observed_profile = (
            _serverless_observed_profile(
                target=target,
                observed=observed,
                max_scale=self.max_scale,
            )
            if observed is not None
            else {}
        )
        valid = bool(
            deterministic_valid
            and (
                not observed_profile
                or observed_profile["observed_slo_pass"]
            )
        )
        payload = {
            "mode": "serverless-operational",
            "valid": valid,
            "slo_pass": valid,
            "requests_per_second": target.requests_per_second,
            "avg_request_ms": target.avg_request_ms,
            "p99_request_ms": target.p99_request_ms,
            "target_p99_ms": target.target_p99_ms,
            "cold_start_ms": target.cold_start_ms,
            "cold_start_total_ms": cold_start_total_ms,
            "cold_start_budget_ms": target.cold_start_budget_ms,
            "cold_start_budget_ok": cold_start_budget_ok,
            "required_concurrency": required_concurrency,
            "required_replicas": required_replicas,
            "warm_replicas": warm_replicas,
            "max_scale": self.max_scale,
            "target_concurrency": self.target_concurrency,
            "burst_capacity_rps": burst_capacity_rps,
            "scale_out_possible": scale_out_possible,
            "scale_to_zero_safe": scale_to_zero_safe,
            "external_state_ok": external_state_ok,
            "uses_postgres": readiness["uses_postgres"],
            "uses_external_qdrant": readiness["uses_external_qdrant"],
            "uses_shared_cache": readiness["uses_shared_cache"],
            "has_auth_secret": readiness["has_auth_secret"],
            "safe_for_pod_eviction": readiness["safe_for_pod_eviction"],
            "active_fraction": target.active_fraction,
            "replica_hourly_cost_usd": target.replica_hourly_cost_usd,
            "monthly_compute_cost_usd": monthly_compute_cost_usd,
            "monthly_budget_usd": target.monthly_budget_usd,
            "max_error_rate": target.max_error_rate,
            "max_scale_out_seconds": target.max_scale_out_seconds,
            "cost_ok": cost_ok,
        }
        payload.update(observed_profile)
        return payload

    def _labels(self, *, component: str = "serverless-api") -> dict[str, str]:
        return {
            "app.kubernetes.io/name": "wavemind",
            "app.kubernetes.io/instance": self.name,
            "app.kubernetes.io/component": component,
            "app.kubernetes.io/managed-by": "wavemind-serverless",
        }


def serverless_sample_bundle(spec: WaveMindServerlessSpec | None = None) -> dict[str, Any]:
    return (spec or WaveMindServerlessSpec()).resource_list()


def _serverless_observed_profile(
    *,
    target: ServerlessWorkloadTarget,
    observed: ServerlessObservedTelemetry,
    max_scale: int,
) -> dict[str, Any]:
    cold_start_total_ms = observed.cold_start_ms + observed.p99_request_ms
    observed_traffic_ok = observed.requests_per_second >= target.requests_per_second * 0.95
    observed_p99_ok = observed.p99_request_ms <= target.target_p99_ms
    observed_cold_start_budget_ok = cold_start_total_ms <= target.cold_start_budget_ms
    observed_error_rate_ok = observed.error_rate <= target.max_error_rate
    observed_scale_out_ok = observed.scale_out_seconds <= target.max_scale_out_seconds
    observed_capacity_ok = observed.max_replicas <= max_scale
    observed_cost_ok = (
        observed.monthly_compute_cost_usd is None
        or observed.monthly_compute_cost_usd <= target.monthly_budget_usd
    )
    observed_slo_pass = bool(
        observed_traffic_ok
        and observed_p99_ok
        and observed_cold_start_budget_ok
        and observed_error_rate_ok
        and observed_scale_out_ok
        and observed_capacity_ok
        and observed_cost_ok
    )
    return {
        "observed_telemetry_present": True,
        "observed_telemetry_source": observed.source,
        "observed_requests_per_second": observed.requests_per_second,
        "observed_avg_request_ms": observed.avg_request_ms,
        "observed_p95_request_ms": observed.p95_request_ms,
        "observed_p99_request_ms": observed.p99_request_ms,
        "observed_cold_start_ms": observed.cold_start_ms,
        "observed_cold_start_total_ms": cold_start_total_ms,
        "observed_error_rate": observed.error_rate,
        "observed_max_replicas": observed.max_replicas,
        "observed_scale_out_seconds": observed.scale_out_seconds,
        "observed_monthly_compute_cost_usd": observed.monthly_compute_cost_usd,
        "observed_traffic_ok": observed_traffic_ok,
        "observed_p99_ok": observed_p99_ok,
        "observed_cold_start_budget_ok": observed_cold_start_budget_ok,
        "observed_error_rate_ok": observed_error_rate_ok,
        "observed_scale_out_ok": observed_scale_out_ok,
        "observed_capacity_ok": observed_capacity_ok,
        "observed_cost_ok": observed_cost_ok,
        "observed_slo_pass": observed_slo_pass,
    }


def _secret_key_ref(ref: SecretEnvRef) -> dict[str, Any]:
    return {
        "secretKeyRef": {
            "name": ref.name,
            "key": ref.key,
        }
    }
