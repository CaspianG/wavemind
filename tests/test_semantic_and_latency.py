import statistics
import time
import warnings

import numpy as np

from wavemind import WaveMind


class TinySemanticEncoder:
    vector_dim = 8

    def encode_vector(self, text: str) -> np.ndarray:
        text = text.lower()
        if "машина" in text or "автомобиль" in text:
            return self._unit([1, 0, 0, 0, 0, 0, 0, 0])
        if "собака" in text:
            return self._unit([0, 1, 0, 0, 0, 0, 0, 0])
        return self._unit([0, 0, 1, 0, 0, 0, 0, 0])

    def _unit(self, values):
        vector = np.array(values, dtype=np.float32)
        return vector / np.linalg.norm(vector)


class FlatSemanticEncoder:
    vector_dim = 8

    def encode_vector(self, text: str) -> np.ndarray:
        vector = np.ones(self.vector_dim, dtype=np.float32)
        return vector / np.linalg.norm(vector)


class SkewedShortQueryEncoder:
    vector_dim = 8

    def encode_vector(self, text: str) -> np.ndarray:
        text = text.lower()
        if text.strip() == "needle":
            return self._unit([1, 0, 0, 0, 0, 0, 0, 0])
        if "needle" in text:
            return self._unit([0, 1, 0, 0, 0, 0, 0, 0])
        return self._unit([1, 0, 0, 0, 0, 0, 0, 0])

    def _unit(self, values):
        vector = np.array(values, dtype=np.float32)
        return vector / np.linalg.norm(vector)


def test_semantic_encoder_recalls_synonym_without_shared_tokens(tmp_path):
    mind = WaveMind(
        db_path=tmp_path / "semantic.sqlite3",
        encoder=TinySemanticEncoder(),
        width=16,
        height=16,
        layers=2,
        index_kind="numpy",
    )

    expected_id = mind.remember("Автомобиль припаркован возле дома", namespace="semantic")
    mind.remember("Собака спит на ковре", namespace="semantic")

    results = mind.query("машина", namespace="semantic", top_k=1)

    assert results[0].id == expected_id
    assert results[0].text == "Автомобиль припаркован возле дома"


def test_query_latency_stays_under_10ms_for_200_cached_memories(tmp_path):
    mind = WaveMind(
        db_path=tmp_path / "latency.sqlite3",
        width=64,
        height=64,
        layers=3,
        index_kind="numpy",
        evolve_on_feed=2,
    )
    for i in range(200):
        mind.remember(
            f"latencytoken{i:03d} русское тестовое воспоминание номер {i}",
            namespace="latency",
        )

    latencies = []
    for i in range(50):
        started = time.perf_counter()
        result = mind.query(f"latencytoken{i:03d}", namespace="latency", top_k=3)
        latencies.append((time.perf_counter() - started) * 1000.0)
        assert result[0].text.startswith(f"latencytoken{i:03d}")

    assert statistics.mean(latencies) < 10.0
    assert sorted(latencies)[47] < 15.0


def test_query_includes_exact_lexical_matches_outside_vector_shortlist(tmp_path):
    mind = WaveMind(
        db_path=tmp_path / "lexical-union.sqlite3",
        encoder=FlatSemanticEncoder(),
        width=16,
        height=16,
        layers=2,
        index_kind="numpy",
        rerank_k=3,
    )
    expected_id = mind.remember(
        "specialneedle важная память должна найтись по точному слову",
        namespace="lexical",
    )
    for i in range(30):
        mind.remember(f"обычное воспоминание номер {i}", namespace="lexical")

    results = mind.query("specialneedle", namespace="lexical", top_k=1)

    assert results[0].id == expected_id


def test_short_query_exact_match_can_beat_stronger_vector_candidate(tmp_path):
    mind = WaveMind(
        db_path=tmp_path / "short-query.sqlite3",
        encoder=SkewedShortQueryEncoder(),
        width=16,
        height=16,
        layers=2,
        index_kind="numpy",
        field_weight=0.0,
    )
    expected_id = mind.remember("needle exact lexical memory", namespace="short")
    mind.remember("semantic distractor memory", namespace="short")

    results = mind.query("needle", namespace="short", top_k=1)

    assert results[0].id == expected_id


def test_idf_normalized_lexical_score_prefers_rare_query_evidence(tmp_path):
    mind = WaveMind(
        db_path=tmp_path / "idf-lexical.sqlite3",
        encoder=FlatSemanticEncoder(),
        width=16,
        height=16,
        layers=2,
        index_kind="numpy",
        vector_weight=0.0,
        field_weight=0.0,
        priority_weight=0.0,
        lexical_weight=1.0,
        short_query_lexical_weight=1.0,
        max_lexical_token_frequency=100,
        lexical_idf_normalization=True,
        rerank_k=50,
    )
    try:
        mind.remember("sharedtopic generic evidence", namespace="idf")
        expected_id = mind.remember(
            "uniqueneedle decisive evidence",
            namespace="idf",
        )
        for index in range(20):
            mind.remember(
                f"sharedtopic background record {index}",
                namespace="idf",
            )

        results = mind.query(
            "sharedtopic uniqueneedle",
            namespace="idf",
            top_k=1,
        )

        assert results[0].id == expected_id
    finally:
        mind.close()


def test_idf_document_frequency_cache_tracks_namespaces_and_forget(tmp_path):
    mind = WaveMind(
        db_path=tmp_path / "idf-frequency-cache.sqlite3",
        encoder=FlatSemanticEncoder(),
        width=16,
        height=16,
        layers=2,
        index_kind="numpy",
        lexical_idf_normalization=True,
    )
    try:
        first_id = mind.remember(
            "sharedtopic first",
            namespace="first",
            metadata={"group": "kept"},
        )
        mind.remember(
            "sharedtopic second",
            namespace="first",
            metadata={"group": "drop"},
        )
        mind.remember("sharedtopic other", namespace="other")

        first_ids = mind._allowed_ids("first")
        weights = mind._lexical_query_weights(
            mind._tokens("sharedtopic missing"),
            first_ids,
            namespace="first",
        )

        assert weights is not None
        assert weights["missing"] > weights["sharedtopic"]
        assert mind._namespace_token_counts["first"]["sharedtopic"] == 2
        assert mind._namespace_token_counts["other"]["sharedtopic"] == 1

        filtered_ids = mind._allowed_ids(
            "first",
            metadata_filters={"group": "kept"},
        )
        filtered_weights = mind._lexical_query_weights(
            mind._tokens("sharedtopic missing"),
            filtered_ids,
            namespace="first",
        )
        assert filtered_weights is not None
        assert filtered_weights["missing"] > filtered_weights["sharedtopic"]

        assert mind.forget(id=first_id) == 1
        assert mind._namespace_token_counts["first"]["sharedtopic"] == 1
    finally:
        mind.close()


def test_query_can_diversify_results_by_metadata_group(tmp_path):
    mind = WaveMind(
        db_path=tmp_path / "diversity.sqlite3",
        encoder=FlatSemanticEncoder(),
        width=16,
        height=16,
        layers=2,
        index_kind="numpy",
        vector_weight=0.0,
        field_weight=0.0,
        priority_weight=1.0,
        lexical_weight=0.0,
        short_query_lexical_weight=0.0,
        rerank_k=5,
    )
    try:
        mind.remember(
            "first duplicate",
            namespace="diverse",
            metadata={"trajectory_id": "a"},
            priority=10.0,
        )
        mind.remember(
            "second duplicate",
            namespace="diverse",
            metadata={"trajectory_id": "a"},
            priority=9.0,
        )
        mind.remember(
            "second trajectory",
            namespace="diverse",
            metadata={"trajectory_id": "b"},
            priority=8.0,
        )
        mind.remember(
            "third trajectory",
            namespace="diverse",
            metadata={"trajectory_id": "c"},
            priority=7.0,
        )

        results = mind.query(
            "memory",
            namespace="diverse",
            top_k=3,
            candidate_top_k=4,
            diversity_metadata_key="trajectory_id",
        )

        assert [result.metadata["trajectory_id"] for result in results] == [
            "a",
            "b",
            "c",
        ]
    finally:
        mind.close()


def test_common_query_words_do_not_expand_lexical_candidates(tmp_path):
    mind = WaveMind(
        db_path=tmp_path / "stopwords.sqlite3",
        encoder=FlatSemanticEncoder(),
        width=16,
        height=16,
        layers=2,
        index_kind="numpy",
        rerank_k=1,
    )
    expected_id = mind.remember("rarebudget target memory", namespace="stopwords")
    noise_ids = [
        mind.remember(f"the user background filler memory {i}", namespace="stopwords")
        for i in range(20)
    ]

    tokens = mind._tokens("what is the user rarebudget")
    candidate_ids = mind._lexical_candidate_ids(tokens, {expected_id, *noise_ids})

    assert "the" not in tokens
    assert "user" not in tokens
    assert candidate_ids == {expected_id}


def test_frequent_tokens_do_not_expand_lexical_candidate_pool(tmp_path):
    mind = WaveMind(
        db_path=tmp_path / "frequent-tokens.sqlite3",
        encoder=FlatSemanticEncoder(),
        width=16,
        height=16,
        layers=2,
        index_kind="numpy",
        rerank_k=1,
    )
    try:
        expected_id = mind.remember("rarebudget target memory", namespace="frequent")
        noise_ids = [
            mind.remember(f"память фоновая запись номер {i}", namespace="frequent")
            for i in range(80)
        ]

        tokens = mind._tokens("память rarebudget")
        candidate_ids = mind._lexical_candidate_ids(tokens, {expected_id, *noise_ids})

        assert candidate_ids == {expected_id}
    finally:
        mind.store.close()


def test_field_weight_is_disabled_above_capacity_threshold(tmp_path):
    mind = WaveMind(
        db_path=tmp_path / "field-cutoff.sqlite3",
        encoder=FlatSemanticEncoder(),
        width=16,
        height=16,
        layers=2,
        index_kind="numpy",
        field_weight=0.5,
        field_disable_after=1,
    )
    mind.remember("first memory", namespace="field")
    mind.remember("second memory", namespace="field")

    assert mind._effective_field_weight(allowed_count=1) == 0.5
    assert mind._effective_field_weight(allowed_count=2) == 0.0


def test_field_magnitude_refresh_is_numerically_stable_for_large_values(tmp_path):
    mind = WaveMind(
        db_path=tmp_path / "field-numeric-stability.sqlite3",
        width=8,
        height=8,
        layers=2,
        encoder=FlatSemanticEncoder(),
        index_kind="numpy",
    )
    try:
        mind.field.state.fill(np.finfo(np.float32).max / 4)
        with warnings.catch_warnings():
            warnings.simplefilter("error", RuntimeWarning)
            mind._refresh_field_magnitude()
            score = mind._field_resonance(np.ones((8, 8), dtype=np.float32))

        assert np.isfinite(mind._field_magnitude_norm)
        assert np.isfinite(score)
    finally:
        mind.close()
