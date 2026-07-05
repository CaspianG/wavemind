import numpy as np

from wavemind import WaveMind


class FlatEncoder:
    vector_dim = 4

    def encode_vector(self, text: str) -> np.ndarray:
        vector = np.ones(self.vector_dim, dtype=np.float32)
        return vector / np.linalg.norm(vector)


class TopicEncoder:
    vector_dim = 4

    def encode_vector(self, text: str) -> np.ndarray:
        text = text.lower()
        if "pasta" in text:
            return self._unit([0, 1, 0, 0])
        if "compiler" in text:
            return self._unit([0.95, 0.05, 0, 0])
        return self._unit([1, 0, 0, 0])

    def _unit(self, values: list[float]) -> np.ndarray:
        vector = np.array(values, dtype=np.float32)
        return vector / np.linalg.norm(vector)


def test_wavemind_graph_suppresses_stale_conflicting_memory(tmp_path):
    mind = WaveMind(
        db_path=tmp_path / "graph-conflict.sqlite3",
        encoder=FlatEncoder(),
        width=8,
        height=8,
        layers=1,
        vector_weight=0.0,
        field_weight=0.0,
        priority_weight=0.0,
        lexical_weight=0.0,
        short_query_lexical_weight=0.0,
        graph_weight=1.0,
        graph_steps=1,
    )
    old_id = mind.remember(
        "The user's current city is Berlin",
        namespace="agent",
        metadata={"conflict_group": "profile.city"},
    )
    new_id = mind.remember(
        "The user's current city is Lisbon",
        namespace="agent",
        metadata={"conflict_group": "profile.city"},
    )

    results = mind.query("current city", namespace="agent", top_k=2)

    assert results[0].id == new_id
    assert results[1].id == old_id
    assert results[0].graph_score > results[1].graph_score


def test_wavemind_exposes_coactivated_concept_candidates(tmp_path):
    mind = WaveMind(
        db_path=tmp_path / "graph-concepts.sqlite3",
        encoder=TopicEncoder(),
        width=8,
        height=8,
        layers=1,
        graph_weight=0.4,
        graph_steps=2,
    )
    rust_id = mind.remember("User likes Rust systems programming", namespace="agent", tags=("systems",))
    compiler_id = mind.remember("User studies compiler internals", namespace="agent", tags=("systems",))
    mind.remember("User cooks pasta on Sundays", namespace="agent", tags=("cooking",))

    mind.query("Rust", namespace="agent", top_k=1)
    concepts = mind.concept_candidates(namespace="agent", min_energy=0.01)

    assert concepts
    assert set(concepts[0]["memory_ids"]).issuperset({rust_id, compiler_id})
    assert concepts[0]["label"] == "systems"


def test_wavemind_consolidates_active_cluster_into_durable_concept_memory(tmp_path):
    mind = WaveMind(
        db_path=tmp_path / "graph-consolidation.sqlite3",
        encoder=TopicEncoder(),
        width=8,
        height=8,
        layers=1,
        graph_weight=0.4,
        graph_steps=2,
        rerank_k=5,
    )
    rust_id = mind.remember("User likes Rust systems programming", namespace="agent", tags=("systems",))
    compiler_id = mind.remember("User studies compiler internals", namespace="agent", tags=("systems",))
    mind.remember("User cooks pasta on Sundays", namespace="agent", tags=("cooking",))

    created = mind.consolidate_concepts(
        namespace="agent",
        seed_text="Rust compiler systems",
        min_energy=0.01,
        min_size=2,
    )

    assert len(created) == 1
    concept = created[0]
    assert concept["namespace"] == "agent"
    assert "Consolidated memory: systems" in concept["text"]
    assert set(concept["metadata"]["memory_ids"]).issuperset({rust_id, compiler_id})
    assert concept["metadata"]["source"] == "wavemind_consolidation"

    duplicates = mind.consolidate_concepts(
        namespace="agent",
        seed_text="Rust compiler systems",
        min_energy=0.01,
        min_size=2,
    )
    assert duplicates == []

    concept_hits = mind.query("systems programming", namespace="agent", tags=("concept",), top_k=1)
    assert concept_hits
    assert concept_hits[0].id == concept["id"]
