import json
import os
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest


def test_streaming_load_numpy_smoke_and_slo():
    from benchmarks import production_streaming_load_benchmark as benchmark

    run_streaming_load = benchmark.run_streaming_load

    payload = run_streaming_load(
        sizes=[256],
        dim=16,
        query_count=8,
        top_k=3,
        seed=7,
        noise=0.01,
        batch_size=64,
        engines=["numpy-streaming"],
    )

    assert payload["scenario"]["name"] == "production_streaming_load_profile"
    assert payload["scenario"]["default_target_sizes"] == [10_000_000, 50_000_000]
    assert payload["scenario"]["target_recall_definition"].startswith("source id")
    row = payload["results"][0]["results"][0]
    assert row["engine"] == "WaveMind numpy-streaming"
    assert row["target_recall_at_k"] == 1.0
    assert row["recall_at_k"] == row["target_recall_at_k"]
    assert row["queries"] == 8
    assert row["slo_status"] in {"pass", "scale_required", "fail"}
    assert row["compute_cost_per_1m_queries_usd"] > 0


def test_streaming_load_skips_unconfigured_service_engines(monkeypatch):
    from benchmarks.production_streaming_load_benchmark import run_streaming_load

    monkeypatch.delenv("WAVEMIND_FAISS_PATH", raising=False)
    monkeypatch.delenv("WAVEMIND_FAISS_IVFPQ_PATH", raising=False)
    monkeypatch.delenv("WAVEMIND_QDRANT_URL", raising=False)
    monkeypatch.delenv("WAVEMIND_PGVECTOR_DSN", raising=False)

    payload = run_streaming_load(
        sizes=[64],
        dim=8,
        query_count=4,
        top_k=2,
        seed=3,
        noise=0.01,
        batch_size=32,
        engines=["faiss-persisted", "faiss-ivfpq-persisted", "qdrant-service", "pgvector-service"],
    )

    rows = {row["engine"]: row for row in payload["results"][0]["results"]}
    assert rows["WaveMind faiss-persisted streaming"]["skipped"] is True
    assert "WAVEMIND_FAISS_PATH" in rows["WaveMind faiss-persisted streaming"]["reason"]
    assert rows["WaveMind faiss-ivfpq-persisted streaming"]["skipped"] is True
    assert "WAVEMIND_FAISS_IVFPQ_PATH" in rows["WaveMind faiss-ivfpq-persisted streaming"]["reason"]
    assert rows["Qdrant service streaming"]["skipped"] is True
    assert "WAVEMIND_QDRANT_URL" in rows["Qdrant service streaming"]["reason"]
    assert rows["WaveMind pgvector streaming"]["skipped"] is True
    assert "WAVEMIND_PGVECTOR_DSN" in rows["WaveMind pgvector streaming"]["reason"]
    assert rows["WaveMind faiss-persisted streaming"]["slo_status"] == "skipped"
    assert rows["WaveMind faiss-ivfpq-persisted streaming"]["cost_status"] == "skipped"
    assert rows["Qdrant service streaming"]["cost_status"] == "skipped"
    assert rows["WaveMind pgvector streaming"]["slo_status"] == "skipped"


def test_streaming_load_qdrant_chunks_large_upsert_batches():
    import concurrent.futures

    from benchmarks.production_streaming_load_benchmark import (
        QdrantShardTarget,
        _chunks,
        _merge_scored_hits,
        _iter_qdrant_shard_point_chunks,
        _qdrant_shard_index,
        _iter_qdrant_point_chunks,
        _upsert_qdrant_point_chunks,
        _upsert_qdrant_points,
        _upsert_qdrant_shards,
    )

    assert list(_chunks([1, 2, 3, 4, 5], 2)) == [[1, 2], [3, 4], [5]]
    with pytest.raises(ValueError, match="chunk size must be positive"):
        list(_chunks([1], 0))
    assert [_qdrant_shard_index(point_id, 3) for point_id in range(1, 8)] == [0, 1, 2, 0, 1, 2, 0]
    with pytest.raises(ValueError, match="shard_count must be positive"):
        _qdrant_shard_index(1, 0)

    class Point:
        def __init__(self, *, id, vector):
            self.id = id
            self.vector = vector

    shard_chunks = list(
        _iter_qdrant_shard_point_chunks(
            np.arange(1, 8, dtype=np.int64),
            np.arange(14, dtype=np.float32).reshape(7, 2),
            shard_index=1,
            shard_count=3,
            point_type=Point,
            chunk_size=2,
        )
    )
    assert [[point.id for point in chunk] for chunk in shard_chunks] == [[2, 5]]
    with pytest.raises(ValueError, match="chunk size must be positive"):
        list(
            _iter_qdrant_shard_point_chunks(
                np.array([1]),
                np.array([[1.0]], dtype=np.float32),
                shard_index=0,
                shard_count=1,
                point_type=Point,
                chunk_size=0,
            )
        )

    class Hit:
        def __init__(self, point_id, score):
            self.id = point_id
            self.score = score

    assert _merge_scored_hits(
        [
            [Hit(1, 0.7), Hit(2, 0.6)],
            [Hit(3, 0.95), Hit(4, 0.5)],
        ],
        top_k=3,
    ) == [3, 1, 2]

    class Client:
        def __init__(self):
            self.calls = []

        def upsert(self, *, collection_name, points):
            self.calls.append((collection_name, list(points)))

    clients = [Client(), Client()]
    targets = [
        QdrantShardTarget(0, "http://shard-0", "memories_s000"),
        QdrantShardTarget(1, "http://shard-1", "memories_s001"),
    ]
    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
        inserted = _upsert_qdrant_shards(
            executor=executor,
            clients=clients,
            targets=targets,
            point_chunks_by_shard={
                0: iter([[1, 3], [5]]),
                1: iter([[2, 4]]),
            },
        )

    assert inserted == 5
    assert clients[0].calls == [
        ("memories_s000", [1, 3]),
        ("memories_s000", [5]),
    ]
    assert clients[1].calls == [("memories_s001", [2, 4])]

    client = Client()
    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
        inserted = _upsert_qdrant_points(
            executor=executor,
            client=client,
            collection_name="memories",
            points=[1, 2, 3, 4, 5],
            upsert_batch_size=2,
        )

    assert inserted == 5
    assert sorted(client.calls) == [
        ("memories", [1, 2]),
        ("memories", [3, 4]),
        ("memories", [5]),
    ]

    class Point:
        def __init__(self, *, id, vector):
            self.id = id
            self.vector = vector

    chunks = list(
        _iter_qdrant_point_chunks(
            np.asarray([1, 2, 3, 4, 5]),
            np.asarray([[1.0], [2.0], [3.0], [4.0], [5.0]]),
            point_type=Point,
            chunk_size=2,
        )
    )
    assert [[point.id for point in chunk] for chunk in chunks] == [
        [1, 2],
        [3, 4],
        [5],
    ]
    client = Client()
    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
        inserted = _upsert_qdrant_point_chunks(
            executor=executor,
            client=client,
            collection_name="memories",
            point_chunks=iter(chunks),
            max_in_flight=2,
        )
    assert inserted == 5


def test_qdrant_index_readiness_waits_for_green_index(monkeypatch):
    from benchmarks import production_streaming_load_benchmark as benchmark

    states = [
        SimpleNamespace(
            points_count=100,
            indexed_vectors_count=80,
            status="yellow",
            optimizer_status="ok",
        ),
        SimpleNamespace(
            points_count=100,
            indexed_vectors_count=100,
            status="green",
            optimizer_status="ok",
        ),
    ]

    class FakeClient:
        def get_collection(self, *, collection_name):
            assert collection_name == "memories"
            return states.pop(0)

    monkeypatch.setattr(benchmark.time, "sleep", lambda _seconds: None)
    readiness = benchmark._wait_for_qdrant_index_ready(
        FakeClient(),
        "memories",
        expected_vectors=100,
        timeout_seconds=1.0,
        poll_interval_seconds=0.0,
        require_full_index=True,
    )

    assert readiness["ready"] is True
    assert readiness["points_count"] == 100
    assert readiness["indexed_vectors_count"] == 100
    assert readiness["attempts"] == 2
    assert readiness["require_full_index"] is True


def test_qdrant_index_readiness_can_observe_without_waiting():
    from benchmarks.production_streaming_load_benchmark import (
        _wait_for_qdrant_index_ready,
    )

    class FakeClient:
        def get_collection(self, *, collection_name):
            return SimpleNamespace(
                points_count=100,
                indexed_vectors_count=90,
                status="yellow",
                optimizer_status="ok",
            )

    readiness = _wait_for_qdrant_index_ready(
        FakeClient(),
        "memories",
        expected_vectors=100,
        timeout_seconds=0.0,
    )

    assert readiness["ready"] is False
    assert readiness["attempts"] == 1


def test_qdrant_index_readiness_allows_small_green_full_scan_collection():
    from benchmarks.production_streaming_load_benchmark import (
        _wait_for_qdrant_index_ready,
    )

    class FakeClient:
        def get_collection(self, *, collection_name):
            return SimpleNamespace(
                points_count=10_000,
                indexed_vectors_count=0,
                status="green",
                optimizer_status="ok",
            )

    readiness = _wait_for_qdrant_index_ready(
        FakeClient(),
        "small-memories",
        expected_vectors=10_000,
        timeout_seconds=1.0,
    )

    assert readiness["ready"] is True
    assert readiness["require_full_index"] is False


def test_qdrant_deferred_indexing_config_requires_higher_ingest_threshold(
    monkeypatch,
):
    from benchmarks.production_streaming_load_benchmark import (
        _qdrant_deferred_indexing_config_from_env,
    )

    monkeypatch.setenv("WAVEMIND_QDRANT_DEFER_INDEXING", "1")
    monkeypatch.setenv("WAVEMIND_QDRANT_DEFERRED_INDEXING_THRESHOLD_KB", "500000")
    monkeypatch.setenv("WAVEMIND_QDRANT_FINAL_INDEXING_THRESHOLD_KB", "20000")
    config = _qdrant_deferred_indexing_config_from_env()

    assert config == {
        "enabled": True,
        "deferred_threshold_kb": 500000,
        "final_threshold_kb": 20000,
    }

    monkeypatch.setenv("WAVEMIND_QDRANT_DEFERRED_INDEXING_THRESHOLD_KB", "10000")
    with pytest.raises(ValueError, match="must be greater"):
        _qdrant_deferred_indexing_config_from_env()


def test_streaming_load_qdrant_rejects_invalid_upsert_chunk_size(monkeypatch):
    from benchmarks.production_streaming_load_benchmark import run_streaming_load

    monkeypatch.setenv("WAVEMIND_QDRANT_URL", "http://127.0.0.1:6333")
    monkeypatch.setenv("WAVEMIND_QDRANT_UPSERT_BATCH_SIZE", "0")

    payload = run_streaming_load(
        sizes=[64],
        dim=8,
        query_count=4,
        top_k=2,
        seed=3,
        noise=0.01,
        batch_size=32,
        engines=["qdrant-service"],
    )

    row = payload["results"][0]["results"][0]
    assert row["engine"] == "Qdrant service streaming"
    assert row["skipped"] is True
    assert "WAVEMIND_QDRANT_UPSERT_BATCH_SIZE must be positive" in row["reason"]


def test_streaming_load_qdrant_sharded_requires_multiple_urls(monkeypatch):
    from benchmarks.production_streaming_load_benchmark import run_streaming_load

    monkeypatch.delenv("WAVEMIND_QDRANT_URLS", raising=False)
    monkeypatch.setenv("WAVEMIND_QDRANT_URL", "http://127.0.0.1:6333")

    payload = run_streaming_load(
        sizes=[64],
        dim=8,
        query_count=4,
        top_k=2,
        seed=3,
        noise=0.01,
        batch_size=32,
        engines=["qdrant-sharded-service"],
    )

    row = payload["results"][0]["results"][0]
    assert row["engine"] == "Qdrant sharded service streaming"
    assert row["skipped"] is True
    assert "WAVEMIND_QDRANT_URLS" in row["reason"]


def test_qdrant_complete_checkpoint_resume_skips_vector_regeneration(
    tmp_path,
    monkeypatch,
):
    from benchmarks import production_streaming_load_benchmark as benchmark

    class Model:
        def __init__(self, **kwargs):
            self.__dict__.update(kwargs)

    class FakeQdrantClient:
        init_kwargs = None
        query_kwargs = []
        update_kwargs = []

        def __init__(self, **kwargs):
            type(self).init_kwargs = kwargs
            self.closed = False

        def get_collection(self, *, collection_name):
            return SimpleNamespace(
                points_count=64,
                indexed_vectors_count=64,
                status="green",
                optimizer_status="ok",
            )

        def update_collection(self, **kwargs):
            type(self).update_kwargs.append(kwargs)
            return True

        def query_points(self, **kwargs):
            type(self).query_kwargs.append(kwargs)
            return SimpleNamespace(points=[SimpleNamespace(id=1, score=1.0)])

        def close(self):
            self.closed = True

    fake_models = SimpleNamespace(
        Distance=SimpleNamespace(COSINE="Cosine"),
        HnswConfigDiff=Model,
        OptimizersConfigDiff=Model,
        PointStruct=Model,
        QuantizationSearchParams=Model,
        ScalarQuantization=Model,
        ScalarQuantizationConfig=Model,
        ScalarType=SimpleNamespace(INT8="int8"),
        SearchParams=Model,
        VectorParams=Model,
    )
    monkeypatch.setitem(
        sys.modules,
        "qdrant_client",
        SimpleNamespace(QdrantClient=FakeQdrantClient),
    )
    monkeypatch.setitem(sys.modules, "qdrant_client.models", fake_models)

    checkpoint_path = tmp_path / "qdrant-complete.checkpoint.json"
    collection_name = "complete_resume"
    monkeypatch.setenv("WAVEMIND_QDRANT_URL", "http://127.0.0.1:6335")
    monkeypatch.setenv("WAVEMIND_QDRANT_COLLECTION", collection_name)
    monkeypatch.setenv("WAVEMIND_STREAMING_CHECKPOINT_PATH", str(checkpoint_path))
    monkeypatch.setenv("WAVEMIND_QDRANT_DEFER_INDEXING", "0")
    monkeypatch.setenv("WAVEMIND_QDRANT_PREFER_GRPC", "1")
    monkeypatch.setenv("WAVEMIND_QDRANT_GRPC_PORT", "6336")
    monkeypatch.setenv("WAVEMIND_QDRANT_QUERY_TIMEOUT_SECONDS", "300")
    monkeypatch.setenv("WAVEMIND_QDRANT_HNSW_ON_DISK", "0")
    monkeypatch.setenv("WAVEMIND_QDRANT_SCALAR_QUANTIZATION", "1")
    monkeypatch.setenv("WAVEMIND_QDRANT_SCALAR_QUANTILE", "0.99")
    monkeypatch.setenv("WAVEMIND_QDRANT_SCALAR_ALWAYS_RAM", "1")
    monkeypatch.setenv("WAVEMIND_QDRANT_QUANTIZATION_RESCORE", "0")

    source_ids = benchmark.choose_source_ids(64, 4, 3)
    signature = benchmark._checkpoint_signature(
        engine="Qdrant service streaming",
        count=64,
        dim=8,
        query_count=4,
        top_k=2,
        seed=3,
        noise=0.01,
        batch_size=32,
        extra={"collection_config": benchmark._qdrant_collection_config_from_env()},
    )
    checkpoint = benchmark._new_checkpoint(signature)
    checkpoint["metadata"]["collection_name"] = collection_name
    checkpoint["completed_batch_starts"] = [1, 33]
    checkpoint["source_vectors"] = {
        str(source_id): [1.0] + [0.0] * 7 for source_id in source_ids
    }
    benchmark._write_checkpoint(checkpoint_path, checkpoint)

    def fail_if_vectors_are_regenerated(**kwargs):
        raise AssertionError("complete Qdrant checkpoint must not regenerate batches")

    monkeypatch.setattr(
        benchmark,
        "iter_vector_batches",
        fail_if_vectors_are_regenerated,
    )
    row = benchmark.run_qdrant_streaming(
        count=64,
        dim=8,
        query_count=4,
        top_k=2,
        seed=3,
        noise=0.01,
        batch_size=32,
    )

    assert row["qdrant_checkpoint_complete_resume"] is True
    assert row["checkpoint_completed_batches"] == 2
    assert row["checkpoint_source_vectors"] == 4
    assert row["transport"] == {
        "prefer_grpc": True,
        "grpc_port": 6336,
        "query_timeout_seconds": 300,
    }
    assert FakeQdrantClient.init_kwargs["prefer_grpc"] is True
    assert FakeQdrantClient.init_kwargs["grpc_port"] == 6336
    assert {call["timeout"] for call in FakeQdrantClient.query_kwargs} == {300}
    assert len(FakeQdrantClient.update_kwargs) == 1
    assert FakeQdrantClient.update_kwargs[0]["hnsw_config"].on_disk is False
    assert (
        FakeQdrantClient.update_kwargs[0]["quantization_config"].scalar.always_ram
        is True
    )
    assert row["collection_params"]["scalar_quantization"] == {
        "type": "int8",
        "quantile": 0.99,
        "always_ram": True,
    }
    assert row["search_params"]["quantization"]["rescore"] is False


def test_qdrant_sharded_complete_resume_uses_grpc_and_quantization(
    tmp_path,
    monkeypatch,
):
    from benchmarks import production_streaming_load_benchmark as benchmark

    class Model:
        def __init__(self, **kwargs):
            self.__dict__.update(kwargs)

    class FakeQdrantClient:
        init_kwargs = []
        query_kwargs = []
        update_kwargs = []

        def __init__(self, **kwargs):
            type(self).init_kwargs.append(kwargs)

        def recreate_collection(self, **kwargs):
            raise AssertionError("complete sharded checkpoint must reuse collections")

        def get_collection(self, *, collection_name):
            return SimpleNamespace(
                points_count=32,
                indexed_vectors_count=32,
                status="green",
                optimizer_status="ok",
            )

        def update_collection(self, **kwargs):
            type(self).update_kwargs.append(kwargs)
            return True

        def query_points(self, **kwargs):
            type(self).query_kwargs.append(kwargs)
            return SimpleNamespace(points=[SimpleNamespace(id=1, score=1.0)])

        def close(self):
            return None

    fake_models = SimpleNamespace(
        Distance=SimpleNamespace(COSINE="Cosine"),
        HnswConfigDiff=Model,
        OptimizersConfigDiff=Model,
        PointStruct=Model,
        QuantizationSearchParams=Model,
        ScalarQuantization=Model,
        ScalarQuantizationConfig=Model,
        ScalarType=SimpleNamespace(INT8="int8"),
        SearchParams=Model,
        VectorParams=Model,
    )
    monkeypatch.setitem(
        sys.modules,
        "qdrant_client",
        SimpleNamespace(QdrantClient=FakeQdrantClient),
    )
    monkeypatch.setitem(sys.modules, "qdrant_client.models", fake_models)

    checkpoint_path = tmp_path / "qdrant-sharded-complete.checkpoint.json"
    urls = ["http://127.0.0.1:6335", "http://127.0.0.1:6337"]
    collection_prefix = "complete_sharded_resume"
    monkeypatch.setenv("WAVEMIND_QDRANT_URLS", ",".join(urls))
    monkeypatch.setenv("WAVEMIND_QDRANT_COLLECTION_PREFIX", collection_prefix)
    monkeypatch.setenv("WAVEMIND_STREAMING_CHECKPOINT_PATH", str(checkpoint_path))
    monkeypatch.setenv("WAVEMIND_QDRANT_DEFER_INDEXING", "0")
    monkeypatch.setenv("WAVEMIND_QDRANT_PREFER_GRPC", "1")
    monkeypatch.setenv("WAVEMIND_QDRANT_GRPC_PORTS", "6336,6338")
    monkeypatch.setenv("WAVEMIND_QDRANT_QUERY_TIMEOUT_SECONDS", "300")
    monkeypatch.setenv("WAVEMIND_QDRANT_HNSW_ON_DISK", "0")
    monkeypatch.setenv("WAVEMIND_QDRANT_SCALAR_QUANTIZATION", "1")
    monkeypatch.setenv("WAVEMIND_QDRANT_SCALAR_QUANTILE", "0.99")
    monkeypatch.setenv("WAVEMIND_QDRANT_SCALAR_ALWAYS_RAM", "1")
    monkeypatch.setenv("WAVEMIND_QDRANT_QUANTIZATION_RESCORE", "0")

    source_ids = benchmark.choose_source_ids(64, 4, 3)
    signature = benchmark._checkpoint_signature(
        engine="Qdrant sharded service streaming",
        count=64,
        dim=8,
        query_count=4,
        top_k=2,
        seed=3,
        noise=0.01,
        batch_size=32,
        extra={
            "collection_config": benchmark._qdrant_collection_config_from_env(),
            "target_urls": urls,
        },
    )
    checkpoint = benchmark._new_checkpoint(signature)
    checkpoint["metadata"]["collection_prefix"] = collection_prefix
    checkpoint["completed_batch_starts"] = [1, 33]
    checkpoint["source_vectors"] = {
        str(source_id): [1.0] + [0.0] * 7 for source_id in source_ids
    }
    benchmark._write_checkpoint(checkpoint_path, checkpoint)

    def fail_if_vectors_are_regenerated(**kwargs):
        raise AssertionError("complete sharded checkpoint must not regenerate batches")

    monkeypatch.setattr(
        benchmark,
        "iter_vector_batches",
        fail_if_vectors_are_regenerated,
    )
    row = benchmark.run_qdrant_sharded_streaming(
        count=64,
        dim=8,
        query_count=4,
        top_k=2,
        seed=3,
        noise=0.01,
        batch_size=32,
    )

    assert row["qdrant_checkpoint_complete_resume"] is True
    assert row["checkpoint_completed_batches"] == 2
    assert row["checkpoint_source_vectors"] == 4
    assert row["transport"] == {
        "prefer_grpc": True,
        "grpc_ports": [6336, 6338],
        "query_timeout_seconds": 300,
    }
    assert [call["grpc_port"] for call in FakeQdrantClient.init_kwargs] == [
        6336,
        6338,
    ]
    assert all(call["prefer_grpc"] is True for call in FakeQdrantClient.init_kwargs)
    assert {call["timeout"] for call in FakeQdrantClient.query_kwargs} == {300}
    assert len(FakeQdrantClient.update_kwargs) == 2
    assert all(
        call["quantization_config"].scalar.always_ram is True
        for call in FakeQdrantClient.update_kwargs
    )
    assert row["search_params"]["quantization"]["rescore"] is False
    assert row["collection_params"]["scalar_quantization"]["quantile"] == 0.99


def test_streaming_load_faiss_ivfpq_smoke(tmp_path, monkeypatch):
    pytest.importorskip("faiss")

    from benchmarks import production_streaming_load_benchmark as benchmark

    run_streaming_load = benchmark.run_streaming_load

    index_path = tmp_path / "streaming-ivfpq.faiss"
    checkpoint_path = tmp_path / "streaming-ivfpq.checkpoint.json"
    monkeypatch.setenv("WAVEMIND_FAISS_IVFPQ_PATH", str(index_path))
    monkeypatch.setenv("WAVEMIND_STREAMING_CHECKPOINT_PATH", str(checkpoint_path))
    monkeypatch.setenv("WAVEMIND_FAISS_IVFPQ_NLIST", "8")
    monkeypatch.setenv("WAVEMIND_FAISS_IVFPQ_M", "2")
    monkeypatch.setenv("WAVEMIND_FAISS_IVFPQ_NBITS", "8")
    monkeypatch.setenv("WAVEMIND_FAISS_IVFPQ_NPROBE", "8")
    monkeypatch.setenv("WAVEMIND_FAISS_IVFPQ_NPROBE_SWEEP", "1,2,4,8")
    monkeypatch.setenv("WAVEMIND_FAISS_IVFPQ_TRAINING_SIZE", "12000")
    monkeypatch.setenv("WAVEMIND_FAISS_CHECKPOINT_INTERVAL_BATCHES", "2")

    payload = run_streaming_load(
        sizes=[1024],
        dim=8,
        query_count=16,
        top_k=10,
        seed=13,
        noise=0.0,
        batch_size=256,
        engines=["faiss-ivfpq-persisted"],
    )

    row = payload["results"][0]["results"][0]
    assert row["engine"] == "WaveMind faiss-ivfpq-persisted streaming"
    assert row["faiss_index"] == "IndexIVFPQ"
    assert row["target_recall_at_k"] >= 0.95
    assert row["ivfpq_nprobe"] in {1, 2, 4, 8}
    assert row["ivfpq_nprobe_candidates"] == [1, 2, 4, 8]
    assert row["ivfpq_nprobe_sweep"]
    assert row["ivfpq_nprobe_sweep"][-1]["nprobe"] == row["ivfpq_nprobe"]
    assert row["ivfpq_nprobe_selection_reason"] == "first_candidate_meeting_recall_and_p99"
    assert index_path.exists()
    assert checkpoint_path.exists()
    assert row["checkpoint_enabled"] is True
    assert row["checkpoint_completed_batches"] == 4
    assert row["checkpoint_source_vectors"] == 16
    assert row["faiss_checkpoint_interval_batches"] == 2
    assert row["faiss_checkpoint_write_count"] == 3
    assert row["faiss_checkpoint_complete_resume"] is False
    assert not list(tmp_path.glob("streaming-ivfpq.faiss.checkpoint-*"))

    legacy_checkpoint = json.loads(checkpoint_path.read_text(encoding="utf-8"))
    legacy_checkpoint["signature"]["extra"]["nprobe"] = 8
    checkpoint_path.write_text(
        json.dumps(legacy_checkpoint, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    def fail_if_vectors_are_regenerated(**kwargs):
        raise AssertionError("complete checkpoint must not regenerate vector batches")

    monkeypatch.setattr(
        benchmark,
        "iter_vector_batches",
        fail_if_vectors_are_regenerated,
    )
    resumed = run_streaming_load(
        sizes=[1024],
        dim=8,
        query_count=16,
        top_k=10,
        seed=13,
        noise=0.0,
        batch_size=256,
        engines=["faiss-ivfpq-persisted"],
    )
    resumed_row = resumed["results"][0]["results"][0]
    assert resumed_row["target_recall_at_k"] >= 0.95
    assert resumed_row["checkpoint_completed_batches"] == 4
    assert resumed_row["checkpoint_source_vectors"] == 16
    assert resumed_row["faiss_checkpoint_write_count"] == 1
    assert resumed_row["faiss_checkpoint_complete_resume"] is True
    migrated = json.loads(checkpoint_path.read_text(encoding="utf-8"))
    assert "nprobe" not in migrated["signature"]["extra"]
    assert migrated["metadata"]["signature_migrated_from_nprobe"] == 8

    monkeypatch.setenv("WAVEMIND_FAISS_IVFPQ_NPROBE_SWEEP", "1,2")
    fallback = run_streaming_load(
        sizes=[1024],
        dim=8,
        query_count=16,
        top_k=10,
        seed=13,
        noise=0.0,
        batch_size=256,
        engines=["faiss-ivfpq-persisted"],
        target_p99_ms=1e-9,
    )
    fallback_row = fallback["results"][0]["results"][0]
    assert len(fallback_row["ivfpq_nprobe_sweep"]) == 2
    assert (
        fallback_row["ivfpq_nprobe_selection_reason"]
        == "best_recall_then_latency_no_candidate_met_both_targets"
    )


def test_streaming_load_faiss_ivfpq_resumes_atomic_partial_snapshot(
    tmp_path,
    monkeypatch,
):
    pytest.importorskip("faiss")

    from benchmarks import production_streaming_load_benchmark as benchmark

    index_path = tmp_path / "interrupted-ivfpq.faiss"
    checkpoint_path = tmp_path / "interrupted-ivfpq.checkpoint.json"
    monkeypatch.setenv("WAVEMIND_FAISS_IVFPQ_PATH", str(index_path))
    monkeypatch.setenv("WAVEMIND_STREAMING_CHECKPOINT_PATH", str(checkpoint_path))
    monkeypatch.setenv("WAVEMIND_FAISS_IVFPQ_NLIST", "8")
    monkeypatch.setenv("WAVEMIND_FAISS_IVFPQ_M", "2")
    monkeypatch.setenv("WAVEMIND_FAISS_IVFPQ_NBITS", "8")
    monkeypatch.setenv("WAVEMIND_FAISS_IVFPQ_NPROBE", "8")
    monkeypatch.setenv("WAVEMIND_FAISS_IVFPQ_TRAINING_SIZE", "12000")
    monkeypatch.setenv("WAVEMIND_FAISS_CHECKPOINT_INTERVAL_BATCHES", "2")

    original_iter = benchmark.iter_vector_batches

    def interrupted_iter(**kwargs):
        for batch_index, batch in enumerate(original_iter(**kwargs)):
            yield batch
            if batch_index == 1:
                raise RuntimeError("simulated runner interruption")

    monkeypatch.setattr(benchmark, "iter_vector_batches", interrupted_iter)
    with pytest.raises(RuntimeError, match="simulated runner interruption"):
        benchmark.run_streaming_load(
            sizes=[1024],
            dim=8,
            query_count=16,
            top_k=10,
            seed=17,
            noise=0.0,
            batch_size=256,
            engines=["faiss-ivfpq-persisted"],
        )

    partial = json.loads(checkpoint_path.read_text(encoding="utf-8"))
    assert partial["completed_batch_starts"] == [1, 257]
    assert partial["metadata"]["faiss_snapshot_ntotal"] == 512
    partial_snapshot = Path(partial["metadata"]["faiss_snapshot_path"])
    assert partial_snapshot.exists()
    assert not index_path.exists()

    monkeypatch.setattr(benchmark, "iter_vector_batches", original_iter)
    resumed = benchmark.run_streaming_load(
        sizes=[1024],
        dim=8,
        query_count=16,
        top_k=10,
        seed=17,
        noise=0.0,
        batch_size=256,
        engines=["faiss-ivfpq-persisted"],
    )

    row = resumed["results"][0]["results"][0]
    assert row["target_recall_at_k"] >= 0.95
    assert row["checkpoint_completed_batches"] == 4
    assert row["checkpoint_source_vectors"] == 16
    assert index_path.exists()
    assert not partial_snapshot.exists()
    assert not list(tmp_path.glob("interrupted-ivfpq.faiss.checkpoint-*"))


def test_streaming_checkpoint_rejects_signature_mismatch(tmp_path):
    from benchmarks.production_streaming_load_benchmark import (
        _checkpoint_signature,
        _load_checkpoint,
        _record_checkpoint_batch,
    )

    checkpoint_path = tmp_path / "streaming.checkpoint.json"
    signature = _checkpoint_signature(
        engine="test-engine",
        count=64,
        dim=8,
        query_count=4,
        top_k=2,
        seed=3,
        noise=0.01,
        batch_size=32,
    )
    payload = _load_checkpoint(checkpoint_path, signature)
    _record_checkpoint_batch(
        path=checkpoint_path,
        payload=payload,
        batch_start=1,
        captured={3: [0.1, 0.2]},
    )

    assert checkpoint_path.exists()
    loaded = _load_checkpoint(checkpoint_path, signature)
    assert loaded["completed_batch_starts"] == [1]
    assert loaded["source_vectors"]["3"] == pytest.approx([0.1, 0.2])

    mismatch = dict(signature)
    mismatch["vectors"] = 128
    with pytest.raises(ValueError, match="does not match"):
        _load_checkpoint(checkpoint_path, mismatch)


def test_streaming_checkpoint_retries_transient_windows_replace_lock(
    tmp_path,
    monkeypatch,
):
    from benchmarks.production_streaming_load_benchmark import _write_checkpoint

    checkpoint_path = tmp_path / "streaming.checkpoint.json"
    original_replace = Path.replace
    attempts = 0

    def transient_lock(path, target):
        nonlocal attempts
        attempts += 1
        if attempts < 3:
            raise PermissionError(5, "simulated sharing violation")
        return original_replace(path, target)

    monkeypatch.setattr(Path, "replace", transient_lock)
    monkeypatch.setenv("WAVEMIND_CHECKPOINT_REPLACE_RETRIES", "3")
    monkeypatch.setenv("WAVEMIND_CHECKPOINT_REPLACE_DELAY_SECONDS", "0")

    _write_checkpoint(checkpoint_path, {"schema": "test"})

    assert attempts == 3
    assert json.loads(checkpoint_path.read_text(encoding="utf-8"))["schema"] == "test"


def test_streaming_load_cli_writes_json(tmp_path):
    output = tmp_path / "streaming-load.json"
    project_root = Path(__file__).resolve().parents[1]
    env = os.environ.copy()
    env["PYTHONPATH"] = str(project_root) + os.pathsep + env.get("PYTHONPATH", "")

    subprocess.run(
        [
            sys.executable,
            "benchmarks/production_streaming_load_benchmark.py",
            "--sizes",
            "128",
            "--dim",
            "12",
            "--queries",
            "6",
            "--top-k",
            "3",
            "--batch-size",
            "32",
            "--engines",
            "numpy-streaming",
            "--output",
            str(output),
        ],
        cwd=project_root,
        env=env,
        text=True,
        encoding="utf-8",
        capture_output=True,
        check=True,
    )

    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload["scenario"]["name"] == "production_streaming_load_profile"
    assert payload["scenario"]["vector_dim"] == 12
    assert payload["results"][0]["vectors"] == 128
    assert payload["results"][0]["results"][0]["target_recall_at_k"] >= 0.95


def test_streaming_load_plan_only_estimates_50m_without_generating_vectors(monkeypatch):
    from benchmarks.production_streaming_load_benchmark import plan_streaming_load

    monkeypatch.delenv("WAVEMIND_FAISS_IVFPQ_PATH", raising=False)

    payload = plan_streaming_load(
        sizes=[50_000_000],
        dim=128,
        query_count=100,
        top_k=10,
        seed=42,
        noise=0.08,
        batch_size=100_000,
        engines=["faiss-ivfpq-persisted"],
        output_path=Path("benchmarks/production_streaming_load_50m_plan.json"),
        planned_result_output_path=Path("benchmarks/production_streaming_load_ivfpq_50m_results.json"),
    )

    assert payload["schema"] == "wavemind.production_streaming_load_plan.v1"
    assert payload["scenario"]["plan_only"] is True
    assert payload["scenario"]["sizes"] == [50_000_000]
    assert payload["scenario"]["runner_storage_root"] == "state"
    assert payload["scenario"]["disk_free_path"]
    assert "disk_free_gb" in payload["scenario"]
    assert payload["status"] == "action_required"
    row = payload["plans"][0]
    assert row["vectors"] == 50_000_000
    assert row["engine"] == "WaveMind faiss-ivfpq-persisted streaming"
    assert row["estimated_index_gb"] > 0
    assert row["estimated_index_gb"] < row["estimated_application_storage_gb"]
    assert row["required_local_free_gb"] > row["estimated_index_gb"]
    assert "WAVEMIND_FAISS_IVFPQ_PATH" in row["required_env"]
    assert row["command_env"]["WAVEMIND_FAISS_CHECKPOINT_INTERVAL_BATCHES"] == "5"
    assert row["command_env"]["WAVEMIND_FAISS_IVFPQ_NPROBE_SWEEP"] == "64,128,256,512,1024"
    assert "missing_env:WAVEMIND_FAISS_IVFPQ_PATH" in row["blockers"]
    assert row["runner_storage_root"] == "state"
    assert row["disk_free_path"]
    assert row["checkpoint_path"] == "state/faiss-ivfpq-persisted-50000000.checkpoint.json"
    assert row["resume_mode"].startswith("batch checkpoint")
    assert "--sizes 50000000" in row["command"]
    assert "--engines faiss-ivfpq-persisted" in row["command"]
    assert "--checkpoint-path state/faiss-ivfpq-persisted-50000000.checkpoint.json" in row["command"]
    assert "--output benchmarks" in row["command"]
    assert "production_streaming_load_ivfpq_50m_results.json" in row["command"]
    assert row["claim_boundary"].startswith("preflight only")


def test_streaming_load_plan_only_uses_runner_storage_root(tmp_path, monkeypatch):
    from benchmarks.production_streaming_load_benchmark import plan_streaming_load

    monkeypatch.delenv("WAVEMIND_FAISS_IVFPQ_PATH", raising=False)
    runner_root = tmp_path / "streaming-state"
    runner_root.mkdir()

    payload = plan_streaming_load(
        sizes=[50_000_000],
        dim=128,
        query_count=100,
        top_k=10,
        seed=42,
        noise=0.08,
        batch_size=100_000,
        engines=["faiss-ivfpq-persisted"],
        output_path=Path("benchmarks/production_streaming_load_50m_plan.json"),
        planned_result_output_path=Path("benchmarks/production_streaming_load_ivfpq_50m_results.json"),
        runner_storage_root=runner_root,
        disk_free_gb_override=1000.0,
    )

    row = payload["plans"][0]
    assert payload["scenario"]["runner_storage_root"].endswith("streaming-state")
    assert payload["scenario"]["disk_free_path"].endswith("streaming-state")
    assert payload["scenario"]["disk_free_gb"] == 1000.0
    assert row["runner_storage_root"].endswith("streaming-state")
    assert row["disk_free_path"].endswith("streaming-state")
    assert row["disk_free_gb"] == 1000.0
    assert row["checkpoint_path"].endswith(
        "streaming-state/faiss-ivfpq-persisted-50000000.checkpoint.json"
    )
    assert row["command_env"]["WAVEMIND_FAISS_IVFPQ_PATH"].endswith(
        "streaming-state/wavemind-faiss-ivfpq-50m.faiss"
    )
    assert "streaming-state/faiss-ivfpq-persisted-50000000.checkpoint.json" in row["command"]


def test_streaming_load_plan_only_cli_writes_json(tmp_path):
    output = tmp_path / "streaming-load-plan.json"
    project_root = Path(__file__).resolve().parents[1]
    env = os.environ.copy()
    env["PYTHONPATH"] = str(project_root) + os.pathsep + env.get("PYTHONPATH", "")
    env.pop("WAVEMIND_FAISS_IVFPQ_PATH", None)

    subprocess.run(
        [
            sys.executable,
            "benchmarks/production_streaming_load_benchmark.py",
            "--plan-only",
            "--sizes",
            "50000000",
            "--dim",
            "128",
            "--queries",
            "100",
            "--top-k",
            "10",
            "--batch-size",
            "100000",
            "--engines",
            "faiss-ivfpq-persisted",
            "--output",
            str(output),
            "--planned-result-output",
            "benchmarks/production_streaming_load_ivfpq_50m_results.json",
        ],
        cwd=project_root,
        env=env,
        text=True,
        encoding="utf-8",
        capture_output=True,
        check=True,
    )

    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload["schema"] == "wavemind.production_streaming_load_plan.v1"
    assert payload["plans"][0]["vectors"] == 50_000_000
    assert payload["plans"][0]["status"] == "action_required"
    assert "--checkpoint-path state/faiss-ivfpq-persisted-50000000.checkpoint.json" in payload["plans"][0]["command"]
    assert "production_streaming_load_ivfpq_50m_results.json" in payload["plans"][0]["command"]


def test_streaming_load_plan_only_cli_accepts_runner_storage_root(tmp_path):
    output = tmp_path / "streaming-load-plan.json"
    runner_root = tmp_path / "runner-state"
    runner_root.mkdir()
    project_root = Path(__file__).resolve().parents[1]
    env = os.environ.copy()
    env["PYTHONPATH"] = str(project_root) + os.pathsep + env.get("PYTHONPATH", "")
    env.pop("WAVEMIND_FAISS_IVFPQ_PATH", None)

    subprocess.run(
        [
            sys.executable,
            "benchmarks/production_streaming_load_benchmark.py",
            "--plan-only",
            "--sizes",
            "50000000",
            "--dim",
            "128",
            "--queries",
            "100",
            "--top-k",
            "10",
            "--batch-size",
            "100000",
            "--engines",
            "faiss-ivfpq-persisted",
            "--runner-storage-root",
            str(runner_root),
            "--disk-free-gb",
            "1000",
            "--output",
            str(output),
            "--planned-result-output",
            "benchmarks/production_streaming_load_ivfpq_50m_results.json",
        ],
        cwd=project_root,
        env=env,
        text=True,
        encoding="utf-8",
        capture_output=True,
        check=True,
    )

    row = json.loads(output.read_text(encoding="utf-8"))["plans"][0]
    assert row["disk_free_gb"] == 1000.0
    assert row["checkpoint_path"].endswith(
        "runner-state/faiss-ivfpq-persisted-50000000.checkpoint.json"
    )
    assert row["command_env"]["WAVEMIND_FAISS_IVFPQ_PATH"].endswith(
        "runner-state/wavemind-faiss-ivfpq-50m.faiss"
    )


def test_streaming_load_plan_only_supports_pgvector_service(monkeypatch):
    from benchmarks.production_streaming_load_benchmark import plan_streaming_load

    monkeypatch.delenv("WAVEMIND_PGVECTOR_DSN", raising=False)

    payload = plan_streaming_load(
        sizes=[10_000_000],
        dim=128,
        query_count=100,
        top_k=10,
        seed=42,
        noise=0.08,
        batch_size=100_000,
        engines=["pgvector-service"],
        output_path=Path("benchmarks/production_streaming_load_pgvector_10m_plan.json"),
        planned_result_output_path=Path("benchmarks/production_streaming_load_pgvector_10m_results.json"),
    )

    row = payload["plans"][0]
    assert row["engine"] == "WaveMind pgvector streaming"
    assert row["vectors"] == 10_000_000
    assert row["estimated_index_gb"] == 0.0
    assert row["index_mode"].startswith("remote PostgreSQL/pgvector")
    assert "WAVEMIND_PGVECTOR_DSN" in row["required_env"]
    assert "missing_env:WAVEMIND_PGVECTOR_DSN" in row["blockers"]
    assert row["command_env"]["WAVEMIND_PGVECTOR_CREATE_HNSW"] == "1"
    assert row["command_env"]["WAVEMIND_PGVECTOR_STORAGE_TYPE"] == "halfvec"
    assert row["command_env"]["WAVEMIND_PGVECTOR_INSERT_MODE"] == "copy"
    assert "--engines pgvector-service" in row["command"]
    assert "production_streaming_load_pgvector_10m_results.json" in row["command"]


def test_pgvector_config_validates_storage_and_insert_modes(monkeypatch):
    from benchmarks.production_streaming_load_benchmark import _pgvector_config_from_env

    monkeypatch.setenv("WAVEMIND_PGVECTOR_STORAGE_TYPE", "halfvec")
    monkeypatch.setenv("WAVEMIND_PGVECTOR_INSERT_MODE", "copy")
    config = _pgvector_config_from_env()
    assert config["storage_type"] == "halfvec"
    assert config["insert_mode"] == "copy"

    monkeypatch.setenv("WAVEMIND_PGVECTOR_STORAGE_TYPE", "binary")
    with pytest.raises(ValueError, match="must be vector or halfvec"):
        _pgvector_config_from_env()


def test_pgvector_copy_batch_replaces_only_uncheckpointed_range():
    from benchmarks.production_streaming_load_benchmark import _pgvector_insert_batch

    class FakeCopy:
        def __init__(self):
            self.rows = []

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, traceback):
            return False

        def write_row(self, row):
            self.rows.append(row)

    class FakeCursor:
        def __init__(self):
            self.executed = []
            self.copy_sql = None
            self.copy_stream = FakeCopy()

        def execute(self, sql, params):
            self.executed.append((sql, params))

        def copy(self, sql):
            self.copy_sql = sql
            return self.copy_stream

    cursor = FakeCursor()
    ids = np.asarray([101, 102], dtype=np.int64)
    vectors = np.asarray([[1.0, 0.0], [0.0, 1.0]], dtype=np.float32)
    _pgvector_insert_batch(
        cursor,
        table="wavemind_vectors",
        collection="run-1",
        ids=ids,
        vectors=vectors,
        storage_type="halfvec",
        insert_mode="copy",
    )

    assert cursor.executed == [
        (
            "DELETE FROM wavemind_vectors WHERE collection = %s AND memory_id BETWEEN %s AND %s",
            ("run-1", 101, 102),
        )
    ]
    assert cursor.copy_sql == (
        "COPY wavemind_vectors (collection, memory_id, embedding) FROM STDIN"
    )
    assert [row[:2] for row in cursor.copy_stream.rows] == [
        ("run-1", 101),
        ("run-1", 102),
    ]


def test_streaming_load_plan_only_supports_qdrant_service(monkeypatch):
    from benchmarks.production_streaming_load_benchmark import plan_streaming_load

    monkeypatch.delenv("WAVEMIND_QDRANT_URL", raising=False)

    payload = plan_streaming_load(
        sizes=[10_000_000],
        dim=128,
        query_count=100,
        top_k=10,
        seed=42,
        noise=0.08,
        batch_size=100_000,
        engines=["qdrant-service"],
        output_path=Path("benchmarks/production_streaming_load_qdrant_10m_plan.json"),
        planned_result_output_path=Path("benchmarks/production_streaming_load_qdrant_10m_results.json"),
    )

    row = payload["plans"][0]
    assert row["engine"] == "Qdrant service streaming"
    assert row["vectors"] == 10_000_000
    assert row["estimated_index_gb"] == 0.0
    assert row["index_mode"].startswith("remote Qdrant service")
    assert "WAVEMIND_QDRANT_URL" in row["required_env"]
    assert "missing_env:WAVEMIND_QDRANT_URL" in row["blockers"]
    assert row["command_env"]["WAVEMIND_QDRANT_VECTOR_ON_DISK"] == "1"
    assert row["command_env"]["WAVEMIND_QDRANT_HNSW_ON_DISK"] == "0"
    assert row["command_env"]["WAVEMIND_QDRANT_PREFER_GRPC"] == "1"
    assert row["command_env"]["WAVEMIND_QDRANT_GRPC_PORT"] == "6334"
    assert row["command_env"]["WAVEMIND_QDRANT_SCALAR_QUANTIZATION"] == "1"
    assert row["command_env"]["WAVEMIND_QDRANT_SCALAR_ALWAYS_RAM"] == "1"
    assert row["command_env"]["WAVEMIND_QDRANT_QUANTIZATION_RESCORE"] == "0"
    assert row["command_env"]["WAVEMIND_QDRANT_REQUIRE_FULL_INDEX"] == "1"
    assert row["command_env"]["WAVEMIND_QDRANT_DEFER_INDEXING"] == "1"
    assert (
        row["command_env"]["WAVEMIND_QDRANT_INDEX_READY_TIMEOUT_SECONDS"]
        == "1800"
    )
    assert "--engines qdrant-service" in row["command"]
    assert "production_streaming_load_qdrant_10m_results.json" in row["command"]


def test_streaming_load_plan_only_supports_qdrant_sharded_service(monkeypatch):
    from benchmarks.production_streaming_load_benchmark import plan_streaming_load

    monkeypatch.delenv("WAVEMIND_QDRANT_URLS", raising=False)
    monkeypatch.setenv("WAVEMIND_QDRANT_SHARD_COUNT", "6")

    payload = plan_streaming_load(
        sizes=[10_000_000],
        dim=128,
        query_count=100,
        top_k=10,
        seed=42,
        noise=0.08,
        batch_size=100_000,
        engines=["qdrant-sharded-service"],
        output_path=Path("benchmarks/production_streaming_load_qdrant_sharded_10m_plan.json"),
        planned_result_output_path=Path("benchmarks/production_streaming_load_qdrant_sharded_10m_results.json"),
    )

    row = payload["plans"][0]
    assert row["engine"] == "Qdrant sharded service streaming"
    assert row["vectors"] == 10_000_000
    assert row["estimated_index_gb"] == 0.0
    assert "horizontally sharded Qdrant" in row["index_mode"]
    assert "WAVEMIND_QDRANT_URLS" in row["required_env"]
    assert "missing_env:WAVEMIND_QDRANT_URLS" in row["blockers"]
    assert row["command_env"]["WAVEMIND_QDRANT_FANOUT_WORKERS"] == "6"
    assert row["command_env"]["WAVEMIND_QDRANT_PREFER_GRPC"] == "1"
    assert row["command_env"]["WAVEMIND_QDRANT_GRPC_PORT"] == "6334"
    assert row["command_env"]["WAVEMIND_QDRANT_HNSW_ON_DISK"] == "0"
    assert row["command_env"]["WAVEMIND_QDRANT_SCALAR_QUANTIZATION"] == "1"
    assert row["command_env"]["WAVEMIND_QDRANT_QUANTIZATION_RESCORE"] == "0"
    assert row["command_env"]["WAVEMIND_QDRANT_REQUIRE_FULL_INDEX"] == "1"
    assert row["command_env"]["WAVEMIND_QDRANT_DEFER_INDEXING"] == "1"
    assert (
        row["command_env"]["WAVEMIND_QDRANT_INDEX_READY_TIMEOUT_SECONDS"]
        == "1800"
    )
    assert "qdrant-5.example" in row["command_env"]["WAVEMIND_QDRANT_URLS"]
    assert "--engines qdrant-sharded-service" in row["command"]
    assert "production_streaming_load_qdrant_sharded_10m_results.json" in row["command"]
