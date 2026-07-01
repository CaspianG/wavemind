from fastapi.testclient import TestClient

from wavemind import HashingTextEncoder, WaveMind, __version__
from wavemind.api import create_app


def test_fastapi_remember_query_forget_and_stats(tmp_path):
    mind = WaveMind(
        db_path=tmp_path / "api.sqlite3",
        width=32,
        height=32,
        layers=2,
        encoder=HashingTextEncoder(vector_dim=64),
        score_threshold=0.05,
    )
    try:
        with TestClient(create_app(mind=mind)) as client:
            remember = client.post(
                "/remember",
                json={
                    "text": "cat sits on the windowsill",
                    "namespace": "pets",
                    "tags": ["animal"],
                    "ttl_seconds": 3600,
                },
            )
            assert remember.status_code == 200
            memory_id = remember.json()["id"]

            query = client.post(
                "/query",
                json={"text": "cat", "namespace": "pets", "top_k": 3, "tags": ["animal"]},
            )
            assert query.status_code == 200
            assert query.json()["results"][0]["id"] == memory_id
            assert query.json()["results"][0]["text"] == "cat sits on the windowsill"

            stats = client.get("/stats", params={"namespace": "pets"})
            assert stats.status_code == 200
            assert stats.json()["active_memories"] == 1
            assert stats.json()["audit_events"] == 1

            audit = client.get("/audit", params={"namespace": "pets"})
            assert audit.status_code == 200
            assert audit.json()["events"][0]["action"] == "remember"
            assert audit.json()["events"][0]["memory_id"] == memory_id

            metrics = client.get("/metrics", params={"namespace": "pets"})
            assert metrics.status_code == 200
            assert "wavemind_active_memories 1" in metrics.text
            assert "wavemind_audit_events 1" in metrics.text
            assert "wavemind_index_healthy 1" in metrics.text

            health = client.get("/index/health")
            assert health.status_code == 200
            assert health.json()["healthy"] is True
            assert health.json()["expected_count"] == 1

            backup_dir = tmp_path / "api-backups"
            backup = client.post(
                "/backup",
                json={
                    "path": str(backup_dir),
                    "keep_last": 1,
                    "prefix": "api",
                },
            )
            assert backup.status_code == 200
            assert backup.json()["path"].endswith(".sqlite3")
            assert len(list(backup_dir.glob("api-*.sqlite3"))) == 1

            mind.index.remove(memory_id)
            drifted = client.get("/index/health")
            assert drifted.json()["healthy"] is False

            rebuilt = client.post("/index/rebuild")
            assert rebuilt.status_code == 200
            assert rebuilt.json()["healthy"] is True

            deleted = client.request(
                "DELETE",
                "/forget",
                json={"id": memory_id, "namespace": "pets"},
            )
            assert deleted.status_code == 200
            assert deleted.json()["deleted"] == 1

            empty = client.post("/query", json={"text": "cat", "namespace": "pets"})
            assert empty.json()["results"] == []
    finally:
        mind.close()


def test_fastapi_query_accepts_query_alias(tmp_path):
    mind = WaveMind(
        db_path=tmp_path / "api.sqlite3",
        width=32,
        height=32,
        layers=2,
        encoder=HashingTextEncoder(vector_dim=64),
        score_threshold=0.0,
    )
    try:
        with TestClient(create_app(mind=mind)) as client:
            remember = client.post(
                "/remember",
                json={"text": "Andrey is a trader", "namespace": "demo"},
            )
            assert remember.status_code == 200

            query = client.post(
                "/query",
                json={"query": "trader", "namespace": "demo", "top_k": 1},
            )

            assert query.status_code == 200
            assert query.json()["results"][0]["text"] == "Andrey is a trader"
    finally:
        mind.close()


def test_fastapi_studio_dashboard_state_heatmap_and_feedback(tmp_path):
    mind = WaveMind(
        db_path=tmp_path / "studio.sqlite3",
        width=32,
        height=32,
        layers=2,
        encoder=HashingTextEncoder(vector_dim=64),
    )
    try:
        memory_id = mind.remember(
            "Andrey prefers WaveMind Studio for visual memory inspection",
            namespace="studio",
            tags=["ui"],
            metadata={"conflict_group": "preference.ui"},
        )
        mind.remember(
            "Andrey prefers terminal-only memory inspection",
            namespace="studio",
            tags=["ui"],
            metadata={"conflict_group": "preference.ui"},
        )
        before = mind.store.get(memory_id)
        assert before is not None

        with TestClient(create_app(mind=mind)) as client:
            page = client.get("/studio")
            assert page.status_code == 200
            assert "WaveMind Studio" in page.text

            state = client.get("/studio/state", params={"namespace": "studio"})
            assert state.status_code == 200
            payload = state.json()
            assert "studio" in payload["namespaces"]
            assert payload["stats"]["active_memories"] == 2
            assert payload["memories"][0]["namespace"] == "studio"
            assert payload["conflict_groups"][0]["group"] == "preference.ui"

            fallback_state = client.get("/studio/state", params={"namespace": "default"})
            assert fallback_state.status_code == 200
            assert fallback_state.json()["selected_namespace"] == "studio"
            assert fallback_state.json()["memories"][0]["namespace"] == "studio"

            heatmap = client.get("/studio/heatmap", params={"bins": 8})
            assert heatmap.status_code == 200
            heatmap_payload = heatmap.json()
            assert heatmap_payload["bins"] == 8
            assert len(heatmap_payload["values"]) == 64
            assert max(heatmap_payload["values"]) <= 1.0

            feedback = client.post(
                "/studio/feedback",
                json={"id": memory_id, "useful": True, "strength": 0.5},
            )
            assert feedback.status_code == 200
            after = mind.store.get(memory_id)
            assert after is not None
            assert after.priority > before.priority
            assert after.access_count == before.access_count + 1
            assert mind.audit_events(namespace="studio", action="feedback", limit=1)
    finally:
        mind.close()


def test_fastapi_version_matches_package_version():
    mind = WaveMind(
        db_path=None,
        width=16,
        height=16,
        layers=1,
        encoder=HashingTextEncoder(vector_dim=16),
    )
    try:
        app = create_app(mind=mind)
        assert app.version == __version__
    finally:
        mind.close()


def test_fastapi_api_keys_enforce_roles(tmp_path, monkeypatch):
    monkeypatch.setenv("WAVEMIND_READ_KEYS", "read-key")
    monkeypatch.setenv("WAVEMIND_WRITE_KEYS", "write-key")
    monkeypatch.setenv("WAVEMIND_ADMIN_KEYS", "admin-key")
    mind = WaveMind(
        db_path=tmp_path / "auth.sqlite3",
        width=32,
        height=32,
        layers=2,
        encoder=HashingTextEncoder(vector_dim=64),
    )
    try:
        memory_id = mind.remember("role based API memory", namespace="auth")
        with TestClient(create_app(mind=mind)) as client:
            missing = client.get("/stats", params={"namespace": "auth"})
            assert missing.status_code == 401

            read_stats = client.get(
                "/stats",
                params={"namespace": "auth"},
                headers={"X-API-Key": "read-key"},
            )
            assert read_stats.status_code == 200

            read_write = client.post(
                "/remember",
                json={"text": "read key cannot write", "namespace": "auth"},
                headers={"X-API-Key": "read-key"},
            )
            assert read_write.status_code == 403

            write = client.post(
                "/remember",
                json={"text": "write key can write", "namespace": "auth"},
                headers={"Authorization": "Bearer write-key"},
            )
            assert write.status_code == 200

            write_audit = client.get(
                "/audit",
                params={"namespace": "auth"},
                headers={"X-API-Key": "write-key"},
            )
            assert write_audit.status_code == 403

            admin_audit = client.get(
                "/audit",
                params={"namespace": "auth"},
                headers={"X-API-Key": "admin-key"},
            )
            assert admin_audit.status_code == 200

            read_backup = client.post(
                "/backup",
                json={"path": str(tmp_path / "read-backup.sqlite3")},
                headers={"X-API-Key": "read-key"},
            )
            assert read_backup.status_code == 403

            admin_backup = client.post(
                "/backup",
                json={"path": str(tmp_path / "admin-backup.sqlite3")},
                headers={"X-API-Key": "admin-key"},
            )
            assert admin_backup.status_code == 200

            deleted = client.request(
                "DELETE",
                "/forget",
                json={"id": memory_id, "namespace": "auth"},
                headers={"X-API-Key": "admin-key"},
            )
            assert deleted.status_code == 200
    finally:
        mind.close()


def test_fastapi_rate_limit_is_opt_in(tmp_path, monkeypatch):
    monkeypatch.delenv("WAVEMIND_READ_KEYS", raising=False)
    monkeypatch.delenv("WAVEMIND_WRITE_KEYS", raising=False)
    monkeypatch.delenv("WAVEMIND_ADMIN_KEYS", raising=False)
    monkeypatch.delenv("WAVEMIND_API_KEYS", raising=False)
    monkeypatch.setenv("WAVEMIND_RATE_LIMIT_PER_MINUTE", "2")
    mind = WaveMind(
        db_path=tmp_path / "rate.sqlite3",
        width=32,
        height=32,
        layers=2,
        encoder=HashingTextEncoder(vector_dim=64),
    )
    try:
        with TestClient(create_app(mind=mind)) as client:
            assert client.get("/stats").status_code == 200
            assert client.get("/stats").status_code == 200
            limited = client.get("/stats")
            assert limited.status_code == 429
            assert limited.json()["detail"] == "Rate limit exceeded"
    finally:
        mind.close()
