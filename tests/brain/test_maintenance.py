"""Launched transports drain real durable work and await owned worker shutdown."""

import asyncio
import importlib.util
import threading
from contextlib import asynccontextmanager

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from wavemind.brain.auth import BrainAuth
from wavemind.brain.http import mount_brain
from wavemind.brain.models import Principal
from wavemind.brain.service import BrainService


def queued_outcome(service, owner, brain):
    draft = service.preview_import(
        principal=owner,
        brain_id=brain,
        files=[
            {"name": "run.txt", "content": b"A separately checked real fixture run."}
        ],
    )
    source = service.commit_import(
        principal=owner,
        brain_id=brain,
        preview_id=draft["id"],
        accepted_ids=[draft["files"][0]["id"]],
    )["sources"][0]
    cid = source["citations"][0]["id"]
    packet = service.build_context(principal=owner, brain_id=brain, question="checked")
    receipt = service.begin_action(
        principal=owner,
        brain_id=brain,
        packet_id=packet["id"],
        run_id="maintenance-run",
        action="Report checked run",
    )
    outcome = service.record_outcome(
        principal=owner,
        brain_id=brain,
        receipt_id=receipt["id"],
        outcome={
            "idempotency_key": "maintenance-result",
            "summary": "Checked",
            "procedure": ["Check run"],
            "evidence_citation_ids": [cid],
        },
    )
    verified = service.verify_outcome(
        principal=owner,
        brain_id=brain,
        outcome_id=outcome["id"],
        success=True,
        evidence_citation_ids=[cid],
    )
    assert verified["integration_status"] == "pending"
    return source


def test_retry_real_queued_outcome_and_await_inflight_shutdown(
    tmp_path, monkeypatch, caplog
):
    assert importlib.util.find_spec("wavemind.brain.maintenance") is not None
    from wavemind.brain.maintenance import BrainMaintenance

    service, owner = BrainService(tmp_path), Principal("owner")
    brain = service.create_brain(principal=owner, title="Maintenance")["id"]
    queued_outcome(service, owner, brain)
    original = service.drain_outbox
    calls = 0
    entered, release = threading.Event(), threading.Event()

    def flaky(*, limit):
        nonlocal calls
        calls += 1
        assert limit == 100
        if calls == 1:
            raise OSError("private diagnostic must never be logged")
        if calls == 3:
            entered.set()
            assert release.wait(5)
        return original(limit=limit)

    monkeypatch.setattr(service, "drain_outbox", flaky)

    async def verify():
        maintenance = BrainMaintenance(service)
        await maintenance.start()
        deadline = asyncio.get_running_loop().time() + 4
        while (
            service.review_experience(principal=owner, brain_id=brain)["outcomes"][0][
                "integration_status"
            ]
            != "completed"
        ):
            assert asyncio.get_running_loop().time() < deadline
            await asyncio.sleep(0.02)
        assert await asyncio.to_thread(entered.wait, 3)
        stopping = asyncio.create_task(maintenance.stop())
        await asyncio.sleep(0.05)
        assert not stopping.done(), "Shutdown abandoned its in-flight SQLite worker"
        release.set()
        await stopping
        service.close()
        await asyncio.sleep(0.05)
        assert calls == 3

    try:
        asyncio.run(verify())
        assert "private diagnostic" not in caplog.text
        assert (
            caplog.text.count("Brain maintenance remains pending; retry scheduled.")
            == 1
        )
    finally:
        release.set()
        service.close()


@pytest.mark.parametrize("custom", [False, True])
def test_http_preserves_existing_lifecycle_and_serves_only_packaged_assets(
    tmp_path, custom
):
    auth = BrainAuth(tmp_path)
    auth.bootstrap_owner()
    service = BrainService(tmp_path, bootstrap_owner=auth.owner_identity)
    owner = Principal(auth.owner_identity)
    brain = service.create_brain(principal=owner, title="Lifecycle")["id"]
    queued_outcome(service, owner, brain)
    events = []

    def start():
        events.append("start")

    def stop():
        assert (
            service.review_experience(principal=owner, brain_id=brain)["outcomes"][0][
                "integration_status"
            ]
            == "completed"
        )
        events.append("stop")

    @asynccontextmanager
    async def lifespan(app):
        start()
        yield {"custom_state": True}
        stop()

    app = FastAPI(lifespan=lifespan) if custom else FastAPI()
    if not custom:
        app.router.add_event_handler("startup", start)
        app.router.add_event_handler("shutdown", stop)

    @app.get("/legacy")
    def legacy(value: int = 7):
        return value

    mount_brain(app, service, auth)
    with TestClient(app, base_url="http://127.0.0.1:8000") as client:
        assert events == ["start"]
        assert client.get("/legacy").json() == 7
        for path, mime in [
            ("/brain", "text/html"),
            ("/brain/ui/app.js", "text/javascript"),
            ("/brain/ui/ui.js", "text/javascript"),
            ("/brain/ui/panels.js", "text/javascript"),
            ("/brain/ui/style.css", "text/css"),
        ]:
            response = client.get(path)
            assert response.status_code == 200
            assert response.headers["content-type"].startswith(mime)
            assert response.headers["cache-control"] == "no-store"
            assert "default-src 'none'" in response.headers["content-security-policy"]
            assert response.headers["x-content-type-options"] == "nosniff"
        assert client.get("/brain/ui/maintenance.py").status_code == 404
        assert client.get("/brain/ui/%2e%2e%2fhttp.py").status_code == 404
    assert events == ["start", "stop"]
