import json
from pathlib import Path


def test_production_index_profile_compose_documents_real_services():
    compose = Path("examples/production-index-profile/docker-compose.yml").read_text(
        encoding="utf-8"
    )
    readme = Path("examples/production-index-profile/README.md").read_text(
        encoding="utf-8"
    )

    assert "qdrant/qdrant:v1.18.2" in compose
    assert "pgvector/pgvector:pg16" in compose
    assert 'INSTALL_PRODUCTION: "true"' in compose
    assert "WAVEMIND_FAISS_PATH: /state/production-index-profile.faiss" in compose
    assert "WAVEMIND_QDRANT_URL: http://qdrant:6333" in compose
    assert "WAVEMIND_PGVECTOR_CREATE_HNSW: \"1\"" in compose
    assert "faiss-persisted" in compose
    assert "qdrant-service" in compose
    assert "pgvector" in compose
    assert "benchmarks/production_index_profile_results.json" in compose
    assert "docker compose -f examples/production-index-profile/docker-compose.yml run --rm benchmark" in readme


def test_production_index_profile_result_is_checked_in_and_documented():
    payload = json.loads(
        Path("benchmarks/production_index_profile_results.json").read_text(
            encoding="utf-8"
        )
    )
    readme = Path("README.md").read_text(encoding="utf-8")

    assert payload["scenario"]["sizes"] == [10000, 50000]
    latest = payload["results"][-1]
    assert latest["vectors"] == 50000
    engines = {result["engine"]: result for result in latest["results"]}
    assert engines["WaveMind faiss-persisted"]["recall_at_k"] == 1.0
    assert engines["Qdrant service"]["recall_at_k"] == 1.0
    assert engines["WaveMind pgvector"]["recall_at_k"] < 0.95
    assert "Checked-in production 50000-vector point" in readme
    assert "WaveMind faiss-persisted" in readme
    assert "Qdrant service" in readme
    assert "pgvector/HNSW profile is fast but loses" in readme
