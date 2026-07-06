import socket
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path

import httpx

from wavemind import ClusterNode, DistributedShardedWaveMind


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


@dataclass(frozen=True)
class _ApiNode:
    node_id: str
    db_path: Path
    port: int
    process: subprocess.Popen

    @property
    def address(self) -> str:
        return f"http://127.0.0.1:{self.port}"


def _start_api_node(tmp_path: Path, node_id: str) -> _ApiNode:
    db_path = tmp_path / f"{node_id}.sqlite3"
    port = _free_port()
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
    node = _ApiNode(node_id=node_id, db_path=db_path, port=port, process=process)
    _wait_until_ready(node)
    return node


def _wait_until_ready(node: _ApiNode) -> None:
    deadline = time.time() + 20.0
    last_error = None
    with httpx.Client(trust_env=False) as client:
        while time.time() < deadline:
            if node.process.poll() is not None:
                stdout, stderr = node.process.communicate(timeout=1)
                raise AssertionError(
                    f"{node.node_id} exited early with {node.process.returncode}\n"
                    f"STDOUT:\n{stdout}\nSTDERR:\n{stderr}"
                )
            try:
                response = client.get(f"{node.address}/stats", timeout=1)
                if response.status_code == 200:
                    return
            except (httpx.NetworkError, httpx.TimeoutException) as exc:
                last_error = exc
            time.sleep(0.2)
    raise AssertionError(f"{node.node_id} did not become ready: {last_error}")


def _stop_api_nodes(nodes: list[_ApiNode]) -> None:
    for node in nodes:
        if node.process.poll() is not None:
            continue
        node.process.kill()
    for node in nodes:
        try:
            node.process.communicate(timeout=5)
        except subprocess.TimeoutExpired:
            node.process.terminate()
            node.process.communicate(timeout=5)


def _cluster(nodes: list[_ApiNode], *, replication_factor: int) -> DistributedShardedWaveMind:
    return DistributedShardedWaveMind(
        nodes=[
            ClusterNode(id=node.node_id, address=node.address, zone=f"zone-{node.node_id}")
            for node in nodes
        ],
        replication_factor=replication_factor,
    )


def _node_by_id(nodes: list[_ApiNode]) -> dict[str, _ApiNode]:
    return {node.node_id: node for node in nodes}


def test_distributed_http_cluster_repairs_missing_replica(tmp_path):
    nodes = [_start_api_node(tmp_path, node_id) for node_id in ("node-a", "node-b", "node-c")]
    by_id = _node_by_id(nodes)
    memory = _cluster(nodes, replication_factor=2)
    namespace = "tenant:http-repair"
    text = "http shard repair copies missing service replica"

    try:
        write = memory.remember(text, namespace=namespace, tags=("ops",), priority=2.0)
        stale_node = next(node_id for node_id in write.writes if node_id != write.primary_node)

        with httpx.Client(trust_env=False) as client:
            deleted = client.request(
                "DELETE",
                f"{by_id[stale_node].address}/forget",
                json={"namespace": namespace, "text": text},
                timeout=5,
            )
            assert deleted.status_code == 200
            assert deleted.json()["deleted"] == 1

        memory.set_node_available(write.primary_node, False)
        assert memory.query("service replica", namespace=namespace, top_k=1) == []
        memory.set_node_available(write.primary_node, True)

        report = memory.repair_namespace(namespace, tags=("ops",))

        assert report.ok
        assert report.canonical_records == 1
        assert report.missing_before_repair[stale_node] == 1
        assert report.repaired[stale_node] == 1

        memory.set_node_available(write.primary_node, False)
        repaired = memory.query("service replica", namespace=namespace, top_k=1)
        assert repaired[0].text == text
        assert repaired[0].metadata["_wavemind_node"] == stale_node
    finally:
        _stop_api_nodes(nodes)


def test_distributed_http_cluster_tombstone_repair_deletes_stale_replica(tmp_path):
    nodes = [_start_api_node(tmp_path, node_id) for node_id in ("node-a", "node-b", "node-c")]
    by_id = _node_by_id(nodes)
    memory = _cluster(nodes, replication_factor=3)
    namespace = "tenant:http-tombstone"
    text = "http tombstone repair must delete stale service memory"

    try:
        write = memory.remember(text, namespace=namespace)
        missed_delete = next(node_id for node_id in write.writes if node_id != write.primary_node)
        memory.set_node_available(missed_delete, False)

        delete = memory.forget(namespace=namespace, text=text)

        assert delete.ok
        assert missed_delete not in delete.deletes
        memory.set_node_available(missed_delete, True)
        assert memory.query("stale service memory", namespace=namespace, top_k=1) == []

        with httpx.Client(trust_env=False) as client:
            before = client.post(
                f"{by_id[missed_delete].address}/memories/export",
                json={"namespace": namespace},
                timeout=5,
            )
            assert before.status_code == 200
            assert len(before.json()["records"]) == 1

        report = memory.repair_namespace(namespace)

        assert report.ok
        assert report.canonical_records == 0
        assert report.tombstone_texts == 1
        assert report.tombstone_deleted == 1

        with httpx.Client(trust_env=False) as client:
            after = client.post(
                f"{by_id[missed_delete].address}/memories/export",
                json={"namespace": namespace},
                timeout=5,
            )
            assert after.status_code == 200
            assert after.json()["records"] == []
    finally:
        _stop_api_nodes(nodes)


def test_distributed_http_cluster_handles_concurrent_namespace_traffic(tmp_path):
    nodes = [_start_api_node(tmp_path, node_id) for node_id in ("node-a", "node-b", "node-c")]
    memory = _cluster(nodes, replication_factor=3)
    namespace = "tenant:http-concurrent"
    texts = [
        f"http concurrent tenant memory item {index:02d}"
        for index in range(12)
    ]

    try:
        with ThreadPoolExecutor(max_workers=6) as pool:
            writes = list(pool.map(lambda text: memory.remember(text, namespace=namespace), texts))

        assert len(writes) == len(texts)
        assert all(write.ok for write in writes)
        assert all(len(write.writes) == 3 for write in writes)

        with ThreadPoolExecutor(max_workers=6) as pool:
            hits = list(
                pool.map(
                    lambda text: any(
                        result.text == text
                        for result in memory.query(text, namespace=namespace, top_k=3)
                    ),
                    texts,
                )
            )

        assert all(hits)
    finally:
        _stop_api_nodes(nodes)
