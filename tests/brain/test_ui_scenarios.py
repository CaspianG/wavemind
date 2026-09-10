"""Real owner browser workflows; missing browser tooling is an unexecuted gate."""

import json
import os
import shutil
import socket
import subprocess
import sys
import threading
import time

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
import uvicorn

from wavemind.brain.auth import BrainAuth
from wavemind.brain.http import mount_brain
from wavemind.brain.service import BrainService
from wavemind.brain.models import BrainError, Principal
from wavemind.brain.sources import mark_context_pending


@pytest.mark.parametrize("rejection", ["host", "body"])
def test_boundary_rejections_keep_privacy_headers(tmp_path, rejection):
    auth = BrainAuth(tmp_path)
    auth.bootstrap_owner()
    service = BrainService(tmp_path, bootstrap_owner=auth.owner_identity)
    app = FastAPI()
    mount_brain(app, service, auth)
    with TestClient(app, base_url="http://127.0.0.1:8000") as client:
        if rejection == "host":
            response = client.get("/brain", headers={"Host": "untrusted.invalid"})
            assert response.status_code == 403
        else:
            response = client.post("/brain/api/login", content=b"x" * 1048577)
            assert response.status_code == 413
        assert response.headers.get("cache-control") == "no-store"
        assert response.headers.get("referrer-policy") == "no-referrer"
        assert response.headers.get("x-content-type-options") == "nosniff"


class LocalServer:
    def __init__(self, state, port):
        self.state, self.port = state, port

    def start(self):
        auth = BrainAuth(self.state)
        self.auth = auth
        auth.allowed_hosts = [f"127.0.0.1:{self.port}"]
        service = BrainService(self.state, bootstrap_owner=auth.owner_identity)

        # A trusted fixture verifier, deliberately failing without exposing diagnostics.
        def unavailable(_):
            raise RuntimeError("synthetic verifier unavailable")

        service.register_outcome_verifier(
            verifier_id="demo-unavailable", source="test", callback=unavailable
        )
        app = FastAPI()
        mount_brain(app, service, auth)
        self.server = uvicorn.Server(
            uvicorn.Config(
                app,
                host="127.0.0.1",
                port=self.port,
                log_level="critical",
                access_log=False,
            )
        )
        self.thread = threading.Thread(target=self.server.run, daemon=True)
        self.thread.start()
        deadline = time.monotonic() + 15
        while (
            not self.server.started
            and self.thread.is_alive()
            and time.monotonic() < deadline
        ):
            time.sleep(0.02)
        assert self.server.started, "Owned test HTTP server did not start"

    def stop(self):
        self.server.should_exit = True
        self.thread.join(15)
        assert not self.thread.is_alive(), "Owned test HTTP server did not stop"


@pytest.mark.parametrize(
    "scenario,variant", [("P1", 0), ("P1", 1), ("B1", 0), ("B1", 1)]
)
def test_real_owner_browser_journey(tmp_path, scenario, variant):
    node = os.environ.get("BRAIN_UI_NODE") or shutil.which("node")
    if not node:
        pytest.skip("UNEXECUTED browser gate: Node/Playwright runtime unavailable")
    state = tmp_path / "state"
    auth = BrainAuth(state)
    secret = auth.bootstrap_owner()
    auth.close()
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        port = listener.getsockname()[1]
    server = LocalServer(state, port)
    evidence = tmp_path / "evidence"
    evidence.mkdir()
    print(f"Browser evidence: {evidence}")
    env = {
        **os.environ,
        "BRAIN_UI_ORIGIN": f"http://127.0.0.1:{port}",
        "BRAIN_UI_OWNER_KEY": secret,
        "BRAIN_UI_EVIDENCE": str(evidence),
        "BRAIN_UI_PYTHON": sys.executable,
        "BRAIN_UI_TEST_CONTROL": "1",
        "BRAIN_UI_SCENARIO": scenario,
        "BRAIN_UI_VARIANT": str(variant),
    }
    process = None
    server.start()
    try:
        process = subprocess.Popen(
            [node, "scripts/verify_brain_ui.mjs"],
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
        )
        deadline = time.monotonic() + 240
        restarted = False
        expired = revoked = False
        while process.poll() is None and time.monotonic() < deadline:
            if (evidence / "restart.request").exists() and not restarted:
                server.stop()
                pending_service = BrainService(state)
                try:
                    with pending_service.store.transaction(write=True) as conn:
                        for row in conn.execute("SELECT id FROM brains").fetchall():
                            mark_context_pending(conn, brain_id=row["id"])
                finally:
                    pending_service.close()
                server.start()
                (evidence / "restart.ready").touch()
                restarted = True
            if (evidence / "expire.request").exists() and not expired:
                with server.auth._transaction() as conn:
                    conn.execute("UPDATE sessions SET expires_at=0")
                expired = True
                (evidence / "expire.ready").touch()
            if (evidence / "revoke.request").exists() and not revoked:
                server.auth.revoke_token(
                    principal=server.auth.authenticate(secret),
                    token_id=server.auth.token_id(secret),
                )
                revoked = True
                (evidence / "revoke.ready").touch()
            time.sleep(0.05)
        if process.poll() is None:
            process.kill()
        stdout, stderr = process.communicate(timeout=10)
        # Script deliberately never prints request headers, response secrets or traceback locals.
        assert secret not in stdout + stderr, "Credential appeared in browser output"
        if process.returncode == 77:
            pytest.skip("UNEXECUTED browser gate: " + stderr.strip())
        assert process.returncode == 0, stdout + stderr
        assert restarted, "Scenario did not exercise a service restart"
        assert expired and revoked, (
            "Scenario did not exercise session expiry and parent revocation"
        )
        result = json.loads((evidence / "result.json").read_text(encoding="utf-8"))
        assert result["two_bound_clients"] is True
        assert result["cross_client_denied"] is True
        assert result["scenario"] == scenario
    finally:
        if process and process.poll() is None:
            process.kill()
            process.communicate(timeout=10)
        server.stop()
    reopened_auth = BrainAuth(state)
    reopened = BrainService(state, bootstrap_owner=reopened_auth.owner_identity)
    try:
        with pytest.raises(BrainError):
            reopened_auth.authenticate(secret)
        # Trusted fixture inspection after intentionally revoking its generated bootstrap key.
        owner = Principal(reopened_auth.owner_identity)
        brains = reopened.list_brains(principal=owner)
        assert len(brains) == 2
        memory = reopened.review_memory(principal=owner, brain_id=result["brain_id"])
        assert not any(c.get("id") == "budget" for c in memory["claims"])
        assert any(c.get("id") == "goal" for c in memory["claims"])
    finally:
        reopened.close()
        reopened_auth.close()
