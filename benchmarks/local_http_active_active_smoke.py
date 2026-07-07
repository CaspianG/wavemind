from __future__ import annotations

import argparse
import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import ProxyHandler, Request, build_opener

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) in sys.path:
    sys.path.remove(str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT))

from wavemind import HTTPActiveActiveSyncWorker, HTTPNamespaceShardClient


@dataclass(frozen=True)
class LocalReplicatedRegion:
    id: str
    address: str
    root_path: Path
    process: subprocess.Popen[str]


def free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def wait_until_ready(region: LocalReplicatedRegion, *, timeout_seconds: float = 25.0) -> None:
    opener = build_opener(ProxyHandler({}))
    deadline = time.time() + timeout_seconds
    last_error: object = None
    while time.time() < deadline:
        if region.process.poll() is not None:
            stdout, stderr = region.process.communicate(timeout=1)
            raise RuntimeError(
                f"{region.id} exited before readiness with {region.process.returncode}\n"
                f"STDOUT:\n{stdout}\nSTDERR:\n{stderr}"
            )
        try:
            request = Request(f"{region.address}/stats", method="GET")
            with opener.open(request, timeout=1) as response:
                if response.status == 200:
                    return
        except (HTTPError, URLError, TimeoutError) as exc:
            last_error = exc
        time.sleep(0.2)
    raise RuntimeError(f"{region.id} did not become ready: {last_error}")


def start_replicated_region(
    root: Path,
    region_id: str,
    *,
    host: str = "127.0.0.1",
    port: int | None = None,
    replicas_per_region: int = 3,
    readiness_timeout_seconds: float = 25.0,
    capture_output: bool = True,
) -> LocalReplicatedRegion:
    port = free_port() if port is None else int(port)
    region_root = root / region_id
    command = [
        sys.executable,
        "-m",
        "wavemind",
        "--score-threshold",
        "0.05",
        "--width",
        "16",
        "--height",
        "16",
        "--layers",
        "1",
        "serve",
        "--host",
        host,
        "--port",
        str(port),
        "--replicated-root",
        str(region_root),
        "--replication-factor",
        str(replicas_per_region),
        "--read-quorum",
        "1",
    ]
    for index in range(replicas_per_region):
        command.extend(["--replica-node", f"{region_id}-replica-{index}"])
    env = dict(os.environ)
    env.setdefault("WAVEMIND_API_SERIALIZE_OPERATIONS", "1")
    env["PYTHONPATH"] = str(PROJECT_ROOT) + os.pathsep + env.get("PYTHONPATH", "")
    process = subprocess.Popen(
        command,
        cwd=PROJECT_ROOT,
        env=env,
        stdout=subprocess.PIPE if capture_output else subprocess.DEVNULL,
        stderr=subprocess.PIPE if capture_output else subprocess.DEVNULL,
        text=True,
        encoding="utf-8",
    )
    region = LocalReplicatedRegion(
        id=region_id,
        address=f"http://{host}:{port}",
        root_path=region_root,
        process=process,
    )
    wait_until_ready(region, timeout_seconds=readiness_timeout_seconds)
    return region


def stop_regions(regions: list[LocalReplicatedRegion]) -> None:
    for region in regions:
        if region.process.poll() is None:
            region.process.terminate()
    for region in regions:
        if region.process.poll() is not None:
            continue
        try:
            region.process.communicate(timeout=5)
        except subprocess.TimeoutExpired:
            region.process.kill()
            region.process.communicate(timeout=5)


def parse_region_specs(specs: list[str]) -> dict[str, str]:
    regions: dict[str, str] = {}
    for index, spec in enumerate(specs):
        if "=" in spec:
            region_id, address = spec.split("=", 1)
        else:
            region_id, address = f"region-{index:03d}", spec
        region_id = region_id.strip()
        address = address.strip().rstrip("/")
        if not region_id or not address:
            raise ValueError(f"--region must use id=url or url format, got {spec!r}")
        if not address.startswith(("http://", "https://")):
            raise ValueError(f"region address must start with http:// or https://, got {address!r}")
        if region_id in regions:
            raise ValueError(f"duplicate region id: {region_id}")
        regions[region_id] = address
    if len(regions) < 2:
        raise ValueError("at least two regions are required")
    return regions


def run_active_active_service_workload(
    regions: dict[str, str],
    *,
    client: HTTPNamespaceShardClient,
    namespace_prefix: str,
    namespace_count: int,
    limit: int | None = None,
) -> dict[str, object]:
    namespaces = tuple(f"{namespace_prefix}:{index}" for index in range(namespace_count))
    expected: dict[str, set[str]] = {namespace: set() for namespace in namespaces}
    worker = HTTPActiveActiveSyncWorker(regions, client=client)
    reports = []
    sync_latencies: list[float] = []
    operation_latencies: list[float] = []

    write_count = 0
    for region_id, address in regions.items():
        for namespace_index, namespace in enumerate(namespaces):
            text = f"{region_id} active active service namespace {namespace_index} memory"
            started = time.perf_counter()
            client.remember(address, text=text, namespace=namespace)
            operation_latencies.append((time.perf_counter() - started) * 1000.0)
            expected[namespace].add(text)
            write_count += 1

    first_report = worker.run_once(namespaces=namespaces, limit=limit)
    reports.append(first_report)
    sync_latencies.append(first_report.duration_ms)

    total_expected = 0
    total_hits = 0
    for namespace, texts in expected.items():
        for text in texts:
            total_expected += len(regions)
            for address in regions.values():
                started = time.perf_counter()
                results = client.query(address, text=text, namespace=namespace, top_k=3)
                operation_latencies.append((time.perf_counter() - started) * 1000.0)
                if any(result.text == text for result in results):
                    total_hits += 1
    convergence_rate = total_hits / total_expected if total_expected else 0.0

    deleted_namespace = namespaces[0]
    source_region = tuple(regions)[min(1, len(regions) - 1)]
    deleted_text = f"{source_region} active active service namespace 0 memory"
    started = time.perf_counter()
    deleted = client.forget(
        regions[source_region],
        text=deleted_text,
        namespace=deleted_namespace,
    )
    operation_latencies.append((time.perf_counter() - started) * 1000.0)
    expected[deleted_namespace].discard(deleted_text)

    tombstone_report = worker.run_once(namespaces=namespaces, limit=limit)
    reports.append(tombstone_report)
    sync_latencies.append(tombstone_report.duration_ms)

    delete_checks = []
    for address in regions.values():
        started = time.perf_counter()
        results = client.query(address, text=deleted_text, namespace=deleted_namespace, top_k=3)
        operation_latencies.append((time.perf_counter() - started) * 1000.0)
        delete_checks.append(all(result.text != deleted_text for result in results))
    delete_suppression_rate = sum(1 for item in delete_checks if item) / len(delete_checks)

    final_report = worker.run_once(namespaces=namespaces, limit=limit)
    reports.append(final_report)
    sync_latencies.append(final_report.duration_ms)

    pair_reports = [pair for report in reports for pair in report.pair_reports]
    ok_pairs = sum(1 for pair in pair_reports if pair.ok)
    success_rate = ok_pairs / len(pair_reports) if pair_reports else 0.0
    return {
        "engine": "WaveMind real HTTP active-active service-region sync",
        "region_count": len(regions),
        "namespaces": namespace_count,
        "writes": write_count,
        "deleted_records_requested": deleted,
        "sync_cycles": len(reports),
        "pair_syncs": len(pair_reports),
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
        "avg_sync_ms": _mean(sync_latencies),
        "p99_sync_ms": _percentile(sync_latencies, 99),
        "avg_operation_ms": _mean(operation_latencies),
        "p99_operation_ms": _percentile(operation_latencies, 99),
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Run active-active namespace-delta sync through real WaveMind HTTP API "
            "regions. With no --region arguments, the runner starts local replicated "
            "API processes and uses the same workload."
        )
    )
    parser.add_argument("--region", action="append", default=[], help="Region as id=url or url.")
    parser.add_argument("--regions", type=int, default=3)
    parser.add_argument("--replicas-per-region", type=int, default=3)
    parser.add_argument("--namespace-prefix", default=None)
    parser.add_argument("--namespace-count", type=int, default=2)
    parser.add_argument("--limit", type=int)
    parser.add_argument("--timeout", type=float, default=15.0)
    parser.add_argument("--readiness-timeout", type=float, default=25.0)
    parser.add_argument("--api-key", default=None)
    parser.add_argument("--min-success-rate", type=float, default=1.0)
    parser.add_argument("--min-convergence-rate", type=float, default=1.0)
    parser.add_argument("--min-delete-suppression-rate", type=float, default=1.0)
    parser.add_argument("--p99-slo-ms", type=float, default=1500.0)
    parser.add_argument("--fail-on-slo", action="store_true")
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("benchmarks/local_http_active_active_smoke_results.json"),
    )
    return parser


def run_from_args(args: argparse.Namespace) -> dict[str, object]:
    if args.namespace_count <= 0:
        raise ValueError("--namespace-count must be positive")
    if not args.region and args.regions < 2:
        raise ValueError("--regions must be at least 2")
    if args.replicas_per_region < 1:
        raise ValueError("--replicas-per-region must be positive")

    namespace_prefix = args.namespace_prefix or f"tenant:http-active-active:{int(time.time())}"
    started_at = time.time()
    local_regions: list[LocalReplicatedRegion] = []
    local_root: Path | None = None
    try:
        if args.region:
            regions = parse_region_specs(args.region)
            source = "external-regions"
            root_path = None
        else:
            source = "local-replicated-api-processes"
            local_root = Path(tempfile.mkdtemp(prefix="wavemind-active-active-"))
            for index in range(args.regions):
                local_regions.append(
                    start_replicated_region(
                        local_root,
                        f"region-{index:03d}",
                        replicas_per_region=args.replicas_per_region,
                        readiness_timeout_seconds=args.readiness_timeout,
                    )
                )
            regions = {region.id: region.address for region in local_regions}
            root_path = None
            result = run_active_active_service_workload(
                regions,
                client=HTTPNamespaceShardClient(
                    api_key=args.api_key,
                    timeout=args.timeout,
                    trust_env=False,
                ),
                namespace_prefix=namespace_prefix,
                namespace_count=args.namespace_count,
                limit=args.limit,
            )
            result["slo_min_success_rate"] = args.min_success_rate
            result["slo_min_convergence_rate"] = args.min_convergence_rate
            result["slo_min_delete_suppression_rate"] = args.min_delete_suppression_rate
            result["slo_p99_ms"] = args.p99_slo_ms
            result["slo_pass"] = _slo_pass(result, args)
            return _payload(args, regions, result, namespace_prefix, source, root_path, started_at)

        result = run_active_active_service_workload(
            regions,
            client=HTTPNamespaceShardClient(
                api_key=args.api_key,
                timeout=args.timeout,
                trust_env=False,
            ),
            namespace_prefix=namespace_prefix,
            namespace_count=args.namespace_count,
            limit=args.limit,
        )
        result["slo_min_success_rate"] = args.min_success_rate
        result["slo_min_convergence_rate"] = args.min_convergence_rate
        result["slo_min_delete_suppression_rate"] = args.min_delete_suppression_rate
        result["slo_p99_ms"] = args.p99_slo_ms
        result["slo_pass"] = _slo_pass(result, args)
        return _payload(args, regions, result, namespace_prefix, source, root_path, started_at)
    finally:
        stop_regions(local_regions)
        if local_root is not None:
            shutil.rmtree(local_root, ignore_errors=True)


def _payload(
    args: argparse.Namespace,
    regions: dict[str, str],
    result: dict[str, object],
    namespace_prefix: str,
    source: str,
    root_path: str | None,
    started_at: float,
) -> dict[str, object]:
    return {
        "scenario": {
            "name": "local_http_active_active_smoke",
            "source": source,
            "region_count": len(regions),
            "region_ids": list(regions),
            "replicas_per_region": args.replicas_per_region if source.startswith("local") else None,
            "namespace_prefix": namespace_prefix,
            "namespace_count": args.namespace_count,
            "root_path": root_path,
            "duration_ms": (time.time() - started_at) * 1000.0,
            "description": (
                "Real HTTP active-active service-region smoke for namespace delta "
                "export/import, cursor idempotency, convergence, and delete propagation."
            ),
        },
        "results": [result],
    }


def _slo_pass(result: dict[str, object], args: argparse.Namespace) -> bool:
    return (
        float(result["success_rate"]) >= args.min_success_rate
        and float(result["convergence_rate"]) >= args.min_convergence_rate
        and float(result["delete_suppression_rate"]) >= args.min_delete_suppression_rate
        and float(result["p99_operation_ms"]) <= args.p99_slo_ms
        and int(result["failed_pairs"]) == 0
        and int(result["final_noop_records_imported"]) == 0
    )


def _mean(values: list[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def _percentile(values: list[float], percentile: int) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = min(len(ordered) - 1, int(len(ordered) * percentile / 100))
    return ordered[index]


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    try:
        payload = run_from_args(args)
    except ValueError as exc:
        parser.error(str(exc))

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    result = payload["results"][0]
    print("| profile | key metric | value |")
    print("|---|---|---:|")
    print(f"| HTTP active-active | regions | {result['region_count']} |")
    print(f"| HTTP active-active | convergence_rate | {result['convergence_rate']:.3f} |")
    print(f"| HTTP active-active | delete_suppression_rate | {result['delete_suppression_rate']:.3f} |")
    print(f"| HTTP active-active | success_rate | {result['success_rate']:.3f} |")
    print(f"| HTTP active-active | final_noop_records_imported | {result['final_noop_records_imported']} |")
    print(f"| HTTP active-active | p99_operation_ms | {result['p99_operation_ms']:.2f} |")
    print(f"| HTTP active-active | slo_pass | {result['slo_pass']} |")
    print(f"\nWrote {args.output}")
    if args.fail_on_slo and not result["slo_pass"]:
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
