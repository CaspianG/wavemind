from __future__ import annotations

import hashlib
import json
import math
import os
import re
import subprocess
import time
import urllib.parse
import urllib.request
from datetime import datetime
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any


MANAGED_SERVERLESS_SCHEMA = "wavemind.managed_serverless_telemetry.v1"
METRIC_TYPES = {
    "request_count": "run.googleapis.com/request_count",
    "request_latency": "run.googleapis.com/request_latency/e2e_latencies",
    "container_startup_latency": "run.googleapis.com/container/startup_latencies",
    "container_instance_count": "run.googleapis.com/container/instance_count",
}


class CloudRunEvidenceError(RuntimeError):
    pass


CommandRunner = Callable[[Sequence[str]], subprocess.CompletedProcess[str]]


def _default_command_runner(command: Sequence[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        list(command),
        text=True,
        encoding="utf-8",
        capture_output=True,
        timeout=120,
        check=False,
    )


def _source_ref() -> str | None:
    configured = str(os.environ.get("GITHUB_SHA") or "").strip()
    if re.fullmatch(r"[0-9a-fA-F]{40}", configured):
        return configured.lower()
    completed = _default_command_runner(["git", "rev-parse", "HEAD"])
    value = completed.stdout.strip() if completed.returncode == 0 else ""
    return value.lower() if re.fullmatch(r"[0-9a-fA-F]{40}", value) else None


def _provenance() -> dict[str, Any]:
    run_id = str(os.environ.get("GITHUB_RUN_ID") or "").strip() or None
    repository = str(os.environ.get("GITHUB_REPOSITORY") or "").strip()
    server_url = str(os.environ.get("GITHUB_SERVER_URL") or "").strip()
    return {
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "source_ref": _source_ref(),
        "execution_id": run_id or f"local-{int(time.time())}",
        "workflow_run_id": run_id,
        "workflow_run_url": (
            f"{server_url.rstrip('/')}/{repository}/actions/runs/{run_id}"
            if run_id and repository and server_url
            else None
        ),
        "evidence_source": "github-actions" if run_id else "local-provider-query",
    }


def _annotation(service: Mapping[str, Any], *names: str) -> str | None:
    candidates = [
        service.get("metadata", {}).get("annotations", {}),
        service.get("spec", {}).get("template", {}).get("metadata", {}).get("annotations", {}),
        service.get("template", {}).get("annotations", {}),
    ]
    for annotations in candidates:
        if not isinstance(annotations, Mapping):
            continue
        for name in names:
            value = annotations.get(name)
            if value is not None and str(value).strip():
                return str(value).strip()
    return None


def _nested(service: Mapping[str, Any], *paths: tuple[str, ...]) -> Any:
    for path in paths:
        value: Any = service
        for part in path:
            if not isinstance(value, Mapping) or part not in value:
                value = None
                break
            value = value[part]
        if value not in (None, ""):
            return value
    return None


def cloud_run_service_identity(
    service: Mapping[str, Any],
    *,
    project_id: str,
    region: str,
    service_name: str,
) -> dict[str, Any]:
    status = service.get("status") if isinstance(service.get("status"), Mapping) else {}
    ready = any(
        str(row.get("type")) == "Ready" and str(row.get("status")).lower() == "true"
        for row in status.get("conditions", [])
        if isinstance(row, Mapping)
    )
    revision = str(
        _nested(
            service,
            ("status", "latestReadyRevisionName"),
            ("latestReadyRevision",),
        )
        or ""
    )
    service_url = str(_nested(service, ("status", "url"), ("uri",)) or "")
    min_instances_raw = _nested(service, ("scaling", "minInstanceCount"))
    max_instances_raw = _nested(service, ("scaling", "maxInstanceCount"))
    if min_instances_raw is None:
        min_instances_raw = _annotation(
            service,
            "autoscaling.knative.dev/minScale",
            "run.googleapis.com/minScale",
        )
    if max_instances_raw is None:
        max_instances_raw = _annotation(
            service,
            "autoscaling.knative.dev/maxScale",
            "run.googleapis.com/maxScale",
        )
    try:
        min_instances = int(min_instances_raw)
        max_instances = int(max_instances_raw)
    except (TypeError, ValueError) as exc:
        raise CloudRunEvidenceError("Cloud Run min/max instance configuration is required") from exc
    if not ready:
        raise CloudRunEvidenceError("Cloud Run service Ready condition must be true")
    if not revision or not service_url.startswith("https://"):
        raise CloudRunEvidenceError("Cloud Run service URL and latest ready revision are required")
    if min_instances != 0:
        raise CloudRunEvidenceError("strict scale-from-zero evidence requires min instances = 0")
    if max_instances < 2:
        raise CloudRunEvidenceError("strict scale-out evidence requires max instances >= 2")
    return {
        "provider": "gcp-cloud-run",
        "service_id": f"projects/{project_id}/locations/{region}/services/{service_name}",
        "service_name": service_name,
        "deployment_revision": revision,
        "region": region,
        "service_url": service_url.rstrip("/"),
        "service_url_sha256": hashlib.sha256(service_url.rstrip("/").encode()).hexdigest(),
        "min_instances": min_instances,
        "configured_max_scale": max_instances,
        "provider_control_plane_observed": True,
    }


def _point_value(point: Mapping[str, Any]) -> float | None:
    value = point.get("value") if isinstance(point.get("value"), Mapping) else {}
    for key in ("int64Value", "doubleValue"):
        if key in value:
            try:
                return float(value[key])
            except (TypeError, ValueError):
                return None
    return None


def _distribution(point: Mapping[str, Any]) -> Mapping[str, Any] | None:
    value = point.get("value") if isinstance(point.get("value"), Mapping) else {}
    distribution = value.get("distributionValue")
    return distribution if isinstance(distribution, Mapping) else None


def _bucket_bounds(distribution: Mapping[str, Any]) -> list[float]:
    options = distribution.get("bucketOptions")
    if not isinstance(options, Mapping):
        return []
    explicit = options.get("explicitBuckets")
    if isinstance(explicit, Mapping):
        return [float(value) for value in explicit.get("bounds", [])]
    linear = options.get("linearBuckets")
    if isinstance(linear, Mapping):
        count = int(linear.get("numFiniteBuckets") or 0)
        offset = float(linear.get("offset") or 0.0)
        width = float(linear.get("width") or 0.0)
        return [offset + width * index for index in range(1, count + 1)]
    exponential = options.get("exponentialBuckets")
    if isinstance(exponential, Mapping):
        count = int(exponential.get("numFiniteBuckets") or 0)
        scale = float(exponential.get("scale") or 0.0)
        growth = float(exponential.get("growthFactor") or 0.0)
        return [scale * growth**index for index in range(count)]
    return []


def distribution_percentile(series: Sequence[Mapping[str, Any]], percentile: float) -> float:
    distributions = [
        distribution
        for row in series
        for point in row.get("points", [])
        if isinstance(point, Mapping)
        for distribution in [_distribution(point)]
        if distribution is not None
    ]
    if not distributions:
        raise CloudRunEvidenceError("provider distribution metric has no points")
    signatures = [tuple(_bucket_bounds(row)) for row in distributions]
    if not signatures[0] or any(signature != signatures[0] for signature in signatures):
        raise CloudRunEvidenceError("provider distribution bucket layouts must match")
    bounds = list(signatures[0])
    bucket_counts = [0] * (len(bounds) + 1)
    total = 0
    for distribution in distributions:
        counts = [int(value) for value in distribution.get("bucketCounts", [])]
        if len(counts) != len(bucket_counts):
            raise CloudRunEvidenceError("provider distribution bucket count is invalid")
        total += int(distribution.get("count") or sum(counts))
        bucket_counts = [left + right for left, right in zip(bucket_counts, counts)]
    if total <= 0:
        raise CloudRunEvidenceError("provider distribution metric is empty")
    target = max(1, math.ceil(total * float(percentile) / 100.0))
    cumulative = 0
    for index, count in enumerate(bucket_counts):
        cumulative += count
        if cumulative >= target:
            if index == 0:
                return float(bounds[0])
            if index > len(bounds) - 1:
                return float(bounds[-1])
            return float(bounds[index])
    return float(bounds[-1])


def _sum_metric(series: Sequence[Mapping[str, Any]]) -> int:
    return int(
        round(
            sum(
                value
                for row in series
                for point in row.get("points", [])
                if isinstance(point, Mapping)
                for value in [_point_value(point)]
                if value is not None
            )
        )
    )


def _peak_metric(series: Sequence[Mapping[str, Any]]) -> int:
    totals: dict[str, float] = {}
    for row in series:
        for point in row.get("points", []):
            if not isinstance(point, Mapping):
                continue
            value = _point_value(point)
            interval = point.get("interval") if isinstance(point.get("interval"), Mapping) else {}
            end_time = str(interval.get("endTime") or "")
            if value is not None and end_time:
                totals[end_time] = totals.get(end_time, 0.0) + value
    return int(math.ceil(max(totals.values()))) if totals else 0


def _provider_scale_out_seconds(series: Sequence[Mapping[str, Any]]) -> float:
    totals: dict[str, float] = {}
    for row in series:
        for point in row.get("points", []):
            if not isinstance(point, Mapping):
                continue
            value = _point_value(point)
            interval = point.get("interval") if isinstance(point.get("interval"), Mapping) else {}
            end_time = str(interval.get("endTime") or "")
            if value is not None and end_time:
                totals[end_time] = totals.get(end_time, 0.0) + value
    positive = sorted((timestamp, value) for timestamp, value in totals.items() if value > 0)
    if not positive:
        raise CloudRunEvidenceError("provider instance metric has no positive observations")
    peak_value = max(value for _, value in positive)
    first_timestamp = positive[0][0]
    peak_timestamp = next(timestamp for timestamp, value in positive if value == peak_value)

    def parse(value: str) -> datetime:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))

    try:
        elapsed = (parse(peak_timestamp) - parse(first_timestamp)).total_seconds()
    except ValueError as exc:
        raise CloudRunEvidenceError("provider instance metric timestamps are invalid") from exc
    return max(1.0, elapsed)


def _scale_to_zero_observed(series: Sequence[Mapping[str, Any]]) -> bool:
    totals: dict[str, float] = {}
    for row in series:
        for point in row.get("points", []):
            if not isinstance(point, Mapping):
                continue
            value = _point_value(point)
            interval = point.get("interval") if isinstance(point.get("interval"), Mapping) else {}
            end_time = str(interval.get("endTime") or "")
            if value is not None and end_time:
                totals[end_time] = totals.get(end_time, 0.0) + value
    ordered = sorted(totals.items())
    first_positive = next((index for index, (_, value) in enumerate(ordered) if value > 0), None)
    return first_positive is not None and any(value == 0 for _, value in ordered[:first_positive])


def build_cloud_run_managed_telemetry(
    *,
    service_identity: Mapping[str, Any],
    load_result: Mapping[str, Any],
    metrics: Mapping[str, Sequence[Mapping[str, Any]]],
    metric_window_start: str,
    metric_window_end: str,
) -> dict[str, Any]:
    missing = sorted(set(METRIC_TYPES) - set(metrics))
    if missing:
        raise CloudRunEvidenceError(f"missing provider metrics: {', '.join(missing)}")
    request_count = _sum_metric(metrics["request_count"])
    request_p99 = distribution_percentile(metrics["request_latency"], 99.0)
    startup_p99 = distribution_percentile(metrics["container_startup_latency"], 99.0)
    peak_instances = _peak_metric(metrics["container_instance_count"])
    scale_out_seconds = _provider_scale_out_seconds(metrics["container_instance_count"])
    scale_to_zero_observed = _scale_to_zero_observed(metrics["container_instance_count"])
    load_requests = int(load_result.get("requests") or 0)
    successes = int(load_result.get("successes") or 0)
    if load_requests < 1000 or successes < 1000:
        raise CloudRunEvidenceError("managed serverless evidence requires at least 1000 successful load requests")
    if request_count < successes:
        raise CloudRunEvidenceError("Cloud Monitoring request count is below client successes")
    if peak_instances < 2:
        raise CloudRunEvidenceError("Cloud Monitoring must observe at least two instances")
    if not scale_to_zero_observed:
        raise CloudRunEvidenceError("Cloud Monitoring must observe zero instances before scale-out")
    node_hashes = {
        str(value)
        for value in load_result.get("external_node_url_sha256", [])
        if str(value)
    }
    if str(service_identity.get("service_url_sha256") or "") not in node_hashes:
        raise CloudRunEvidenceError("client load result does not identify the attested Cloud Run URL")
    measured_rps = float(load_result.get("measured_pool_requests_per_second") or 0.0)
    client_p99 = float(load_result.get("p99_request_ms") or math.inf)
    target_rps = float(load_result.get("target_rps") or 0.0)
    target_p99 = float(load_result.get("target_p99_ms") or 500.0)
    max_error_rate = float(
        load_result["max_error_rate"]
        if "max_error_rate" in load_result
        else 0.01
    )
    error_rate = float(load_result["error_rate"] if "error_rate" in load_result else 1.0)
    p99 = max(client_p99, request_p99)
    cold_start_total = startup_p99 + p99
    max_scale = int(service_identity.get("configured_max_scale") or 0)
    cold_start_budget = float(load_result.get("cold_start_budget_ms") or 3500.0)
    max_scale_out_seconds = float(load_result.get("max_scale_out_seconds") or 60.0)
    observed_slo_pass = (
        measured_rps >= target_rps
        and p99 <= target_p99
        and cold_start_total <= cold_start_budget
        and scale_out_seconds <= max_scale_out_seconds
        and error_rate <= max_error_rate
        and peak_instances <= max_scale
    )
    return {
        "schema": MANAGED_SERVERLESS_SCHEMA,
        **_provenance(),
        "source": "gcp-cloud-run-monitoring",
        "node_mode": "external",
        **dict(service_identity),
        "capacity_method": "provider-observed",
        "horizontal_capacity_estimate": False,
        "cold_start_measured": True,
        "scale_out_measured": True,
        "scale_to_zero_observed": True,
        "provider_metric_types": list(METRIC_TYPES),
        "metric_window_start": metric_window_start,
        "metric_window_end": metric_window_end,
        "requests": load_requests,
        "successes": successes,
        "failures": int(load_result.get("failures") or 0),
        "requests_per_second": round(measured_rps, 3),
        "measured_pool_requests_per_second": round(measured_rps, 3),
        "p99_request_ms": round(p99, 3),
        "provider_request_p99_ms": round(request_p99, 3),
        "cold_start_ms": round(startup_p99, 3),
        "cold_start_total_ms": round(cold_start_total, 3),
        "scale_out_seconds": round(scale_out_seconds, 3),
        "error_rate": error_rate,
        "max_error_rate": max_error_rate,
        "target_rps": target_rps,
        "target_p99_ms": target_p99,
        "cold_start_budget_ms": cold_start_budget,
        "max_scale_out_seconds": max_scale_out_seconds,
        "measured_replicas": peak_instances,
        "max_replicas": peak_instances,
        "provider_request_count": request_count,
        "observed_slo_pass": observed_slo_pass,
        "claim_boundary": "Provider-observed managed Cloud Run evidence for this revision and metric window only.",
    }


def _monitoring_query_url(
    *,
    project_id: str,
    service_name: str,
    revision: str,
    metric_type: str,
    start: str,
    end: str,
) -> str:
    filter_value = (
        'resource.type="cloud_run_revision" '
        f'AND resource.labels.service_name="{service_name}" '
        f'AND resource.labels.revision_name="{revision}" '
        f'AND metric.type="{metric_type}"'
    )
    query = urllib.parse.urlencode(
        {
            "filter": filter_value,
            "interval.startTime": start,
            "interval.endTime": end,
            "view": "FULL",
            "pageSize": "1000",
        }
    )
    return f"https://monitoring.googleapis.com/v3/projects/{urllib.parse.quote(project_id)}/timeSeries?{query}"


def collect_cloud_run_managed_telemetry(
    *,
    project_id: str,
    region: str,
    service_name: str,
    load_result_path: str | Path,
    metric_window_start: str,
    metric_window_end: str,
    command_runner: CommandRunner = _default_command_runner,
) -> dict[str, Any]:
    describe = command_runner(
        [
            "gcloud",
            "run",
            "services",
            "describe",
            service_name,
            "--project",
            project_id,
            "--region",
            region,
            "--platform",
            "managed",
            "--format=json",
        ]
    )
    if describe.returncode != 0:
        raise CloudRunEvidenceError("gcloud could not describe the managed Cloud Run service")
    service = json.loads(describe.stdout)
    identity = cloud_run_service_identity(
        service,
        project_id=project_id,
        region=region,
        service_name=service_name,
    )
    token_result = command_runner(["gcloud", "auth", "print-access-token"])
    token = token_result.stdout.strip() if token_result.returncode == 0 else ""
    if not token:
        raise CloudRunEvidenceError("gcloud access token is required for Cloud Monitoring")
    metric_rows: dict[str, Sequence[Mapping[str, Any]]] = {}
    for key, metric_type in METRIC_TYPES.items():
        request = urllib.request.Request(
            _monitoring_query_url(
                project_id=project_id,
                service_name=service_name,
                revision=str(identity["deployment_revision"]),
                metric_type=metric_type,
                start=metric_window_start,
                end=metric_window_end,
            ),
            headers={"Authorization": f"Bearer {token}"},
        )
        with urllib.request.urlopen(request, timeout=60) as response:
            payload = json.loads(response.read().decode("utf-8"))
        rows = payload.get("timeSeries", [])
        if not isinstance(rows, list) or not rows:
            raise CloudRunEvidenceError(f"Cloud Monitoring returned no {key} data")
        metric_rows[key] = rows
    load_result = json.loads(Path(load_result_path).read_text(encoding="utf-8"))
    return build_cloud_run_managed_telemetry(
        service_identity=identity,
        load_result=load_result,
        metrics=metric_rows,
        metric_window_start=metric_window_start,
        metric_window_end=metric_window_end,
    )
