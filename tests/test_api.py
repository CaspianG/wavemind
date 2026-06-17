from fastapi.testclient import TestClient

from wavemind import HashingTextEncoder, WaveMind
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
    client = TestClient(create_app(mind=mind))

    remember = client.post(
        "/remember",
        json={
            "text": "кошка сидит на подоконнике",
            "namespace": "pets",
            "tags": ["animal"],
            "ttl_seconds": 3600,
        },
    )
    assert remember.status_code == 200
    memory_id = remember.json()["id"]

    query = client.post(
        "/query",
        json={"text": "кошка", "namespace": "pets", "top_k": 3, "tags": ["animal"]},
    )
    assert query.status_code == 200
    assert query.json()["results"][0]["id"] == memory_id
    assert query.json()["results"][0]["text"] == "кошка сидит на подоконнике"

    stats = client.get("/stats", params={"namespace": "pets"})
    assert stats.status_code == 200
    assert stats.json()["active_memories"] == 1

    deleted = client.request(
        "DELETE",
        "/forget",
        json={"id": memory_id, "namespace": "pets"},
    )
    assert deleted.status_code == 200
    assert deleted.json()["deleted"] == 1

    empty = client.post("/query", json={"text": "кошка", "namespace": "pets"})
    assert empty.json()["results"] == []

