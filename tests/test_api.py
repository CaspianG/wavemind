import sys
import types

from fastapi.testclient import TestClient
import numpy as np

from wavemind import HashingTextEncoder, ReplicatedWaveMind, WaveMind, __version__
from wavemind.api import create_app


class ConsolidationEncoder:
    vector_dim = 4

    def encode_vector(self, text: str) -> np.ndarray:
        lowered = text.lower()
        if "pasta" in lowered:
            return self._unit([0.0, 1.0, 0.0, 0.0])
        if "compiler" in lowered:
            return self._unit([0.95, 0.05, 0.0, 0.0])
        return self._unit([1.0, 0.0, 0.0, 0.0])

    def _unit(self, values: list[float]) -> np.ndarray:
        vector = np.asarray(values, dtype=np.float32)
        return vector / (float(np.linalg.norm(vector)) + 1e-9)


class CountingEncoder:
    vector_dim = 4

    def __init__(self):
        self.calls = 0

    def encode_vector(self, text: str) -> np.ndarray:
        self.calls += 1
        if "budget" in text.lower():
            return self._unit([1.0, 0.0, 0.0, 0.0])
        return self._unit([0.0, 1.0, 0.0, 0.0])

    def _unit(self, values: list[float]) -> np.ndarray:
        vector = np.asarray(values, dtype=np.float32)
        return vector / (float(np.linalg.norm(vector)) + 1e-9)


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

            scale_plan = client.get(
                "/scale-plan",
                params={"namespace": "pets", "target_memories": 50000},
            )
            assert scale_plan.status_code == 200
            scale_payload = scale_plan.json()
            assert scale_payload["current_memories"] == 1
            assert scale_payload["target_memories"] == 50000
            assert scale_payload["namespace"] == "pets"
            assert scale_payload["tier"] == "large-local"
            assert scale_payload["recommended_index"] == "faiss-persisted or qdrant"

            cluster_plan = client.post(
                "/cluster-plan",
                json={
                    "namespace_count": 4,
                    "nodes": [
                        {"id": "node-a", "address": "10.0.0.1:8000"},
                        {"id": "node-b", "address": "10.0.0.2:8000"},
                    ],
                    "replication_factor": 2,
                    "include_kubernetes": True,
                    "include_repair_cronjob": True,
                    "repair_schedule": "*/10 * * * *",
                    "repair_api_key_secret": "wavemind-api-key",
                },
            )
            assert cluster_plan.status_code == 200
            cluster_payload = cluster_plan.json()
            assert len(cluster_payload["placements"]) == 4
            assert cluster_payload["kubernetes"]["kind"] == "StatefulSet"
            assert cluster_payload["repair_cronjob"]["kind"] == "CronJob"
            repair_container = cluster_payload["repair_cronjob"]["spec"]["jobTemplate"]["spec"]["template"]["spec"]["containers"][0]
            assert repair_container["env"][0]["valueFrom"]["secretKeyRef"]["name"] == "wavemind-api-key"
            assert "--namespace" in repair_container["args"]

            autoscale = client.post(
                "/cluster-autoscale-plan",
                json={
                    "namespace_count": 64,
                    "nodes": [
                        {"id": "node-a", "address": "10.0.0.1:8000", "zone": "zone-a"},
                        {"id": "node-b", "address": "10.0.0.2:8000", "zone": "zone-b"},
                        {"id": "node-c", "address": "10.0.0.3:8000", "zone": "zone-c"},
                    ],
                    "replication_factor": 3,
                    "target_memories": 10_000_000,
                    "max_memories_per_node": 1_000_000,
                    "zones": ["zone-a", "zone-b", "zone-c"],
                    "max_moves": 5,
                },
            )
            assert autoscale.status_code == 200
            autoscale_payload = autoscale.json()
            assert autoscale_payload["status"] == "scale_required"
            assert autoscale_payload["required_nodes"] >= 43
            assert len(autoscale_payload["moves"]) == 5

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


def test_fastapi_remember_batch_persists_items_and_invalidates_cache(tmp_path):
    mind = WaveMind(
        db_path=tmp_path / "api-remember-batch.sqlite3",
        width=32,
        height=32,
        layers=2,
        encoder=HashingTextEncoder(vector_dim=64),
        score_threshold=0.05,
    )
    try:
        with TestClient(create_app(mind=mind)) as client:
            batch = client.post(
                "/remember/batch",
                json={
                    "items": [
                        {
                            "text": "batch API memory about budget",
                            "namespace": "tenant:batch-api",
                            "tags": ["profile"],
                            "metadata": {"source": "test"},
                        },
                        {
                            "text": "batch API memory about writing style",
                            "namespace": "tenant:batch-api",
                            "tags": ["profile"],
                        },
                    ]
                },
            )

            assert batch.status_code == 200
            payload = batch.json()
            assert payload["count"] == 2
            assert payload["items"][0]["index"] == 0
            assert payload["items"][0]["text"] == "batch API memory about budget"
            assert payload["items"][0]["namespace"] == "tenant:batch-api"
            assert payload["items"][1]["index"] == 1
            assert payload["items"][0]["id"] != payload["items"][1]["id"]

            query = client.post(
                "/query",
                json={
                    "text": "budget",
                    "namespace": "tenant:batch-api",
                    "top_k": 2,
                    "tags": ["profile"],
                },
            )
            assert query.status_code == 200
            texts = {item["text"] for item in query.json()["results"]}
            assert "batch API memory about budget" in texts

            stats = client.get("/stats", params={"namespace": "tenant:batch-api"})
            assert stats.status_code == 200
            assert stats.json()["active_memories"] == 2
    finally:
        mind.close()


def test_fastapi_default_mind_uses_recovery_journal_env(tmp_path, monkeypatch):
    db_path = tmp_path / "api-env.sqlite3"
    journal_path = tmp_path / "api-env.recovery.jsonl"
    monkeypatch.setenv("WAVEMIND_DB", str(db_path))
    monkeypatch.setenv("WAVEMIND_RECOVERY_JOURNAL", str(journal_path))
    monkeypatch.setenv("WAVEMIND_VECTOR_DIM", "64")

    with TestClient(create_app()) as client:
        remembered = client.post(
            "/remember",
            json={"text": "api recovery journal memory", "namespace": "ops"},
        )
        assert remembered.status_code == 200

    assert journal_path.exists()
    assert '"action": "remember"' in journal_path.read_text(encoding="utf-8")


def test_fastapi_forget_invalidates_local_query_cache(tmp_path, monkeypatch):
    monkeypatch.setenv("WAVEMIND_CACHE_CAPACITY", "8")
    monkeypatch.delenv("WAVEMIND_REDIS_URL", raising=False)

    mind = WaveMind(
        db_path=tmp_path / "api-cache-invalidation.sqlite3",
        width=16,
        height=16,
        layers=1,
        encoder=HashingTextEncoder(vector_dim=64),
        score_threshold=0.05,
    )
    try:
        with TestClient(create_app(mind=mind)) as client:
            remembered = client.post(
                "/remember",
                json={"text": "cache invalidation target memory", "namespace": "tenant:cache"},
            )
            assert remembered.status_code == 200
            memory_id = remembered.json()["id"]

            first = client.post(
                "/query",
                json={
                    "text": "cache invalidation target",
                    "namespace": "tenant:cache",
                    "top_k": 1,
                },
            )
            assert first.status_code == 200
            assert first.json()["results"][0]["id"] == memory_id

            deleted = client.request(
                "DELETE",
                "/forget",
                json={"id": memory_id, "namespace": "tenant:cache"},
            )
            assert deleted.status_code == 200
            assert deleted.json()["deleted"] == 1

            second = client.post(
                "/query",
                json={
                    "text": "cache invalidation target",
                    "namespace": "tenant:cache",
                    "top_k": 1,
                },
            )
            assert second.status_code == 200
            assert second.json()["results"] == []
    finally:
        mind.close()


def test_fastapi_feedback_updates_memory_and_invalidates_cache(tmp_path, monkeypatch):
    monkeypatch.setenv("WAVEMIND_CACHE_CAPACITY", "8")
    monkeypatch.delenv("WAVEMIND_REDIS_URL", raising=False)

    mind = WaveMind(
        db_path=tmp_path / "api-feedback.sqlite3",
        width=16,
        height=16,
        layers=1,
        encoder=HashingTextEncoder(vector_dim=64),
        audit_queries=True,
    )
    try:
        with TestClient(create_app(mind=mind)) as client:
            remembered = client.post(
                "/remember",
                json={"text": "explicit user feedback should train hot memory", "namespace": "tenant:fb"},
            )
            assert remembered.status_code == 200
            memory_id = remembered.json()["id"]

            first = client.post(
                "/query",
                json={"text": "user feedback hot memory", "namespace": "tenant:fb", "top_k": 1},
            )
            assert first.status_code == 200
            before = mind.store.get(memory_id)
            assert before is not None

            mismatch = client.post(
                "/feedback",
                json={"id": memory_id, "namespace": "tenant:other", "useful": True},
            )
            assert mismatch.status_code == 404

            response = client.post(
                "/feedback",
                json={
                    "id": memory_id,
                    "namespace": "tenant:fb",
                    "useful": True,
                    "strength": 0.75,
                    "query": "user feedback hot memory",
                    "reason": "accepted by agent",
                },
            )
            assert response.status_code == 200
            payload = response.json()
            assert payload["ok"] is True
            assert payload["id"] == memory_id
            assert payload["namespace"] == "tenant:fb"
            assert payload["priority"] > before.priority
            assert payload["access_count"] >= before.access_count + 1
            assert payload["cache_invalidated"] >= 1

            event = mind.audit_events(namespace="tenant:fb", action="feedback", limit=1)[0]
            assert event.memory_id == memory_id
            assert event.metadata["useful"] is True
            assert event.metadata["reason"] == "accepted by agent"
            assert event.metadata["query"] == "user feedback hot memory"
    finally:
        mind.close()


def test_fastapi_feedback_batch_updates_once_and_invalidates_cache(tmp_path, monkeypatch):
    monkeypatch.setenv("WAVEMIND_CACHE_CAPACITY", "8")
    monkeypatch.delenv("WAVEMIND_REDIS_URL", raising=False)

    mind = WaveMind(
        db_path=tmp_path / "api-feedback-batch.sqlite3",
        width=16,
        height=16,
        layers=1,
        encoder=HashingTextEncoder(vector_dim=64),
        audit_queries=True,
    )
    try:
        with TestClient(create_app(mind=mind)) as client:
            first = client.post(
                "/remember",
                json={"text": "batch useful answer memory", "namespace": "tenant:batch"},
            )
            second = client.post(
                "/remember",
                json={"text": "batch rejected stale memory", "namespace": "tenant:batch"},
            )
            assert first.status_code == 200
            assert second.status_code == 200
            first_id = first.json()["id"]
            second_id = second.json()["id"]

            cached = client.post(
                "/query",
                json={"text": "batch useful answer", "namespace": "tenant:batch", "top_k": 1},
            )
            assert cached.status_code == 200

            response = client.post(
                "/feedback/batch",
                json={
                    "namespace": "tenant:batch",
                    "items": [
                        {
                            "id": first_id,
                            "useful": True,
                            "strength": 0.5,
                            "query": "batch useful answer",
                            "reason": "accepted",
                        },
                        {
                            "id": second_id,
                            "useful": False,
                            "strength": 0.25,
                            "query": "batch stale answer",
                            "reason": "rejected",
                        },
                        {"id": first_id, "namespace": "wrong", "useful": True},
                    ],
                },
            )
            assert response.status_code == 200
            payload = response.json()
            assert payload["ok"] is False
            assert payload["accepted"] == 2
            assert payload["rejected"] == 1
            assert payload["cache_invalidated"] >= 1
            assert [item["ok"] for item in payload["results"]].count(True) == 2
            assert [item["ok"] for item in payload["results"]].count(False) == 1
            assert mind.store.get(first_id).priority > 1.0
            assert mind.store.get(second_id).priority < 1.0
            assert len(mind.audit_events(namespace="tenant:batch", action="feedback", limit=4)) == 2
    finally:
        mind.close()


def test_fastapi_consolidate_creates_durable_concept_memory(tmp_path):
    mind = WaveMind(
        db_path=tmp_path / "api-consolidate.sqlite3",
        width=16,
        height=16,
        layers=1,
        encoder=ConsolidationEncoder(),
        graph_weight=1.0,
        graph_steps=2,
        graph_expand_k=10,
        rerank_k=10,
        score_threshold=0.0,
    )
    try:
        with TestClient(create_app(mind=mind)) as client:
            first = client.post(
                "/remember",
                json={
                    "text": "User likes Rust systems programming",
                    "namespace": "agent",
                    "tags": ["systems"],
                },
            )
            second = client.post(
                "/remember",
                json={
                    "text": "User studies compiler systems internals",
                    "namespace": "agent",
                    "tags": ["systems"],
                },
            )
            client.post(
                "/remember",
                json={
                    "text": "User cooks pasta on weekends",
                    "namespace": "agent",
                    "tags": ["cooking"],
                },
            )

            response = client.post(
                "/consolidate",
                json={
                    "namespace": "agent",
                    "seed_text": "Rust compiler systems",
                    "min_energy": 0.01,
                },
            )

            assert response.status_code == 200
            concepts = response.json()["concepts"]
            assert len(concepts) == 1
            concept = concepts[0]
            assert concept["namespace"] == "agent"
            assert concept["text"].startswith("Consolidated memory:")
            assert concept["metadata"]["source"] == "wavemind_consolidation"
            assert set(concept["metadata"]["memory_ids"]) == {
                first.json()["id"],
                second.json()["id"],
            }

            query = client.post(
                "/query",
                json={
                    "text": "systems programming",
                    "namespace": "agent",
                    "tags": ["concept"],
                    "top_k": 1,
                },
            )
            assert query.status_code == 200
            assert query.json()["results"][0]["id"] == concept["id"]

            duplicate = client.post(
                "/consolidate",
                json={
                    "namespace": "agent",
                    "seed_text": "Rust compiler systems",
                    "min_energy": 0.01,
                },
            )
            assert duplicate.status_code == 200
            assert duplicate.json()["concepts"] == []
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


def test_fastapi_cache_prewarm_requires_enabled_cache(tmp_path, monkeypatch):
    monkeypatch.delenv("WAVEMIND_CACHE_CAPACITY", raising=False)
    monkeypatch.delenv("WAVEMIND_REDIS_URL", raising=False)
    mind = WaveMind(
        db_path=tmp_path / "api-cache-disabled.sqlite3",
        width=16,
        height=16,
        layers=1,
        encoder=HashingTextEncoder(vector_dim=64),
        audit_queries=True,
    )
    try:
        with TestClient(create_app(mind=mind)) as client:
            response = client.post("/cache/prewarm", json={})

            assert response.status_code == 400
            assert "Cache is disabled" in response.json()["detail"]
    finally:
        mind.close()


def test_fastapi_cache_prewarm_uses_query_audit_and_exposes_metrics(tmp_path, monkeypatch):
    monkeypatch.delenv("WAVEMIND_REDIS_URL", raising=False)
    monkeypatch.setenv("WAVEMIND_CACHE_CAPACITY", "8")
    monkeypatch.setenv("WAVEMIND_CACHE_TTL_SECONDS", "60")
    mind = WaveMind(
        db_path=tmp_path / "api-cache.sqlite3",
        width=16,
        height=16,
        layers=1,
        encoder=HashingTextEncoder(vector_dim=64),
        audit_queries=True,
    )
    try:
        mind.remember("cached audit driven memory", namespace="tenant:cache")
        mind.query("audit driven", namespace="tenant:cache", top_k=1)
        mind.query("audit driven", namespace="tenant:cache", top_k=1)

        with TestClient(create_app(mind=mind)) as client:
            report = client.post(
                "/cache/prewarm",
                json={
                    "namespace": "tenant:cache",
                    "min_frequency": 2,
                    "top_k": 1,
                },
            )
            assert report.status_code == 200
            payload = report.json()
            assert payload["ok"] is True
            assert payload["warmed"] == 1

            query = client.post(
                "/query",
                json={
                    "text": "audit driven",
                    "namespace": "tenant:cache",
                    "top_k": 1,
                },
            )
            assert query.status_code == 200
            assert query.json()["results"][0]["text"] == "cached audit driven memory"

            metrics = client.get("/metrics")
            assert metrics.status_code == 200
            assert "wavemind_cache_hits_total 1" in metrics.text
            assert "wavemind_cache_size 1" in metrics.text
    finally:
        mind.close()


def test_fastapi_query_vector_cache_reuses_encoder_output(tmp_path, monkeypatch):
    monkeypatch.delenv("WAVEMIND_REDIS_URL", raising=False)
    monkeypatch.delenv("WAVEMIND_CACHE_CAPACITY", raising=False)
    monkeypatch.delenv("WAVEMIND_VECTOR_CACHE_REDIS_URL", raising=False)
    monkeypatch.setenv("WAVEMIND_VECTOR_CACHE_CAPACITY", "8")
    monkeypatch.setenv("WAVEMIND_VECTOR_CACHE_TTL_SECONDS", "60")
    encoder = CountingEncoder()
    mind = WaveMind(
        db_path=tmp_path / "api-query-vector-cache.sqlite3",
        width=16,
        height=16,
        layers=1,
        encoder=encoder,
    )
    try:
        mind.remember("budget recall should use cached query vectors", namespace="tenant:qvec")
        encoder.calls = 0
        with TestClient(create_app(mind=mind)) as client:
            for _ in range(2):
                response = client.post(
                    "/query",
                    json={"text": "budget recall", "namespace": "tenant:qvec", "top_k": 1},
                )
                assert response.status_code == 200
                assert response.json()["results"][0]["text"] == (
                    "budget recall should use cached query vectors"
                )

            metrics = client.get("/metrics")
            assert encoder.calls == 1
            assert "wavemind_vector_cache_hits_total 1" in metrics.text
            assert "wavemind_vector_cache_misses_total 1" in metrics.text
    finally:
        mind.close()


def test_fastapi_query_batch_uses_shared_query_path_and_vector_cache(tmp_path, monkeypatch):
    monkeypatch.delenv("WAVEMIND_REDIS_URL", raising=False)
    monkeypatch.delenv("WAVEMIND_CACHE_CAPACITY", raising=False)
    monkeypatch.delenv("WAVEMIND_VECTOR_CACHE_REDIS_URL", raising=False)
    monkeypatch.setenv("WAVEMIND_VECTOR_CACHE_CAPACITY", "8")
    monkeypatch.setenv("WAVEMIND_VECTOR_CACHE_TTL_SECONDS", "60")
    monkeypatch.setenv("WAVEMIND_QUERY_BATCH_MAX_ITEMS", "4")
    encoder = CountingEncoder()
    mind = WaveMind(
        db_path=tmp_path / "api-query-batch.sqlite3",
        width=16,
        height=16,
        layers=1,
        encoder=encoder,
    )
    try:
        mind.remember("budget recall batch memory", namespace="tenant:batch")
        mind.remember("risk recall batch memory", namespace="tenant:batch")
        encoder.calls = 0
        with TestClient(create_app(mind=mind)) as client:
            response = client.post(
                "/query/batch",
                json={
                    "queries": [
                        {"text": "budget recall", "namespace": "tenant:batch", "top_k": 1},
                        {"text": "budget recall", "namespace": "tenant:batch", "top_k": 1},
                        {"text": "risk recall", "namespace": "tenant:batch", "top_k": 1},
                    ]
                },
            )
            assert response.status_code == 200
            payload = response.json()
            assert payload["count"] == 3
            assert [item["index"] for item in payload["items"]] == [0, 1, 2]
            assert payload["items"][0]["results"][0]["text"] == "budget recall batch memory"
            assert payload["items"][1]["results"][0]["text"] == "budget recall batch memory"
            assert payload["items"][2]["results"][0]["text"] == "risk recall batch memory"
            assert encoder.calls == 2

            empty = client.post("/query/batch", json={"queries": []})
            assert empty.status_code == 400

            oversized = client.post(
                "/query/batch",
                json={
                    "queries": [
                        {"text": f"budget recall {index}", "namespace": "tenant:batch"}
                        for index in range(5)
                    ]
                },
            )
            assert oversized.status_code == 413

            metrics = client.get("/metrics")
            assert metrics.status_code == 200
            assert "wavemind_api_query_batch_requests_total 1" in metrics.text
            assert "wavemind_vector_cache_hits_total 1" in metrics.text
            assert "wavemind_vector_cache_misses_total 2" in metrics.text
    finally:
        mind.close()


def test_fastapi_memory_os_runs_adaptive_worker(tmp_path, monkeypatch):
    monkeypatch.delenv("WAVEMIND_REDIS_URL", raising=False)
    monkeypatch.setenv("WAVEMIND_CACHE_CAPACITY", "8")
    monkeypatch.setenv("WAVEMIND_CACHE_TTL_SECONDS", "60")
    mind = WaveMind(
        db_path=tmp_path / "api-memory-os.sqlite3",
        width=16,
        height=16,
        layers=1,
        encoder=HashingTextEncoder(vector_dim=64),
        audit_queries=True,
    )
    try:
        mind.remember("memory os should prewarm hot budget recall", namespace="tenant:os")
        mind.remember("memory os should demote unused cold note", namespace="tenant:os")
        mind.query("budget recall", namespace="tenant:os", top_k=1)
        mind.query("budget recall", namespace="tenant:os", top_k=1)

        with TestClient(create_app(mind=mind)) as client:
            response = client.post(
                "/memory-os/run",
                json={
                    "namespace": "tenant:os",
                    "min_frequency": 2,
                    "top_k": 1,
                    "consolidate_steps": 0,
                    "consolidate_concepts": False,
                    "forgetting_min_age_seconds": 0,
                    "forgetting_priority_decay": 0.1,
                    "target_memories": 2000000,
                    "namespace_count": 4096,
                    "node_count": 2,
                    "deployment": "production",
                    "multimodal": True,
                },
            )
            assert response.status_code == 200
            payload = response.json()
            assert payload["ok"] is True
            assert payload["cache_enabled"] is True
            assert payload["hot_queries"][0]["query"] == "budget recall"
            assert payload["prewarm"]["warmed"] == 1
            assert payload["predictive_prefetch"]["generated_queries"] >= 1
            assert payload["predictive_prefetch"]["warmed"] >= 1
            assert payload["priority_predictions"] >= 1
            assert payload["priority_boost_total"] > 0.0
            assert payload["forgetting_demotions"] >= 1
            assert payload["forgetting_decay_total"] > 0.0
            assert "predict_priority" in payload["actions"]
            assert "predictive_prefetch" in payload["actions"]
            assert "adaptive_forgetting" in payload["actions"]
            assert "advise_architecture" in payload["actions"]
            advice = payload["architecture_advice"]
            recommendation_ids = {item["id"] for item in advice["recommendations"]}
            assert advice["status"] == "architecture_required"
            assert "namespace-sharding" in recommendation_ids
            assert "production-controls" in recommendation_ids
            suggestion_ids = {item["id"] for item in payload["suggestions"]}
            assert "predictive-prefetch-active" in suggestion_ids
            assert "priority-learning-active" in suggestion_ids
            assert "adaptive-forgetting-active" in suggestion_ids
            assert "architecture:namespace-sharding" in suggestion_ids
            assert any(
                item["evidence"].get("namespace") == "tenant:os"
                for item in payload["suggestions"]
            )

            query = client.post(
                "/query",
                json={"text": "budget recall", "namespace": "tenant:os", "top_k": 1},
            )
            assert query.status_code == 200
            assert query.json()["results"][0]["text"] == "memory os should prewarm hot budget recall"

            metrics = client.get("/metrics")
            assert "wavemind_api_memory_os_requests_total 1" in metrics.text
    finally:
        mind.close()


def test_fastapi_memory_os_required_lock_skips_when_busy(tmp_path, monkeypatch):
    class FakeRedisClient:
        values = {"wm:lock:tenant:os": "other-worker"}

        @classmethod
        def from_url(cls, url, decode_responses=True):
            assert url == "redis://memory-os-lock.test/0"
            assert decode_responses is True
            return cls()

        def get(self, key):
            return self.values.get(key)

        def set(self, key, value, ex=None, nx=False):
            if nx and key in self.values:
                return False
            self.values[key] = value
            return True

        def scan_iter(self, match=None):
            return iter(())

        def delete(self, *keys):
            for key in keys:
                self.values.pop(key, None)

    fake_redis_module = types.SimpleNamespace(Redis=FakeRedisClient)
    monkeypatch.setitem(sys.modules, "redis", fake_redis_module)
    monkeypatch.setenv("WAVEMIND_MEMORY_OS_LOCK_REDIS_URL", "redis://memory-os-lock.test/0")
    monkeypatch.delenv("WAVEMIND_REDIS_URL", raising=False)
    monkeypatch.delenv("WAVEMIND_CACHE_CAPACITY", raising=False)

    mind = WaveMind(
        db_path=tmp_path / "api-memory-os-lock.sqlite3",
        width=16,
        height=16,
        layers=1,
        encoder=HashingTextEncoder(vector_dim=64),
        audit_queries=True,
    )
    try:
        id = mind.remember("memory os lock should prevent mutation", namespace="tenant:os", priority=1.0)
        mind.query("prevent mutation", namespace="tenant:os", top_k=1)
        mind.query("prevent mutation", namespace="tenant:os", top_k=1)
        before = mind.store.get(id).priority

        with TestClient(create_app(mind=mind)) as client:
            response = client.post(
                "/memory-os/run",
                json={
                    "namespace": "tenant:os",
                    "lock_required": True,
                    "lock_prefix": "wm:lock",
                    "consolidate_steps": 0,
                    "consolidate_concepts": False,
                    "priority_boost_per_hit": 1.0,
                },
            )
            assert response.status_code == 200
            payload = response.json()
            assert payload["ok"] is False
            assert payload["lock"]["required"] is True
            assert payload["lock"]["acquired"] is False
            assert payload["lock"]["reason"] == "lock_already_held"
            assert payload["actions"] == ["lock_skipped"]
            assert mind.store.get(id).priority == before
            assert FakeRedisClient.values["wm:lock:tenant:os"] == "other-worker"
    finally:
        mind.close()


def test_fastapi_memory_os_plan_is_read_only_scheduler_preflight(tmp_path, monkeypatch):
    monkeypatch.delenv("WAVEMIND_REDIS_URL", raising=False)
    monkeypatch.setenv("WAVEMIND_CACHE_CAPACITY", "8")
    mind = WaveMind(
        db_path=tmp_path / "api-memory-os-plan.sqlite3",
        width=16,
        height=16,
        layers=1,
        encoder=HashingTextEncoder(vector_dim=64),
        audit_queries=True,
    )
    try:
        mind.remember("memory os plan should prewarm budget recall", namespace="tenant:os")
        mind.remember("memory os plan cold note stays untouched", namespace="tenant:os")
        mind.query("budget recall", namespace="tenant:os", top_k=1)
        mind.query("budget recall", namespace="tenant:os", top_k=1)
        before = mind.stats(namespace="tenant:os")

        with TestClient(create_app(mind=mind)) as client:
            response = client.post(
                "/memory-os/plan",
                json={
                    "namespace": "tenant:os",
                    "min_frequency": 2,
                    "top_k": 1,
                    "target_memories": 2000000,
                    "namespace_count": 4096,
                    "node_count": 2,
                    "deployment": "production",
                    "cache_mode": "auto",
                    "target_qps": 500,
                    "observed_p99_ms": 150,
                    "multimodal": True,
                },
            )
            assert response.status_code == 200
            payload = response.json()
            task_by_id = {task["id"]: task for task in payload["tasks"]}
            execution = payload["execution_plan"]
            step_by_id = {
                step["task_id"]: step for step in execution["steps"]
            }

            assert payload["status"] == "architecture_required"
            assert payload["effective_cache_mode"] == "redis"
            assert payload["hot_query_count"] == 1
            assert payload["worker_count"] >= 5
            assert payload["policy_manifest"]["status"] == "architecture_required"
            assert payload["policy_history"]["trend"] == "first_run"
            assert payload["policy_escalation_ids"] == []
            assert payload["policy_auto_adjustments"] == []
            assert "memory-os" in payload["enabled_task_ids"]
            assert "cache-prewarm" in payload["enabled_task_ids"]
            assert task_by_id["memory-os"]["requires_distributed_lock"] is True
            assert "--redis-url $WAVEMIND_REDIS_URL" in task_by_id["memory-os"]["command"]
            assert "--lock-required" in task_by_id["memory-os"]["command"]
            assert execution["status"] == "architecture_required"
            assert execution["safe_to_run"] is True
            assert execution["requires_shared_cache"] is True
            assert execution["requires_distributed_lock"] is True
            assert execution["blocked_task_ids"] == []
            assert "distributed-lock-required" in execution["warnings"]
            assert set(execution["enabled_task_ids"]) == set(payload["enabled_task_ids"])
            assert step_by_id["memory-os"]["run_scope"] == "cluster-singleton"
            assert step_by_id["memory-os"]["state_mutation"] is True
            assert step_by_id["memory-os"]["idempotency_key"] == (
                "wavemind:memory-os:tenant:os:memory-os"
            )
            assert "WAVEMIND_REDIS_URL" in step_by_id["memory-os"]["required_environment"]
            assert (
                "WAVEMIND_MEMORY_OS_LOCK_REDIS_URL"
                in step_by_id["memory-os"]["required_environment"]
            )
            assert step_by_id["cache-prewarm"]["run_scope"] == "worker-pool"
            assert step_by_id["cache-prewarm"]["can_run_on_all_workers"] is True
            assert step_by_id["cache-prewarm"]["state_mutation"] is False

            after = mind.stats(namespace="tenant:os")
            assert before["active_memories"] == after["active_memories"]
            assert mind.audit_events(namespace="tenant:os", action="memory_os", limit=1) == []

            metrics = client.get("/metrics")
            assert "wavemind_api_memory_os_plan_requests_total 1" in metrics.text
    finally:
        mind.close()


def test_fastapi_cache_can_use_redis_from_env(tmp_path, monkeypatch):
    class FakeRedisClient:
        values = {}

        @classmethod
        def from_url(cls, url, decode_responses=True):
            assert url == "redis://cache.test/0"
            assert decode_responses is True
            return cls()

        def get(self, key):
            return self.values.get(key)

        def set(self, key, value, ex=None):
            self.values[key] = value

        def scan_iter(self, match=None):
            prefix = (match or "").rstrip("*")
            for key in list(self.values):
                if key.startswith(prefix):
                    yield key

        def delete(self, *keys):
            for key in keys:
                self.values.pop(key, None)

    fake_redis_module = types.SimpleNamespace(Redis=FakeRedisClient)
    monkeypatch.setitem(sys.modules, "redis", fake_redis_module)
    monkeypatch.setenv("WAVEMIND_REDIS_URL", "redis://cache.test/0")
    monkeypatch.setenv("WAVEMIND_REDIS_PREFIX", "wm:test")
    monkeypatch.delenv("WAVEMIND_CACHE_CAPACITY", raising=False)

    mind = WaveMind(
        db_path=tmp_path / "api-redis-cache.sqlite3",
        width=16,
        height=16,
        layers=1,
        encoder=HashingTextEncoder(vector_dim=64),
        audit_queries=True,
    )
    try:
        mind.remember("redis warmed memory", namespace="tenant:redis")
        mind.query("warmed memory", namespace="tenant:redis", top_k=1)

        with TestClient(create_app(mind=mind)) as client:
            report = client.post(
                "/cache/prewarm",
                json={"namespace": "tenant:redis", "top_k": 1},
            )
            assert report.status_code == 200
            assert report.json()["warmed"] == 1

            query = client.post(
                "/query",
                json={"text": "warmed memory", "namespace": "tenant:redis", "top_k": 1},
            )
            assert query.status_code == 200
            assert query.json()["results"][0]["text"] == "redis warmed memory"
            assert any(key.startswith("wm:test:tenant:redis:") for key in FakeRedisClient.values)

            replacement = client.post(
                "/remember",
                json={"text": "redis replacement memory", "namespace": "tenant:redis"},
            )
            assert replacement.status_code == 200
            assert not any(key.startswith("wm:test:tenant:redis:") for key in FakeRedisClient.values)

            refreshed = client.post(
                "/query",
                json={"text": "replacement memory", "namespace": "tenant:redis", "top_k": 1},
            )
            assert refreshed.status_code == 200
            assert refreshed.json()["results"][0]["id"] == replacement.json()["id"]
            assert any(key.startswith("wm:test:tenant:redis:") for key in FakeRedisClient.values)

            deleted = client.request(
                "DELETE",
                "/forget",
                json={"id": replacement.json()["id"], "namespace": "tenant:redis"},
            )
            assert deleted.status_code == 200
            assert deleted.json()["deleted"] == 1
            assert not any(key.startswith("wm:test:tenant:redis:") for key in FakeRedisClient.values)
    finally:
        mind.close()


def test_fastapi_admin_can_export_namespace_memories(tmp_path):
    mind = WaveMind(
        db_path=tmp_path / "api-export.sqlite3",
        width=16,
        height=16,
        layers=1,
        encoder=HashingTextEncoder(vector_dim=64),
    )
    try:
        memory_id = mind.remember(
            "exportable production memory",
            namespace="tenant:export",
            tags=["ops"],
            metadata={"source": "api-test"},
            priority=4.0,
        )
        mind.remember("other tenant memory", namespace="tenant:other")

        with TestClient(create_app(mind=mind)) as client:
            response = client.post(
                "/memories/export",
                json={"namespace": "tenant:export", "tags": ["ops"]},
            )

            assert response.status_code == 200
            payload = response.json()
            assert len(payload["records"]) == 1
            record = payload["records"][0]
            assert record["id"] == memory_id
            assert record["text"] == "exportable production memory"
            assert record["namespace"] == "tenant:export"
            assert record["tags"] == ["ops"]
            assert record["metadata"] == {"source": "api-test"}
            assert record["priority"] == 4.0
    finally:
        mind.close()


def test_fastapi_admin_can_write_and_export_tombstones(tmp_path):
    mind = WaveMind(
        db_path=tmp_path / "api-tombstone.sqlite3",
        width=16,
        height=16,
        layers=1,
        encoder=HashingTextEncoder(vector_dim=64),
    )
    try:
        with TestClient(create_app(mind=mind)) as client:
            tombstone = client.post(
                "/memories/tombstone",
                json={
                    "namespace": "tenant:tombstone",
                    "record_keys": ["record-key-1"],
                    "texts": ["deleted memory"],
                },
            )
            assert tombstone.status_code == 200
            assert tombstone.json()["id"] >= 1

            exported = client.post(
                "/memories/export",
                json={
                    "namespace": "tenant:tombstone",
                    "include_tombstones": True,
                },
            )
            assert exported.status_code == 200
            payload = exported.json()
            assert payload["records"] == []
            assert payload["tombstones"][0]["record_keys"] == ["record-key-1"]
            assert payload["tombstones"][0]["texts"] == ["deleted memory"]

            bad = client.post(
                "/memories/tombstone",
                json={"namespace": "tenant:tombstone"},
            )
            assert bad.status_code == 400
    finally:
        mind.close()


def test_fastapi_replication_delta_export_import_between_service_regions(tmp_path):
    region_a = ReplicatedWaveMind(
        root_path=tmp_path / "api-region-a",
        nodes=["a1", "a2", "a3"],
        replication_factor=3,
        width=16,
        height=16,
        layers=1,
        encoder=HashingTextEncoder(vector_dim=64),
    )
    region_b = ReplicatedWaveMind(
        root_path=tmp_path / "api-region-b",
        nodes=["b1", "b2", "b3"],
        replication_factor=3,
        width=16,
        height=16,
        layers=1,
        encoder=HashingTextEncoder(vector_dim=64),
    )
    try:
        namespace = "tenant:http-delta"
        with TestClient(create_app(mind=region_a)) as client_a, TestClient(create_app(mind=region_b)) as client_b:
            remembered = client_a.post(
                "/remember",
                json={"text": "service region delta keeps active active memory", "namespace": namespace},
            )
            assert remembered.status_code == 200
            assert remembered.json()["id"] >= 1

            exported = client_a.post(
                "/namespace-delta/export",
                json={"namespace": namespace},
            )
            assert exported.status_code == 200
            delta = exported.json()
            assert delta["namespace"] == namespace
            assert len(delta["records"]) == 1
            assert delta["cursor"] is not None

            imported = client_b.post(
                "/namespace-delta/import",
                json={"delta": delta, "namespace": namespace},
            )
            assert imported.status_code == 200
            imported_payload = imported.json()
            assert imported_payload["ok"] is True
            assert imported_payload["imported_records"] == 3

            query = client_b.post(
                "/query",
                json={"text": "active active memory", "namespace": namespace, "top_k": 1},
            )
            assert query.status_code == 200
            assert query.json()["results"][0]["text"] == "service region delta keeps active active memory"

            deleted = client_a.request(
                "DELETE",
                "/forget",
                json={"text": "service region delta keeps active active memory", "namespace": namespace},
            )
            assert deleted.status_code == 200
            assert deleted.json()["deleted"] == 1

            tombstone_delta = client_a.post(
                "/namespace-delta/export",
                json={"namespace": namespace, "since": delta["cursor"]},
            )
            assert tombstone_delta.status_code == 200
            assert tombstone_delta.json()["tombstones"]

            tombstone_import = client_b.post(
                "/namespace-delta/import",
                json={"delta": tombstone_delta.json(), "namespace": namespace},
            )
            assert tombstone_import.status_code == 200
            assert tombstone_import.json()["imported_tombstones"] >= 1
            assert region_b.query("active active memory", namespace=namespace, top_k=1) == []
    finally:
        region_a.close()
        region_b.close()


def test_fastapi_replication_delta_requires_replicated_backend(tmp_path):
    mind = WaveMind(
        db_path=tmp_path / "api-no-delta.sqlite3",
        width=16,
        height=16,
        layers=1,
        encoder=HashingTextEncoder(vector_dim=64),
    )
    try:
        with TestClient(create_app(mind=mind)) as client:
            response = client.post(
                "/namespace-delta/export",
                json={"namespace": "tenant:no-delta"},
            )

            assert response.status_code == 501
            assert "export_namespace_delta" in response.json()["detail"]
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


def test_fastapi_serializes_operations_by_default_and_allows_opt_out(monkeypatch):
    monkeypatch.delenv("WAVEMIND_API_SERIALIZE_OPERATIONS", raising=False)
    locked_mind = WaveMind(
        db_path=None,
        width=16,
        height=16,
        layers=1,
        encoder=HashingTextEncoder(vector_dim=16),
    )
    try:
        locked_app = create_app(mind=locked_mind)
        assert locked_app.state.operation_lock is not None
    finally:
        locked_mind.close()

    monkeypatch.setenv("WAVEMIND_API_SERIALIZE_OPERATIONS", "0")
    unlocked_mind = WaveMind(
        db_path=None,
        width=16,
        height=16,
        layers=1,
        encoder=HashingTextEncoder(vector_dim=16),
    )
    try:
        unlocked_app = create_app(mind=unlocked_mind)
        assert unlocked_app.state.operation_lock is None
    finally:
        unlocked_mind.close()


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


def test_fastapi_rate_limit_can_use_shared_redis_from_env(tmp_path, monkeypatch):
    class FakeRedisClient:
        values = {}
        expirations = {}

        @classmethod
        def from_url(cls, url, decode_responses=True):
            assert url == "redis://rate.test/0"
            assert decode_responses is True
            return cls()

        def incr(self, key):
            self.values[key] = int(self.values.get(key, 0)) + 1
            return self.values[key]

        def expire(self, key, seconds):
            self.expirations[key] = seconds
            return True

    fake_redis_module = types.SimpleNamespace(Redis=FakeRedisClient)
    monkeypatch.setitem(sys.modules, "redis", fake_redis_module)
    monkeypatch.delenv("WAVEMIND_READ_KEYS", raising=False)
    monkeypatch.delenv("WAVEMIND_WRITE_KEYS", raising=False)
    monkeypatch.delenv("WAVEMIND_ADMIN_KEYS", raising=False)
    monkeypatch.delenv("WAVEMIND_API_KEYS", raising=False)
    monkeypatch.setenv("WAVEMIND_RATE_LIMIT_PER_MINUTE", "2")
    monkeypatch.setenv("WAVEMIND_RATE_LIMIT_REDIS_URL", "redis://rate.test/0")
    monkeypatch.setenv("WAVEMIND_RATE_LIMIT_REDIS_PREFIX", "wm:rate")

    mind_a = WaveMind(
        db_path=tmp_path / "rate-a.sqlite3",
        width=16,
        height=16,
        layers=1,
        encoder=HashingTextEncoder(vector_dim=16),
    )
    mind_b = WaveMind(
        db_path=tmp_path / "rate-b.sqlite3",
        width=16,
        height=16,
        layers=1,
        encoder=HashingTextEncoder(vector_dim=16),
    )
    try:
        app_a = create_app(mind=mind_a)
        app_b = create_app(mind=mind_b)
        with TestClient(app_a) as client_a, TestClient(app_b) as client_b:
            assert client_a.get("/stats").status_code == 200
            assert client_b.get("/stats").status_code == 200
            limited = client_b.get("/stats")

            assert limited.status_code == 429
            assert limited.json()["detail"] == "Rate limit exceeded"
            assert len(FakeRedisClient.values) == 1
            assert next(iter(FakeRedisClient.values.values())) == 3
            assert next(iter(FakeRedisClient.expirations.values())) == 120

        stats_a = app_a.state.rate_limiter.stats()
        stats_b = app_b.state.rate_limiter.stats()
        assert stats_a.shared is True
        assert stats_b.shared is True
        assert stats_a.backend == "redis"
        assert stats_b.limited == 1
    finally:
        mind_a.close()
        mind_b.close()
