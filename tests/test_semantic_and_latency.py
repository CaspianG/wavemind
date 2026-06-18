import statistics
import time

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
