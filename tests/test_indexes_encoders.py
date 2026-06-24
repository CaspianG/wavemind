import numpy as np
import pytest

from wavemind.encoders import (
    FieldProjector,
    HashingTextEncoder,
    SentenceTransformerTextEncoder,
    create_text_encoder,
)
from wavemind.indexes import AnnoyVectorIndex, NumpyVectorIndex, create_vector_index


def test_hashing_encoder_is_deterministic_and_normalized():
    encoder = HashingTextEncoder(vector_dim=64)

    a = encoder.encode_vector("кошка спит на окне")
    b = encoder.encode_vector("кошка спит на окне")
    c = encoder.encode_vector("market breakout signal")

    assert a.shape == (64,)
    assert np.allclose(a, b)
    assert np.isclose(np.linalg.norm(a), 1.0)
    assert float(np.dot(a, c)) < 0.95


def test_hashing_encoder_batch_matches_single_vectors():
    encoder = HashingTextEncoder(vector_dim=64)
    texts = ["alpha memory", "beta memory", "gamma memory"]

    batch = encoder.encode_vectors(texts)

    assert batch.shape == (3, 64)
    assert np.allclose(batch[0], encoder.encode_vector(texts[0]))
    assert np.allclose(batch[2], encoder.encode_vector(texts[2]))


def test_sentence_transformer_encoder_uses_injected_model_without_downloading():
    class FakeModel:
        def encode(self, texts, normalize_embeddings=True, show_progress_bar=False):
            assert texts == ["hello"]
            assert normalize_embeddings is True
            assert show_progress_bar is False
            return np.ones((1, 768), dtype=np.float32)

    encoder = SentenceTransformerTextEncoder(model=FakeModel())
    vector = encoder.encode_vector("hello")

    assert vector.shape == (768,)
    assert np.isclose(np.linalg.norm(vector), 1.0)


def test_sentence_transformer_encoder_batches_injected_model():
    class FakeModel:
        def encode(self, texts, normalize_embeddings=True, show_progress_bar=False):
            assert texts == ["hello", "world"]
            return np.eye(2, 768, dtype=np.float32)

    encoder = SentenceTransformerTextEncoder(model=FakeModel())
    vectors = encoder.encode_vectors(["hello", "world"])

    assert vectors.shape == (2, 768)
    assert np.allclose(vectors[0, :2], [1.0, 0.0])
    assert np.allclose(vectors[1, :2], [0.0, 1.0])


def test_sentence_transformer_encoder_requires_dependency_when_no_model(monkeypatch):
    import builtins

    original_import = builtins.__import__

    def fake_import(name, *args, **kwargs):
        if name == "sentence_transformers":
            raise ImportError("missing sentence-transformers")
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fake_import)
    with pytest.raises(ImportError):
        SentenceTransformerTextEncoder()


def test_field_projector_compresses_vectors_to_2d_pattern():
    projector = FieldProjector(width=16, height=8, vector_dim=64, seed=123)
    pattern = projector.to_pattern(np.ones(64, dtype=np.float32))

    assert pattern.shape == (8, 16)
    assert pattern.dtype == np.float32
    assert np.isclose(np.linalg.norm(pattern), 1.0)


def test_numpy_vector_index_returns_exact_cosine_neighbors_with_filters():
    index = NumpyVectorIndex(vector_dim=3)
    index.add(1, np.array([1.0, 0.0, 0.0], dtype=np.float32))
    index.add(2, np.array([0.0, 1.0, 0.0], dtype=np.float32))
    index.add(3, np.array([0.8, 0.2, 0.0], dtype=np.float32))

    all_results = index.search(
        np.array([1.0, 0.0, 0.0], dtype=np.float32),
        top_k=2,
    )
    results = index.search(
        np.array([1.0, 0.0, 0.0], dtype=np.float32),
        top_k=2,
        allowed_ids={1, 3},
    )

    assert [result.id for result in all_results] == [1, 3]
    assert [result.id for result in results] == [1, 3]
    assert results[0].score > results[1].score


def test_index_factory_creates_explicit_numpy_backend():
    index = create_vector_index("numpy", vector_dim=4)
    assert isinstance(index, NumpyVectorIndex)


def test_annoy_vector_index_returns_cosine_neighbors_with_filters():
    pytest.importorskip("annoy")
    index = create_vector_index("annoy", vector_dim=3)
    assert isinstance(index, AnnoyVectorIndex)
    index.add(1, np.array([1.0, 0.0, 0.0], dtype=np.float32))
    index.add(2, np.array([0.0, 1.0, 0.0], dtype=np.float32))
    index.add(3, np.array([0.8, 0.2, 0.0], dtype=np.float32))

    results = index.search(
        np.array([1.0, 0.0, 0.0], dtype=np.float32),
        top_k=2,
        allowed_ids={1, 3},
    )

    assert [result.id for result in results] == [1, 3]
    assert results[0].score > results[1].score


def test_index_factory_rejects_auto_to_avoid_silent_backend_switching():
    with pytest.raises(ValueError, match="explicit"):
        create_vector_index("auto", vector_dim=4)


def test_encoder_factory_rejects_auto_to_avoid_silent_encoder_switching():
    with pytest.raises(ValueError, match="explicit"):
        create_text_encoder("auto")
