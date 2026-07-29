from __future__ import annotations

import hashlib
import json
import re
import urllib.error
import urllib.request
from dataclasses import dataclass
from collections.abc import Iterable
from typing import Protocol

import numpy as np


RUSSIAN_SUFFIXES = (
    "иями",
    "ями",
    "ами",
    "ого",
    "ему",
    "ому",
    "ыми",
    "ими",
    "ией",
    "ые",
    "ие",
    "ой",
    "ый",
    "ий",
    "ая",
    "яя",
    "ое",
    "ее",
    "ах",
    "ях",
    "ам",
    "ям",
    "ом",
    "ем",
    "ей",
    "ью",
    "у",
    "ю",
    "а",
    "я",
    "ы",
    "и",
    "е",
    "о",
    "ь",
)


DEFAULT_TOKEN_STOPWORDS = frozenset(
    {
        "a",
        "an",
        "and",
        "are",
        "as",
        "be",
        "for",
        "from",
        "how",
        "is",
        "it",
        "of",
        "or",
        "should",
        "s",
        "that",
        "the",
        "this",
        "to",
        "user",
        "what",
        "which",
        "with",
        "а",
        "без",
        "в",
        "во",
        "где",
        "для",
        "до",
        "его",
        "ее",
        "её",
        "зачем",
        "и",
        "из",
        "или",
        "к",
        "как",
        "какая",
        "какие",
        "каким",
        "каких",
        "какого",
        "какой",
        "каком",
        "какую",
        "кем",
        "ко",
        "когда",
        "лучше",
        "на",
        "но",
        "нужен",
        "нужна",
        "нужно",
        "о",
        "об",
        "он",
        "она",
        "от",
        "по",
        "пользователь",
        "пользователя",
        "почему",
        "при",
        "про",
        "с",
        "со",
        "у",
        "чем",
        "что",
        "это",
    }
)
DEFAULT_SENTENCE_TRANSFORMER_MODEL = (
    "sentence-transformers/paraphrase-multilingual-mpnet-base-v2"
)
DEFAULT_OLLAMA_EMBEDDING_MODEL = "qwen3-embedding:0.6b"


def normalize_token(token: str) -> str:
    token = token.lower().replace("ё", "е")
    if not any("а" <= char <= "я" for char in token):
        return token
    if len(token) <= 4:
        return token
    for suffix in RUSSIAN_SUFFIXES:
        if token.endswith(suffix) and len(token) - len(suffix) >= 4:
            return token[: -len(suffix)]
    return token


def is_stopword_token(token: str) -> bool:
    raw = token.lower().replace("ё", "е")
    return raw in DEFAULT_TOKEN_STOPWORDS or normalize_token(raw) in DEFAULT_TOKEN_STOPWORDS


class TextVectorEncoder(Protocol):
    vector_dim: int

    def encode_vector(self, text: str) -> np.ndarray:
        ...

    def encode_vectors(self, texts: Iterable[str]) -> np.ndarray:
        ...

    def encode_query_vector(self, text: str) -> np.ndarray:
        ...

    def encode_document_vector(self, text: str) -> np.ndarray:
        ...

    def encode_document_vectors(self, texts: Iterable[str]) -> np.ndarray:
        ...


def encode_query_text(encoder: TextVectorEncoder, text: str) -> np.ndarray:
    method = getattr(encoder, "encode_query_vector", None)
    return method(text) if callable(method) else encoder.encode_vector(text)


def encode_document_text(encoder: TextVectorEncoder, text: str) -> np.ndarray:
    method = getattr(encoder, "encode_document_vector", None)
    return method(text) if callable(method) else encoder.encode_vector(text)


def encode_document_batch(
    encoder: TextVectorEncoder,
    texts: Iterable[str],
) -> np.ndarray:
    method = getattr(encoder, "encode_document_vectors", None)
    return method(texts) if callable(method) else encoder.encode_vectors(texts)


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
    stopwords: frozenset[str] = DEFAULT_TOKEN_STOPWORDS

    def encode_vector(self, text: str) -> np.ndarray:
        text = text.lower().strip()
        vector = np.zeros(self.vector_dim, dtype=np.float32)
        if not text:
            return vector

        tokens = []
        for token in re.findall(r"[\w]+", text, flags=re.UNICODE):
            if is_stopword_token(token):
                continue
            normalized = normalize_token(token)
            if normalized not in self.stopwords:
                tokens.append(normalized)
        for token in tokens:
            self._add_feature(vector, f"tok:{token}", self.token_weight)

        if self.char_ngram_weight > 0.0:
            compact = re.sub(r"\s+", " ", text)
            for size in (2, 3):
                for i in range(max(0, len(compact) - size + 1)):
                    self._add_feature(
                        vector,
                        f"ch{size}:{compact[i:i + size]}",
                        self.char_ngram_weight,
                    )

        return _l2_normalize(vector)

    def encode_vectors(self, texts: Iterable[str]) -> np.ndarray:
        vectors = [self.encode_vector(text) for text in texts]
        if not vectors:
            return np.zeros((0, self.vector_dim), dtype=np.float32)
        return np.stack(vectors).astype(np.float32)

    def encode_query_vector(self, text: str) -> np.ndarray:
        return self.encode_vector(text)

    def encode_document_vector(self, text: str) -> np.ndarray:
        return self.encode_vector(text)

    def encode_document_vectors(self, texts: Iterable[str]) -> np.ndarray:
        return self.encode_vectors(texts)

    def _add_feature(self, vector: np.ndarray, feature: str, weight: float) -> None:
        digest = hashlib.blake2b(feature.encode("utf-8"), digest_size=16).digest()
        bucket = int.from_bytes(digest[:8], "little") % self.vector_dim
        sign = 1.0 if digest[8] & 1 else -1.0
        vector[bucket] += sign * weight


class SentenceTransformerTextEncoder:
    def __init__(
        self,
        model_name: str = DEFAULT_SENTENCE_TRANSFORMER_MODEL,
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
        return self.encode_vectors([text])[0]

    def encode_vectors(self, texts: Iterable[str]) -> np.ndarray:
        batch = list(texts)
        if not batch:
            return np.zeros((0, self.vector_dim), dtype=np.float32)
        try:
            encoded = self.model.encode(
                batch,
                normalize_embeddings=True,
                show_progress_bar=False,
            )
        except TypeError:
            encoded = self.model.encode(batch, normalize_embeddings=True)
        vectors = np.asarray(encoded, dtype=np.float32)
        norms = np.linalg.norm(vectors, axis=1, keepdims=True)
        norms = np.where(norms <= 1e-12, 1.0, norms)
        return (vectors / norms).astype(np.float32)

    def encode_query_vector(self, text: str) -> np.ndarray:
        return self.encode_vector(text)

    def encode_document_vector(self, text: str) -> np.ndarray:
        return self.encode_vector(text)

    def encode_document_vectors(self, texts: Iterable[str]) -> np.ndarray:
        return self.encode_vectors(texts)


class OllamaTextEncoder:
    """Explicit local Ollama embedding encoder with asymmetric query prompts."""

    def __init__(
        self,
        model_name: str = DEFAULT_OLLAMA_EMBEDDING_MODEL,
        *,
        base_url: str = "http://127.0.0.1:11434",
        vector_dim: int = 1024,
        batch_size: int = 32,
        timeout_seconds: float = 180.0,
        query_instruction: str = (
            "Given a question about past agent trajectories, retrieve relevant "
            "memory entries that help answer it."
        ),
    ) -> None:
        if not model_name.strip():
            raise ValueError("model_name must not be empty")
        if vector_dim <= 0:
            raise ValueError("vector_dim must be positive")
        if batch_size <= 0:
            raise ValueError("batch_size must be positive")
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")
        self.model_name = model_name.strip()
        self.base_url = base_url.rstrip("/")
        self.vector_dim = int(vector_dim)
        self.batch_size = int(batch_size)
        self.timeout_seconds = float(timeout_seconds)
        self.query_instruction = query_instruction.strip()
        self.cache_key = (
            f"{self.base_url}|{self.model_name}|{self.vector_dim}|"
            f"{self.query_instruction}"
        )
        self._opener = urllib.request.build_opener(
            urllib.request.ProxyHandler({})
        )

    def encode_vector(self, text: str) -> np.ndarray:
        return self.encode_query_vector(text)

    def encode_vectors(self, texts: Iterable[str]) -> np.ndarray:
        return self.encode_document_vectors(texts)

    def encode_query_vector(self, text: str) -> np.ndarray:
        prefix = (
            f"Instruct: {self.query_instruction}\nQuery: "
            if self.query_instruction
            else ""
        )
        return self._embed([f"{prefix}{text}"])[0]

    def encode_document_vector(self, text: str) -> np.ndarray:
        return self._embed([text])[0]

    def encode_document_vectors(self, texts: Iterable[str]) -> np.ndarray:
        batch = list(texts)
        if not batch:
            return np.zeros((0, self.vector_dim), dtype=np.float32)
        vectors = [
            self._embed(batch[offset : offset + self.batch_size])
            for offset in range(0, len(batch), self.batch_size)
        ]
        return np.concatenate(vectors, axis=0).astype(np.float32)

    def _embed(self, texts: list[str]) -> np.ndarray:
        payload = json.dumps(
            {
                "model": self.model_name,
                "input": texts,
                "truncate": True,
            }
        ).encode("utf-8")
        request = urllib.request.Request(
            f"{self.base_url}/api/embed",
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with self._opener.open(
                request,
                timeout=self.timeout_seconds,
            ) as response:
                body = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(
                f"Ollama HTTP {exc.code} for embedding model "
                f"{self.model_name}: {detail}"
            ) from exc
        except (OSError, urllib.error.URLError) as exc:
            raise RuntimeError(
                f"Ollama embedding request failed for {self.model_name}: {exc}"
            ) from exc
        embeddings = np.asarray(body.get("embeddings"), dtype=np.float32)
        expected_shape = (len(texts), self.vector_dim)
        if embeddings.shape != expected_shape:
            raise RuntimeError(
                "Ollama embedding response shape "
                f"{embeddings.shape}, expected {expected_shape}"
            )
        norms = np.linalg.norm(embeddings, axis=1, keepdims=True)
        norms = np.where(norms <= 1e-12, 1.0, norms)
        return (embeddings / norms).astype(np.float32)

class FieldProjector:
    def __init__(
        self,
        width: int,
        height: int,
        vector_dim: int,
        seed: int = 1729,
        features_per_cell: int = 16,
    ):
        self.width = int(width)
        self.height = int(height)
        self.vector_dim = int(vector_dim)
        self.seed = int(seed + self.width * 31 + self.height * 17 + self.vector_dim)
        self.features_per_cell = max(1, min(int(features_per_cell), self.vector_dim))
        rng = np.random.default_rng(self.seed)
        shape = (self.height * self.width, self.features_per_cell)
        self._indices = rng.integers(
            0,
            self.vector_dim,
            size=shape,
            dtype=np.int32,
        )
        self._weights = rng.normal(
            loc=0.0,
            scale=1.0 / max(1, self.features_per_cell) ** 0.5,
            size=shape,
        ).astype(np.float32)

    def to_pattern(self, vector: np.ndarray) -> np.ndarray:
        vector = _l2_normalize(vector)
        projected = (vector[self._indices] * self._weights).sum(axis=1, dtype=np.float32)
        raw = projected.copy()
        np.maximum(projected, 0.0, out=projected)
        if not np.any(projected):
            projected = np.abs(raw)
        pattern = projected.reshape(self.height, self.width).astype(np.float32)
        return _l2_normalize(pattern)


TextEncoder = HashingTextEncoder


def create_text_encoder(
    kind: str = "hash",
    vector_dim: int = 384,
    model_name: str | None = None,
    base_url: str = "http://127.0.0.1:11434",
) -> TextVectorEncoder:
    kind = (kind or "hash").lower()
    if kind == "hash":
        return HashingTextEncoder(vector_dim=vector_dim)
    if kind in {"sentence", "sentence-transformers", "transformer"}:
        return SentenceTransformerTextEncoder(
            model_name=model_name or DEFAULT_SENTENCE_TRANSFORMER_MODEL
        )
    if kind == "ollama":
        return OllamaTextEncoder(
            model_name=model_name or DEFAULT_OLLAMA_EMBEDDING_MODEL,
            base_url=base_url,
            vector_dim=vector_dim,
        )
    raise ValueError(
        "Unknown encoder kind: "
        f"{kind}. Choose an explicit encoder: hash, sentence, or ollama."
    )
