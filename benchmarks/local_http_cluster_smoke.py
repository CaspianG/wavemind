from __future__ import annotations

import argparse
import json
import os
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
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from benchmarks.scale_readiness_benchmark import run_sustained_http_cluster_workload
from wavemind import ClusterNode, DistributedShardedWaveMind, HTTPNamespaceShardClient


@dataclass(frozen=True)
class LocalAPINode:
    id: str
    address: str
    zone: str
    db_path: Path
    process: subprocess.Popen[str]


def free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def wait_until_ready(node: LocalAPINode, *, timeout_seconds: float = 20.0) -> None:
    opener = build_opener(ProxyHandler({}))
    deadline = time.time() + timeout_seconds
    last_error: object = None
    while time.time() < deadline:
        if node.process.poll() is not None:
            stdout, stderr = node.process.communicate(timeout=1)
            raise RuntimeError(
                f"{node.id} exited before readiness with {node.process.returncode}\n"
                f"STDOUT:\n{stdout}\nSTDERR:\n{stderr}"
            )
        try:
            request = Request(f"{node.address}/stats", method="GET")
            with opener.open(request, timeout=1) as response:
                if response.status == 200:
                    return
        except (HTTPError, URLError, TimeoutError) as exc:
            last_error = exc
        time.sleep(0.2)
    raise RuntimeError(f"{node.id} did not become ready: {last_error}")


def start_api_node(
    root: Path,
    node_id: str,
    *,
    host: str = "127.0.0.1",
    port: int | None = None,
    readiness_timeout_seconds: float = 20.0,
) -> LocalAPINode:
    port = free_port() if port is None else int(port)
    db_path = root / f"{node_id}.sqlite3"
    env = dict(os.environ)
    env.setdefault("WAVEMIND_API_SERIALIZE_OPERATIONS", "1")
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
            host,
            "--port",
            str(port),
        ],
        cwd=PROJECT_ROOT,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
    )
    node = LocalAPINode(
        id=node_id,
        address=f"http://{host}:{port}",
        zone=f"zone-{int(node_id.rsplit('-', 1)[-1]) % 3 if '-' in node_id else 0}",
        db_path=db_path,
        process=process,
    )
    wait_until_ready(node, timeout_seconds=readiness_timeout_seconds)
    return node


def stop_api_nodes(nodes: list[LocalAPINode]) -> None:
    for node in nodes:
        if node.process.poll() is None:
            node.process.terminate()
    for node in nodes:
        if node.process.poll() is not None:
            continue
        try:
            node.process.communicate(timeout=5)
        except subprocess.TimeoutExpired:
            node.process.kill()
            node.process.communicate(timeout=5)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Start several real localhost WaveMind API processes, run the "
            "sustained HTTP cluster workload against them, and fail on SLO "
            "regression. This is the CI-friendly production-scale smoke gate."
        )
    )
    parser.add_argument("--nodes", type=int, default=4)
    parser.add_argument("--replication-factor", type=int, default=3)
    parser.add_argument("--write-quorum", type=int, default=None)
    parser.add_argument("--read-quorum", type=int, default=1)
    parser.add_argument(
        "--read-fanout",
        type=int,
        default=1,
        help="Number of replicas queried per read. CI smoke defaults to quorum-sized reads.",
    )
    parser.add_argument("--namespace-prefix", default=None)
    parser.add_argument("--namespace-count", type=int, default=4)
    parser.add_argument("--memories-per-namespace", type=int, default=2)
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--timeout", type=float, default=15.0)
    parser.add_argument("--readiness-timeout", type=float, default=20.0)
    parser.add_argument("--min-success-rate", type=float, default=1.0)
    parser.add_argument("--min-failover-hit-rate", type=float, default=0.95)
    parser.add_argument("--p99-slo-ms", type=float, default=1000.0)
    parser.add_argument("--fail-on-slo", action="store_true")
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("benchmarks/local_http_cluster_smoke_results.json"),
    )
    return parser


def _validate_args(args: argparse.Namespace) -> None:
    if args.nodes < 2:
        raise ValueError("--nodes must be at least 2")
    if args.replication_factor <= 0:
        raise ValueError("--replication-factor must be positive")
    if args.replication_factor > args.nodes:
        raise ValueError("--replication-factor cannot exceed --nodes")
    if args.read_fanout <= 0:
        raise ValueError("--read-fanout must be positive")
    if args.read_fanout < args.read_quorum:
        raise ValueError("--read-fanout cannot be smaller than --read-quorum")
    if args.read_fanout > args.replication_factor:
        raise ValueError("--read-fanout cannot exceed --replication-factor")
    if args.namespace_count <= 0:
        raise ValueError("--namespace-count must be positive")
    if args.memories_per_namespace < 2:
        raise ValueError("--memories-per-namespace must be at least 2")
    if args.workers <= 0:
        raise ValueError("--workers must be positive")


def run_from_args(args: argparse.Namespace) -> dict[str, object]:
    _validate_args(args)
    namespace_prefix = args.namespace_prefix or f"tenant:local-http:{int(time.time())}"
    started_at = time.time()
    with tempfile.TemporaryDirectory(prefix="wavemind-local-http-") as directory:
        root = Path(directory)
        nodes: list[LocalAPINode] = []
        try:
            for index in range(args.nodes):
                nodes.append(
                    start_api_node(
                        root,
                        f"node-{index:03d}",
                        readiness_timeout_seconds=args.readiness_timeout,
                    )
                )
            cluster_nodes = [
                ClusterNode(id=node.id, address=node.address, zone=node.zone)
                for node in nodes
            ]
            client = HTTPNamespaceShardClient(
                timeout=args.timeout,
                trust_env=False,
            )
            result = run_sustained_http_cluster_workload(
                cluster_nodes,
                client=client,
                engine="WaveMind local HTTP cluster smoke",
                namespace_prefix=namespace_prefix,
                namespace_count=args.namespace_count,
                memories_per_namespace=args.memories_per_namespace,
                replication_factor=args.replication_factor,
                write_quorum=args.write_quorum,
                read_quorum=args.read_quorum,
                read_fanout=args.read_fanout,
                max_workers=args.workers,
            )
            health_memory = DistributedShardedWaveMind(
                nodes=cluster_nodes,
                replication_factor=args.replication_factor,
                write_quorum=args.write_quorum,
                read_quorum=args.read_quorum,
                read_fanout=args.read_fanout,
                client=client,
            )
            health = health_memory.probe_nodes()
            healthy_nodes = sum(
                1 for payload in health.values() if payload["status"] == "healthy"
            )
            degraded_nodes = sum(
                1 for payload in health.values() if payload["status"] == "degraded"
            )
            unavailable_nodes = sum(
                1 for payload in health.values() if payload["status"] == "unavailable"
            )
            cluster_health_ok = (
                healthy_nodes == len(cluster_nodes)
                and degraded_nodes == 0
                and unavailable_nodes == 0
            )
            result["cluster_health_ok"] = cluster_health_ok
            result["healthy_nodes"] = healthy_nodes
            result["degraded_nodes"] = degraded_nodes
            result["unavailable_nodes"] = unavailable_nodes
            result["node_health"] = health
            result["slo_min_success_rate"] = args.min_success_rate
            result["slo_min_failover_hit_rate"] = args.min_failover_hit_rate
            result["slo_p99_ms"] = args.p99_slo_ms
            result["slo_pass"] = (
                float(result["success_rate"]) >= args.min_success_rate
                and float(result["failover_hit_rate"]) >= args.min_failover_hit_rate
                and float(result["p99_operation_ms"]) <= args.p99_slo_ms
                and cluster_health_ok
            )
            return {
                "scenario": {
                    "name": "local_http_cluster_smoke",
                    "node_count": args.nodes,
                    "replication_factor": args.replication_factor,
                    "write_quorum": args.write_quorum
                    if args.write_quorum is not None
                    else args.replication_factor // 2 + 1,
                    "read_quorum": args.read_quorum,
                    "read_fanout": args.read_fanout,
                    "namespace_prefix": namespace_prefix,
                    "namespace_count": args.namespace_count,
                    "memories_per_namespace": args.memories_per_namespace,
                    "workers": args.workers,
                    "started_api_processes": len(nodes),
                    "duration_ms": (time.time() - started_at) * 1000.0,
                    "description": (
                        "CI-friendly real localhost API-node cluster smoke for "
                        "quorum writes, queries, failover reads, repair, forget, "
                        "and delete suppression."
                    ),
                },
                "results": [result],
            }
        finally:
            stop_api_nodes(nodes)


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
    print(f"| local HTTP cluster | nodes | {result['nodes']} |")
    print(f"| local HTTP cluster | success_rate | {result['success_rate']:.3f} |")
    print(f"| local HTTP cluster | failover_hit_rate | {result['failover_hit_rate']:.3f} |")
    print(f"| local HTTP cluster | p99_operation_ms | {result['p99_operation_ms']:.2f} |")
    print(f"| local HTTP cluster | healthy_nodes | {result['healthy_nodes']} |")
    print(f"| local HTTP cluster | degraded_nodes | {result['degraded_nodes']} |")
    print(f"| local HTTP cluster | repair_repaired_total | {result['repair_repaired_total']} |")
    print(f"| local HTTP cluster | slo_pass | {result['slo_pass']} |")
    print(f"\nWrote {args.output}")
    if args.fail_on_slo and not result["slo_pass"]:
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
