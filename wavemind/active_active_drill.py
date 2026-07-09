from __future__ import annotations

import hashlib
import time
from datetime import datetime, timezone
from typing import Any, Literal

from .jobs import ActiveActiveSyncJobReport, HTTPActiveActiveSyncWorker
from .sharding import HTTPNamespaceShardClient


ActiveActiveDrillMode = Literal["seed", "outage", "recover"]


def parse_active_active_regions(specs: list[str]) -> dict[str, str]:
    regions: dict[str, str] = {}
    for value in specs:
        region_id, separator, address = value.partition("=")
        if not separator or not region_id.strip() or not address.strip():
            raise ValueError("regions must use region_id=url")
        region_id = region_id.strip()
        address = address.strip().rstrip("/")
        if not address.startswith(("http://", "https://")):
            raise ValueError("region addresses must start with http:// or https://")
        if region_id in regions:
            raise ValueError(f"duplicate region id: {region_id}")
        regions[region_id] = address
    if len(regions) < 3:
        raise ValueError("active-active drill requires at least three regions")
    return regions


def run_active_active_drill(
    regions: dict[str, str],
    *,
    client: HTTPNamespaceShardClient | Any,
    mode: ActiveActiveDrillMode,
    namespace_prefix: str = "active-active-drill",
    namespace_count: int = 16,
    failed_region: str | None = None,
    min_convergence_rate: float = 1.0,
) -> dict[str, Any]:
    if mode not in {"seed", "outage", "recover"}:
        raise ValueError("mode must be seed, outage, or recover")
    if len(regions) < 3:
        raise ValueError("active-active drill requires at least three regions")
    if namespace_count <= 0:
        raise ValueError("namespace_count must be positive")
    if not 0.0 <= min_convergence_rate <= 1.0:
        raise ValueError("min_convergence_rate must be between 0 and 1")
    if mode in {"outage", "recover"} and failed_region not in regions:
        raise ValueError("outage and recover modes require --failed-region")

    started = time.perf_counter()
    region_ids = tuple(sorted(regions))
    namespaces = tuple(
        f"{namespace_prefix}:{index:04d}" for index in range(namespace_count)
    )
    health = _probe_regions(regions, client)
    unavailable = tuple(
        region_id
        for region_id in region_ids
        if health[region_id]["status"] != "healthy"
    )
    payload: dict[str, Any] = {
        "schema": "wavemind.active_active_drill.v1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "mode": mode,
        "namespace_prefix": namespace_prefix,
        "namespace_count": namespace_count,
        "regions": [
            {"id": region_id, "address": regions[region_id]}
            for region_id in region_ids
        ],
        "failed_region": failed_region,
        "region_health": health,
        "unavailable_regions": list(unavailable),
        "min_convergence_rate": min_convergence_rate,
        "workload_digest": _workload_digest(
            region_ids,
            namespace_prefix,
            namespace_count,
            failed_region=failed_region,
        ),
    }

    try:
        if mode == "seed":
            if unavailable:
                raise RuntimeError(f"seed requires every region healthy: {unavailable}")
            writes = _write_seed(regions, namespaces, client)
            report = HTTPActiveActiveSyncWorker(regions, client=client).run_once(
                namespaces=namespaces,
                fail_fast=False,
            )
            verification = _verify_state(
                regions,
                namespaces,
                client,
                all_region_ids=region_ids,
                failed_region=None,
                include_outage_writes=False,
                expect_delete=False,
            )
            sync = _sync_summary(report)
            payload.update(
                {
                    "writes": writes,
                    "sync": sync,
                    "verification": verification,
                    "status": (
                        "pass"
                        if sync["failed_pairs"] == 0
                        and verification["convergence_rate"] >= min_convergence_rate
                        else "fail"
                    ),
                }
            )
        elif mode == "outage":
            if failed_region not in unavailable:
                raise RuntimeError(
                    f"expected failed region {failed_region!r} was not physically unavailable"
                )
            survivors = {
                region_id: address
                for region_id, address in regions.items()
                if region_id not in unavailable
            }
            if len(survivors) < 2:
                raise RuntimeError("outage drill requires at least two surviving regions")
            writes = _write_outage(survivors, namespaces, client)
            deleted_text = _deleted_text(tuple(sorted(survivors)), namespaces[0])
            deleted = client.forget(
                survivors[tuple(sorted(survivors))[0]],
                namespace=namespaces[0],
                text=deleted_text,
            )
            report = HTTPActiveActiveSyncWorker(survivors, client=client).run_once(
                namespaces=namespaces,
                fail_fast=False,
            )
            verification = _verify_state(
                survivors,
                namespaces,
                client,
                all_region_ids=region_ids,
                failed_region=failed_region,
                include_outage_writes=True,
                expect_delete=True,
            )
            sync = _sync_summary(report)
            payload.update(
                {
                    "surviving_regions": sorted(survivors),
                    "writes": writes,
                    "deleted_records_requested": int(deleted),
                    "deleted_text": deleted_text,
                    "sync": sync,
                    "verification": verification,
                    "status": (
                        "pass"
                        if sync["failed_pairs"] == 0
                        and int(deleted) >= 1
                        and verification["convergence_rate"] >= min_convergence_rate
                        and verification["delete_suppression_rate"] >= 1.0
                        else "fail"
                    ),
                }
            )
        else:
            if unavailable:
                raise RuntimeError(f"recover requires every region healthy: {unavailable}")
            worker = HTTPActiveActiveSyncWorker(regions, client=client)
            reports: list[ActiveActiveSyncJobReport] = []
            for _ in range(4):
                report = worker.run_once(namespaces=namespaces, fail_fast=False)
                reports.append(report)
                if report.records_imported == 0 and report.tombstones_imported == 0:
                    break
            final_report = reports[-1]
            verification = _verify_state(
                regions,
                namespaces,
                client,
                all_region_ids=region_ids,
                failed_region=failed_region,
                include_outage_writes=True,
                expect_delete=True,
            )
            payload.update(
                {
                    "sync_cycles": len(reports),
                    "sync": {
                        "failed_pairs": sum(report.failed_pairs for report in reports),
                        "records_imported": sum(report.records_imported for report in reports),
                        "tombstones_imported": sum(
                            report.tombstones_imported for report in reports
                        ),
                        "final_noop_records_imported": final_report.records_imported,
                        "final_noop_tombstones_imported": final_report.tombstones_imported,
                        "final_noop_failed_pairs": final_report.failed_pairs,
                        "duration_ms": sum(report.duration_ms for report in reports),
                    },
                    "verification": verification,
                    "status": (
                        "pass"
                        if sum(report.failed_pairs for report in reports) == 0
                        and final_report.records_imported == 0
                        and final_report.tombstones_imported == 0
                        and verification["convergence_rate"] >= min_convergence_rate
                        and verification["delete_suppression_rate"] >= 1.0
                        else "fail"
                    ),
                }
            )
    except Exception as exc:
        payload.update(
            {
                "status": "fail",
                "error": f"{type(exc).__name__}: {exc}",
            }
        )

    payload["elapsed_ms"] = round((time.perf_counter() - started) * 1000.0, 3)
    return payload


def _probe_regions(
    regions: dict[str, str],
    client: HTTPNamespaceShardClient | Any,
) -> dict[str, dict[str, Any]]:
    health: dict[str, dict[str, Any]] = {}
    for region_id in sorted(regions):
        started = time.perf_counter()
        try:
            client.stats(regions[region_id])
            status = "healthy"
            error = None
        except Exception as exc:
            status = "unavailable"
            error = str(exc)
        health[region_id] = {
            "status": status,
            "error": error,
            "latency_ms": round((time.perf_counter() - started) * 1000.0, 3),
        }
    return health


def _write_seed(
    regions: dict[str, str],
    namespaces: tuple[str, ...],
    client: HTTPNamespaceShardClient | Any,
) -> int:
    writes = 0
    for region_id in sorted(regions):
        for namespace in namespaces:
            client.remember(
                regions[region_id],
                text=_initial_text(region_id, namespace),
                namespace=namespace,
                tags=("active-active-drill", "seed"),
            )
            writes += 1
    return writes


def _write_outage(
    survivors: dict[str, str],
    namespaces: tuple[str, ...],
    client: HTTPNamespaceShardClient | Any,
) -> int:
    writes = 0
    for region_id in sorted(survivors):
        for namespace in namespaces:
            client.remember(
                survivors[region_id],
                text=_outage_text(region_id, namespace),
                namespace=namespace,
                tags=("active-active-drill", "outage"),
            )
            writes += 1
    return writes


def _verify_state(
    target_regions: dict[str, str],
    namespaces: tuple[str, ...],
    client: HTTPNamespaceShardClient | Any,
    *,
    all_region_ids: tuple[str, ...],
    failed_region: str | None,
    include_outage_writes: bool,
    expect_delete: bool,
) -> dict[str, Any]:
    survivor_ids = tuple(
        region_id for region_id in all_region_ids if region_id != failed_region
    )
    deleted_text = _deleted_text(survivor_ids, namespaces[0]) if expect_delete else None
    expected_checks = 0
    hits = 0
    delete_checks: list[bool] = []
    for target_address in target_regions.values():
        for namespace in namespaces:
            expected_texts = [
                _initial_text(region_id, namespace) for region_id in all_region_ids
            ]
            if include_outage_writes:
                expected_texts.extend(
                    _outage_text(region_id, namespace) for region_id in survivor_ids
                )
            for text in expected_texts:
                if deleted_text is not None and text == deleted_text:
                    continue
                expected_checks += 1
                results = client.query(
                    target_address,
                    text=text,
                    namespace=namespace,
                    top_k=10,
                    min_score=0.0,
                )
                if any(result.text == text for result in results):
                    hits += 1
        if deleted_text is not None:
            results = client.query(
                target_address,
                text=deleted_text,
                namespace=namespaces[0],
                top_k=10,
                min_score=0.0,
            )
            delete_checks.append(all(result.text != deleted_text for result in results))
    return {
        "expected_checks": expected_checks,
        "hits": hits,
        "convergence_rate": hits / expected_checks if expected_checks else 0.0,
        "delete_checks": len(delete_checks),
        "delete_suppression_rate": (
            sum(1 for value in delete_checks if value) / len(delete_checks)
            if delete_checks
            else 1.0
        ),
    }


def _sync_summary(report: ActiveActiveSyncJobReport) -> dict[str, Any]:
    return {
        "region_count": len(report.regions),
        "namespace_count": len(report.namespaces),
        "pair_count": len(report.pair_reports),
        "failed_pairs": report.failed_pairs,
        "records_imported": report.records_imported,
        "tombstones_imported": report.tombstones_imported,
        "duration_ms": report.duration_ms,
    }


def _initial_text(region_id: str, namespace: str) -> str:
    token = hashlib.sha256(f"initial:{region_id}:{namespace}".encode("utf-8")).hexdigest()[:16]
    return f"WaveMind active-active initial memory from {region_id} in {namespace}; token {token}"


def _outage_text(region_id: str, namespace: str) -> str:
    token = hashlib.sha256(f"outage:{region_id}:{namespace}".encode("utf-8")).hexdigest()[:16]
    return f"WaveMind active-active outage memory from {region_id} in {namespace}; token {token}"


def _deleted_text(survivor_ids: tuple[str, ...], namespace: str) -> str:
    if not survivor_ids:
        raise ValueError("at least one survivor is required")
    return _initial_text(sorted(survivor_ids)[0], namespace)


def _workload_digest(
    region_ids: tuple[str, ...],
    namespace_prefix: str,
    namespace_count: int,
    *,
    failed_region: str | None,
) -> str:
    value = "|".join(
        (
            ",".join(region_ids),
            namespace_prefix,
            str(namespace_count),
            failed_region or "",
        )
    )
    return hashlib.sha256(value.encode("utf-8")).hexdigest()
