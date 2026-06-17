import socket
import subprocess
import sys
import time

import httpx


def free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def start_api(db_path, port: int) -> subprocess.Popen:
    return subprocess.Popen(
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


def wait_until_ready(base_url: str, process: subprocess.Popen) -> None:
    deadline = time.time() + 20
    last_error = None
    with httpx.Client(trust_env=False) as client:
        while time.time() < deadline:
            if process.poll() is not None:
                stdout, stderr = process.communicate(timeout=1)
                raise AssertionError(
                    f"API process exited early with {process.returncode}\nSTDOUT:\n{stdout}\nSTDERR:\n{stderr}"
                )
            try:
                response = client.get(f"{base_url}/stats", timeout=1)
                if response.status_code == 200:
                    return
            except (httpx.NetworkError, httpx.TimeoutException) as exc:
                last_error = exc
            time.sleep(0.25)
    raise AssertionError(f"API did not become ready: {last_error}")


def kill_process(process: subprocess.Popen) -> None:
    if process.poll() is not None:
        return
    process.kill()
    try:
        process.communicate(timeout=5)
    except subprocess.TimeoutExpired:
        process.terminate()
        process.communicate(timeout=5)


def test_api_persists_10_memories_across_process_restart(tmp_path):
    db_path = tmp_path / "persistent.sqlite3"
    port = free_port()
    base_url = f"http://127.0.0.1:{port}"
    memories = [
        f"wmrestart{i:02d} контрольная память номер {i} сохраняется в sqlite"
        for i in range(10)
    ]

    first = start_api(db_path, port)
    try:
        wait_until_ready(base_url, first)
        with httpx.Client(trust_env=False) as client:
            for text in memories:
                response = client.post(
                    f"{base_url}/remember",
                    json={"text": text, "namespace": "restart", "tags": ["persistence"]},
                    timeout=5,
                )
                assert response.status_code == 200
                assert response.json()["id"] > 0
    finally:
        kill_process(first)

    second = start_api(db_path, port)
    try:
        wait_until_ready(base_url, second)
        with httpx.Client(trust_env=False) as client:
            for i, expected in enumerate(memories):
                response = client.post(
                    f"{base_url}/query",
                    json={
                        "text": f"wmrestart{i:02d}",
                        "namespace": "restart",
                        "tags": ["persistence"],
                        "top_k": 3,
                    },
                    timeout=5,
                )
                assert response.status_code == 200
                texts = [item["text"] for item in response.json()["results"]]
                assert expected in texts
    finally:
        kill_process(second)
