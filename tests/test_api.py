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
