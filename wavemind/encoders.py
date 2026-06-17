from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from typing import Protocol

import numpy as np


class TextVectorEncoder(Protocol):
    vector_dim: int

    def encode_vector(self, text: str) -> np.ndarray:
        ...


def _l2_normalize(vector: np.ndarray) -> np.ndarray:
    vector = np.asarray(vector, dtype=np.float32)
    norm = float(np.linalg.norm(vector))
    if norm <= 1e-12:
        return vector.astype(np.float32)
    return (vector / norm).astype(np.float32)


@dataclass
class HashingTextEncoder:
    vector_dim: int = 384
    token_weight: float = 4.0
    char_ngram_weight: float = 0.10

    def encode_vector(self, text: str) -> np.ndarray:
        text = text.lower().strip()
        vector = np.zeros(self.vector_dim, dtype=np.float32)
        if not text:
            return vector

        tokens = re.findall(r"[\w]+", text, flags=re.UNICODE)
        for token in tokens:
            self._add_feature(vector, f"tok:{token}", self.token_weight)

        compact = re.sub(r"\s+", " ", text)
        for size in (2, 3):
            for i in range(max(0, len(compact) - size + 1)):
                self._add_feature(
                    vector,
                    f"ch{size}:{compact[i:i + size]}",
                    self.char_ngram_weight,
                )

        return _l2_normalize(vector)

    def _add_feature(self, vector: np.ndarray, feature: str, weight: float) -> None:
        digest = hashlib.blake2b(feature.encode("utf-8"), digest_size=16).digest()
        bucket = int.from_bytes(digest[:8], "little") % self.vector_dim
        sign = 1.0 if digest[8] & 1 else -1.0
        vector[bucket] += sign * weight


class SentenceTransformerTextEncoder:
    def __init__(
        self,
        model_name: str = "sentence-transformers/paraphrase-multilingual-mpnet-base-v2",
        model=None,
    ):
        if model is None:
            try:
                from sentence_transformers import SentenceTransformer
            except ImportError as exc:
                raise ImportError(
                    "Install sentence-transformers to use SentenceTransformerTextEncoder"
                ) from exc
            model = SentenceTransformer(model_name)

        self.model_name = model_name
        self.model = model
        if hasattr(model, "get_embedding_dimension"):
            self.vector_dim = int(model.get_embedding_dimension())
        elif hasattr(model, "get_sentence_embedding_dimension"):
            self.vector_dim = int(model.get_sentence_embedding_dimension())
        else:
            self.vector_dim = 768

    def encode_vector(self, text: str) -> np.ndarray:
        encoded = self.model.encode([text], normalize_embeddings=True)
        vector = np.asarray(encoded[0], dtype=np.float32)
        return _l2_normalize(vector)


class FieldProjector:
    def __init__(self, width: int, height: int, vector_dim: int, seed: int = 1729):
        self.width = int(width)
        self.height = int(height)
        self.vector_dim = int(vector_dim)
        rng = np.random.default_rng(seed + self.width * 31 + self.height * 17 + self.vector_dim)
        self._matrix = rng.normal(
            loc=0.0,
            scale=1.0 / max(1, self.vector_dim) ** 0.5,
            size=(self.height * self.width, self.vector_dim),
        ).astype(np.float32)

    def to_pattern(self, vector: np.ndarray) -> np.ndarray:
        vector = _l2_normalize(vector)
        projected = self._matrix @ vector
        projected = np.maximum(projected, 0.0)
        if not np.any(projected):
            projected = np.abs(self._matrix @ vector)
        pattern = projected.reshape(self.height, self.width).astype(np.float32)
        return _l2_normalize(pattern)


TextEncoder = HashingTextEncoder


def create_text_encoder(
    kind: str = "hash",
    vector_dim: int = 384,
    model_name: str = "sentence-transformers/paraphrase-multilingual-mpnet-base-v2",
) -> TextVectorEncoder:
    kind = (kind or "hash").lower()
    if kind == "hash":
        return HashingTextEncoder(vector_dim=vector_dim)
    if kind in {"sentence", "sentence-transformers", "transformer"}:
        return SentenceTransformerTextEncoder(model_name=model_name)
    raise ValueError(
        f"Unknown encoder kind: {kind}. Choose an explicit encoder: hash or sentence."
    )
