from __future__ import annotations

import hashlib
import inspect
import math
import re
from contextlib import nullcontext
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any, Callable, ContextManager, Iterable, Mapping, Sequence

import numpy as np

from ._openshape_pointbert import (
    OPENSHAPE_MODEL_NAME,
    OPENSHAPE_MODEL_REVISION,
    OPENSHAPE_VECTOR_DIM,
    load_openshape_pointbert,
)
from .multimodal import (
    CrossModalEmbeddingSpace,
    CrossModalMemoryLayer,
    CrossModalQueryResult,
    CrossModalSpaceError,
    CrossModalSpaceMismatchError,
    CrossModalSpaceRegistry,
    MemoryPayload,
    _rank_group_confidence,
    normalize_modality,
)


DEFAULT_TEXT_MODEL = "sentence-transformers/paraphrase-multilingual-mpnet-base-v2"
DEFAULT_TEXT_REVISION = "4328cf26390c98c5e3c738b4460a05b95f4911f5"
DEFAULT_CLIP_MODEL = "sentence-transformers/clip-ViT-B-32"
DEFAULT_CLIP_REVISION = "327ab6726d33c0e22f920c83f2ff9e4bd38ca37f"
DEFAULT_CLAP_MODEL = "laion/clap-htsat-unfused"
DEFAULT_CLAP_REVISION = "8fa0f1c6d0433df6e97c127f64b2a1d6c0dcda8a"

_REVISION_RE = re.compile(r"^[0-9a-f]{40}$")
_VECTOR_KEYS = frozenset(
    {
        "cross_modal_vector",
        "cross_modal_embedding",
        "embedding",
        "vector",
    }
)


class LocalMultimodalBackendError(RuntimeError):
    """Raised when a required local model or decoder is unavailable."""


class LocalMediaInputError(ValueError):
    """Raised when a real media payload cannot be decoded from its content."""


@dataclass(frozen=True)
class LocalMultimodalQueryPart:
    modality: str
    text: str = ""
    uri: str | Path | None = None
    weight: float = 1.0
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        modality = normalize_modality(self.modality)
        if modality not in {"text", "image", "audio", "video", "3d"}:
            raise ValueError(f"Unsupported local query modality `{modality}`.")
        if not math.isfinite(float(self.weight)) or float(self.weight) <= 0.0:
            raise ValueError("Local multimodal query-part weight must be positive.")
        if modality == "text" and not str(self.text).strip():
            raise ValueError("Text query parts require non-empty text.")
        if modality != "text" and self.uri is None:
            raise ValueError(f"`{modality}` query parts require a local content URI.")
        object.__setattr__(self, "modality", modality)
        object.__setattr__(self, "weight", float(self.weight))
        object.__setattr__(self, "metadata", dict(self.metadata))


class LocalSentenceTextEncoder:
    """Pinned local sentence-transformers backend for semantic text memory."""

    def __init__(
        self,
        model_name: str = DEFAULT_TEXT_MODEL,
        *,
        model_revision: str = DEFAULT_TEXT_REVISION,
        model: Any | None = None,
        vector_dim: int | None = None,
        cache_folder: str | Path | None = None,
        local_files_only: bool = False,
    ) -> None:
        _require_pinned_revision(model_revision)
        self.model_name = str(model_name)
        self.model_revision = str(model_revision)
        self.model = model or _load_sentence_transformer(
            self.model_name,
            revision=self.model_revision,
            cache_folder=cache_folder,
            local_files_only=local_files_only,
        )
        self.vector_dim = int(vector_dim or _sentence_model_dimension(self.model))
        if self.vector_dim <= 0:
            raise LocalMultimodalBackendError(
                f"Text model `{self.model_name}` did not expose a positive vector dimension."
            )
        self.name = f"sentence-transformers/{self.model_name}"
        self.embedding_space = CrossModalEmbeddingSpace(
            space_id=f"text:{self.model_name}@{self.model_revision}",
            vector_dim=self.vector_dim,
            modalities=("text",),
            encoder_name=self.name,
            model_revision=self.model_revision,
            production_eligible=True,
        )

    def encode_payload(self, payload: MemoryPayload, descriptor: str) -> np.ndarray:
        self.embedding_space.require_modality(payload.kind)
        _reject_vector_shortcut(payload.metadata, backend=self.name)
        text = str(payload.text).strip()
        if not text:
            raise LocalMediaInputError("Text payload content must not be empty.")
        return _encode_sentence_values(self.model, [text], vector_dim=self.vector_dim)[0]

    def encode_query(
        self,
        query: str,
        *,
        target_modality: str | None,
        descriptor: str,
    ) -> np.ndarray:
        if target_modality:
            self.embedding_space.require_modality(target_modality)
        text = str(query).strip()
        if not text:
            raise LocalMediaInputError("Text query must not be empty.")
        return _encode_sentence_values(self.model, [text], vector_dim=self.vector_dim)[0]

    def encode_payloads(
        self,
        payloads: Sequence[MemoryPayload],
    ) -> list[np.ndarray]:
        selected = tuple(payloads)
        texts: list[str] = []
        for payload in selected:
            self.embedding_space.require_modality(payload.kind)
            _reject_vector_shortcut(payload.metadata, backend=self.name)
            text = str(payload.text).strip()
            if not text:
                raise LocalMediaInputError("Text payload content must not be empty.")
            texts.append(text)
        if not texts:
            return []
        matrix = _encode_sentence_values(
            self.model,
            texts,
            vector_dim=self.vector_dim,
        )
        return [matrix[index] for index in range(len(texts))]


class LocalClipMediaEncoder:
    """Pinned CLIP backend for text, image, sampled video, and rendered 3D geometry."""

    def __init__(
        self,
        model_name: str = DEFAULT_CLIP_MODEL,
        *,
        model_revision: str = DEFAULT_CLIP_REVISION,
        model: Any | None = None,
        vector_dim: int | None = None,
        cache_folder: str | Path | None = None,
        local_files_only: bool = False,
        image_loader: Callable[[Path], Any] | None = None,
        video_frame_loader: Callable[[Path, int], Sequence[Any]] | None = None,
        mesh_view_renderer: Callable[[Path, int], Sequence[Any]] | None = None,
        pointcloud_model: Any | None = None,
        pointcloud_loader: Callable[..., Any] | None = None,
        use_openshape_3d: bool = True,
        video_frame_count: int = 8,
        mesh_view_count: int = 6,
        pointcloud_size: int = 4096,
        pointcloud_batch_size: int = 4,
    ) -> None:
        _require_pinned_revision(model_revision)
        if (
            video_frame_count <= 0
            or mesh_view_count <= 0
            or pointcloud_size <= 0
            or pointcloud_batch_size <= 0
        ):
            raise ValueError("Media sample counts and batch sizes must be positive.")
        self.model_name = str(model_name)
        self.model_revision = str(model_revision)
        self.model = model or _load_sentence_transformer(
            self.model_name,
            revision=self.model_revision,
            cache_folder=cache_folder,
            local_files_only=local_files_only,
        )
        self.vector_dim = int(vector_dim or _sentence_model_dimension(self.model))
        if self.vector_dim <= 0:
            raise LocalMultimodalBackendError(
                f"CLIP model `{self.model_name}` did not expose a positive vector dimension."
            )
        if (
            use_openshape_3d
            and pointcloud_model is None
            and (
                self.model_name != DEFAULT_CLIP_MODEL
                or self.model_revision != DEFAULT_CLIP_REVISION
                or self.vector_dim != OPENSHAPE_VECTOR_DIM
            )
        ):
            raise LocalMultimodalBackendError(
                "The bundled OpenShape checkpoint is aligned only with "
                f"`{DEFAULT_CLIP_MODEL}@{DEFAULT_CLIP_REVISION}` "
                f"({OPENSHAPE_VECTOR_DIM} dimensions). Supply a compatible "
                "pointcloud_model explicitly for a custom CLIP space."
            )
        self.image_loader = image_loader or _load_image
        self.video_frame_loader = video_frame_loader or _load_video_frames
        self.mesh_view_renderer = mesh_view_renderer or _render_mesh_views
        self.pointcloud_model = pointcloud_model
        self.pointcloud_loader = pointcloud_loader or load_openshape_pointbert
        self.use_openshape_3d = bool(use_openshape_3d)
        self.cache_folder = str(cache_folder) if cache_folder is not None else None
        self.local_files_only = bool(local_files_only)
        self.video_frame_count = int(video_frame_count)
        self.mesh_view_count = int(mesh_view_count)
        self.pointcloud_size = int(pointcloud_size)
        self.pointcloud_batch_size = int(pointcloud_batch_size)
        backend_suffix = (
            f"+openshape/{OPENSHAPE_MODEL_NAME}"
            if self.use_openshape_3d
            else ""
        )
        revision_suffix = (
            f"+{OPENSHAPE_MODEL_REVISION}" if self.use_openshape_3d else ""
        )
        self.name = f"clip/{self.model_name}{backend_suffix}"
        self.embedding_space = CrossModalEmbeddingSpace(
            space_id=(
                f"clip:{self.model_name}@{self.model_revision}"
                f"{revision_suffix}"
            ),
            vector_dim=self.vector_dim,
            modalities=("text", "image", "video", "3d"),
            encoder_name=self.name,
            model_revision=f"{self.model_revision}{revision_suffix}",
            production_eligible=True,
        )

    def encode_payload(self, payload: MemoryPayload, descriptor: str) -> np.ndarray:
        modality = self.embedding_space.require_modality(payload.kind)
        _reject_vector_shortcut(payload.metadata, backend=self.name)
        if modality == "text":
            text = str(payload.text).strip()
            if not text:
                raise LocalMediaInputError("CLIP text payload content must not be empty.")
            values: Sequence[Any] = _clip_text_views(text)
        else:
            path = _require_local_media_path(payload.metadata.get("uri"), modality=modality)
            if modality == "image":
                values = (self.image_loader(path),)
            elif modality == "video":
                values = tuple(self.video_frame_loader(path, self.video_frame_count))
            elif self.use_openshape_3d:
                return self._encode_pointcloud_paths((path,))[0]
            else:
                values = tuple(self.mesh_view_renderer(path, self.mesh_view_count))
            if not values:
                raise LocalMediaInputError(
                    f"`{modality}` payload `{path}` produced no decodable content."
                )
        vectors = _encode_sentence_values(self.model, values, vector_dim=self.vector_dim)
        if modality == "text":
            return _weighted_mean_vectors(
                vectors,
                _clip_text_view_weights(text),
                vector_dim=self.vector_dim,
            )
        return _mean_unit_vectors(vectors, vector_dim=self.vector_dim)

    def encode_query(
        self,
        query: str,
        *,
        target_modality: str | None,
        descriptor: str,
    ) -> np.ndarray:
        if target_modality:
            self.embedding_space.require_modality(target_modality)
        text = str(query).strip()
        if not text:
            raise LocalMediaInputError("CLIP text query must not be empty.")
        vectors = _encode_sentence_values(
            self.model,
            _clip_query_views(text, target_modality=target_modality),
            vector_dim=self.vector_dim,
        )
        return _mean_unit_vectors(vectors, vector_dim=self.vector_dim)

    def encode_payloads(
        self,
        payloads: Sequence[MemoryPayload],
    ) -> list[np.ndarray]:
        selected = tuple(payloads)
        if not selected:
            return []
        if self.use_openshape_3d and any(
            normalize_modality(payload.kind) == "3d" for payload in selected
        ):
            return self._encode_mixed_payload_batch(selected)
        flattened: list[Any] = []
        spans: list[tuple[int, int, tuple[float, ...] | None]] = []
        for payload in selected:
            values = self._payload_values(payload)
            start = len(flattened)
            flattened.extend(values)
            weights = (
                _clip_text_view_weights(payload.text)
                if normalize_modality(payload.kind) == "text"
                else None
            )
            spans.append((start, len(flattened), weights))
        matrix = _encode_sentence_values(
            self.model,
            flattened,
            vector_dim=self.vector_dim,
        )
        return [
            (
                _weighted_mean_vectors(
                    matrix[start:end],
                    weights,
                    vector_dim=self.vector_dim,
                )
                if weights is not None
                else _mean_unit_vectors(
                    matrix[start:end],
                    vector_dim=self.vector_dim,
                )
            )
            for start, end, weights in spans
        ]

    def _encode_mixed_payload_batch(
        self,
        payloads: Sequence[MemoryPayload],
    ) -> list[np.ndarray]:
        results: list[np.ndarray | None] = [None] * len(payloads)
        standard_rows = []
        pointcloud_rows = []
        for index, payload in enumerate(payloads):
            modality = self.embedding_space.require_modality(payload.kind)
            if modality == "3d":
                _reject_vector_shortcut(payload.metadata, backend=self.name)
                pointcloud_rows.append(
                    (
                        index,
                        _require_local_media_path(
                            payload.metadata.get("uri"),
                            modality="3d",
                        ),
                    )
                )
            else:
                standard_rows.append((index, payload))
        if standard_rows:
            standard_vectors = self.encode_payloads(
                [payload for _, payload in standard_rows]
            )
            for (index, _), vector in zip(
                standard_rows,
                standard_vectors,
                strict=True,
            ):
                results[index] = vector
        if pointcloud_rows:
            vectors = self._encode_pointcloud_paths(
                [path for _, path in pointcloud_rows]
            )
            for (index, _), vector in zip(
                pointcloud_rows,
                vectors,
                strict=True,
            ):
                results[index] = vector
        if any(vector is None for vector in results):
            raise LocalMultimodalBackendError(
                "CLIP/OpenShape batch encoding did not produce one vector per payload."
            )
        return [vector for vector in results if vector is not None]

    def _encode_pointcloud_paths(
        self,
        paths: Sequence[Path],
    ) -> list[np.ndarray]:
        try:
            import torch
        except ImportError as exc:
            raise LocalMultimodalBackendError(
                "OpenShape 3D encoding requires torch."
            ) from exc
        if self.pointcloud_model is None:
            try:
                self.pointcloud_model = self.pointcloud_loader(
                    cache_folder=self.cache_folder,
                    local_files_only=self.local_files_only,
                )
            except Exception as exc:
                raise LocalMultimodalBackendError(
                    "Could not load the pinned OpenShape PointBERT backend."
                ) from exc
        model = self.pointcloud_model
        try:
            device = next(model.parameters()).device
        except (AttributeError, StopIteration):
            device = torch.device("cpu")
        vectors: list[np.ndarray] = []
        for offset in range(0, len(paths), self.pointcloud_batch_size):
            selected = paths[offset : offset + self.pointcloud_batch_size]
            pointclouds = np.stack(
                [
                    _sample_mesh_pointcloud(
                        path,
                        point_count=self.pointcloud_size,
                    )
                    for path in selected
                ],
                axis=0,
            )
            inputs = torch.from_numpy(pointclouds).permute(0, 2, 1).to(device)
            with _torch_inference_context():
                encoded = model(inputs)
            matrix = _feature_matrix(
                encoded,
                vector_dim=self.vector_dim,
                expected_rows=len(selected),
            )
            vectors.extend(matrix)
        return vectors

    def _payload_values(self, payload: MemoryPayload) -> tuple[Any, ...]:
        modality = self.embedding_space.require_modality(payload.kind)
        _reject_vector_shortcut(payload.metadata, backend=self.name)
        if modality == "text":
            text = str(payload.text).strip()
            if not text:
                raise LocalMediaInputError("CLIP text payload content must not be empty.")
            return _clip_text_views(text)
        path = _require_local_media_path(payload.metadata.get("uri"), modality=modality)
        if modality == "image":
            values = (self.image_loader(path),)
        elif modality == "video":
            values = tuple(self.video_frame_loader(path, self.video_frame_count))
        else:
            values = tuple(self.mesh_view_renderer(path, self.mesh_view_count))
        if not values:
            raise LocalMediaInputError(
                f"`{modality}` payload `{path}` produced no decodable content."
            )
        return values


class LocalClapAudioEncoder:
    """Pinned CLAP backend that embeds real local audio and text in one space."""

    def __init__(
        self,
        model_name: str = DEFAULT_CLAP_MODEL,
        *,
        model_revision: str = DEFAULT_CLAP_REVISION,
        model: Any | None = None,
        processor: Any | None = None,
        vector_dim: int | None = None,
        cache_folder: str | Path | None = None,
        local_files_only: bool = False,
        audio_loader: Callable[[Path], tuple[np.ndarray, int]] | None = None,
        inference_context: Callable[[], ContextManager[Any]] | None = None,
    ) -> None:
        _require_pinned_revision(model_revision)
        self.model_name = str(model_name)
        self.model_revision = str(model_revision)
        if model is None or processor is None:
            loaded_model, loaded_processor = _load_clap(
                self.model_name,
                revision=self.model_revision,
                cache_folder=cache_folder,
                local_files_only=local_files_only,
            )
            model = model or loaded_model
            processor = processor or loaded_processor
        self.model = model
        self.processor = processor
        evaluator = getattr(self.model, "eval", None)
        if callable(evaluator):
            evaluator()
        self.audio_loader = audio_loader or _load_audio
        self.inference_context = inference_context or _torch_inference_context
        self.vector_dim = int(vector_dim or _clap_dimension(self.model))
        if self.vector_dim <= 0:
            raise LocalMultimodalBackendError(
                f"CLAP model `{self.model_name}` did not expose a positive vector dimension."
            )
        self.name = f"clap/{self.model_name}"
        self.embedding_space = CrossModalEmbeddingSpace(
            space_id=f"clap:{self.model_name}@{self.model_revision}",
            vector_dim=self.vector_dim,
            modalities=("text", "audio"),
            encoder_name=self.name,
            model_revision=self.model_revision,
            production_eligible=True,
        )

    def encode_payload(self, payload: MemoryPayload, descriptor: str) -> np.ndarray:
        modality = self.embedding_space.require_modality(payload.kind)
        _reject_vector_shortcut(payload.metadata, backend=self.name)
        if modality == "text":
            return self._encode_text(_audio_text_view(payload.text))
        path = _require_local_media_path(payload.metadata.get("uri"), modality="audio")
        samples, sampling_rate = self.audio_loader(path)
        samples = _mono_float_audio(samples)
        target_rate = _processor_sampling_rate(self.processor)
        if int(sampling_rate) != target_rate:
            samples = _resample_audio(samples, int(sampling_rate), target_rate)
        inputs = _processor_call(
            self.processor,
            modality="audio",
            value=[samples],
            sampling_rate=target_rate,
        )
        with self.inference_context():
            vector = self.model.get_audio_features(**inputs)
        return _feature_vector(vector, vector_dim=self.vector_dim)

    def encode_query(
        self,
        query: str,
        *,
        target_modality: str | None,
        descriptor: str,
    ) -> np.ndarray:
        if target_modality:
            self.embedding_space.require_modality(target_modality)
        return self._encode_text(_audio_text_view(query))

    def _encode_text(self, text: str) -> np.ndarray:
        normalized = str(text).strip()
        if not normalized:
            raise LocalMediaInputError("CLAP text input must not be empty.")
        inputs = _processor_call(self.processor, modality="text", value=[normalized])
        with self.inference_context():
            vector = self.model.get_text_features(**inputs)
        return _feature_vector(vector, vector_dim=self.vector_dim)

    def encode_payloads(
        self,
        payloads: Sequence[MemoryPayload],
    ) -> list[np.ndarray]:
        selected = tuple(payloads)
        if not selected:
            return []
        results: list[np.ndarray | None] = [None] * len(selected)
        text_rows: list[tuple[int, str]] = []
        audio_rows: list[tuple[int, np.ndarray]] = []
        target_rate = _processor_sampling_rate(self.processor)
        for index, payload in enumerate(selected):
            modality = self.embedding_space.require_modality(payload.kind)
            _reject_vector_shortcut(payload.metadata, backend=self.name)
            if modality == "text":
                text = str(payload.text).strip()
                if not text:
                    raise LocalMediaInputError("CLAP text input must not be empty.")
                text_rows.append((index, _audio_text_view(text)))
                continue
            path = _require_local_media_path(payload.metadata.get("uri"), modality="audio")
            samples, sampling_rate = self.audio_loader(path)
            samples = _mono_float_audio(samples)
            if int(sampling_rate) != target_rate:
                samples = _resample_audio(samples, int(sampling_rate), target_rate)
            audio_rows.append((index, samples))

        if text_rows:
            inputs = _processor_call(
                self.processor,
                modality="text",
                value=[text for _, text in text_rows],
            )
            with self.inference_context():
                matrix = self.model.get_text_features(**inputs)
            vectors = _feature_matrix(
                matrix,
                vector_dim=self.vector_dim,
                expected_rows=len(text_rows),
            )
            for row, vector in zip(text_rows, vectors, strict=True):
                results[row[0]] = vector
        if audio_rows:
            inputs = _processor_call(
                self.processor,
                modality="audio",
                value=[samples for _, samples in audio_rows],
                sampling_rate=target_rate,
            )
            with self.inference_context():
                matrix = self.model.get_audio_features(**inputs)
            vectors = _feature_matrix(
                matrix,
                vector_dim=self.vector_dim,
                expected_rows=len(audio_rows),
            )
            for row, vector in zip(audio_rows, vectors, strict=True):
                results[row[0]] = vector
        if any(vector is None for vector in results):
            raise LocalMultimodalBackendError(
                "CLAP batch encoding did not produce one vector per payload."
            )
        return [vector for vector in results if vector is not None]


class LocalMultimodalMemory:
    """Routes real local content through compatible spaces and fuses only ranks."""

    _REQUIRED_MODALITIES = ("text", "image", "audio", "video", "3d")

    def __init__(
        self,
        memory: Any,
        *,
        text_encoder: LocalSentenceTextEncoder,
        visual_encoder: LocalClipMediaEncoder,
        audio_encoder: LocalClapAudioEncoder,
        modality_weights: Mapping[str, float] | None = None,
        rrf_k: int = 60,
    ) -> None:
        if rrf_k < 1:
            raise ValueError("rrf_k must be at least 1.")
        self.memory = memory
        self.rrf_k = int(rrf_k)
        self.encoders = {
            "text": text_encoder,
            "image": visual_encoder,
            "video": visual_encoder,
            "3d": visual_encoder,
            "audio": audio_encoder,
        }
        registry = CrossModalSpaceRegistry(
            {
                encoder.embedding_space.space_id: encoder.embedding_space
                for encoder in self.encoders.values()
            }.values()
        )
        self.layers = {
            space_id: CrossModalMemoryLayer(
                memory,
                cross_modal_encoder=encoder,
                space_registry=registry,
                base_weight=0.0,
                cross_modal_weight=1.0,
                modality_weight=0.0,
            )
            for space_id, encoder in {
                encoder.embedding_space.space_id: encoder
                for encoder in self.encoders.values()
            }.items()
        }
        supplied_weights = {
            normalize_modality(key): float(value)
            for key, value in (modality_weights or {}).items()
        }
        self.modality_weights: dict[str, float] = {}
        for modality in self._REQUIRED_MODALITIES:
            weight = supplied_weights.get(modality, 1.0)
            if not math.isfinite(weight) or weight <= 0.0:
                raise ValueError(f"Weight for modality `{modality}` must be positive.")
            self.modality_weights[modality] = weight

    @property
    def spaces(self) -> dict[str, dict[str, Any]]:
        return {
            layer.space_id: layer.embedding_space.as_dict()
            for layer in self.layers.values()
        }

    def remember(
        self,
        payload: MemoryPayload,
        *,
        namespace: str = "default",
        ttl_seconds: float | None = None,
        priority: float = 1.0,
        metadata: dict[str, Any] | None = None,
    ) -> int:
        modality = normalize_modality(payload.kind)
        if modality == "text":
            return self._remember_text_across_spaces(
                payload,
                namespace=namespace,
                ttl_seconds=ttl_seconds,
                priority=priority,
                metadata=metadata,
            )
        encoder = self._encoder_for(modality)
        return self.layers[encoder.embedding_space.space_id].remember(
            payload,
            namespace=namespace,
            ttl_seconds=ttl_seconds,
            priority=priority,
            metadata=metadata,
        )

    def forget(self, logical_memory_id: int, *, namespace: str = "default") -> int:
        records = self.memory.store.list(namespace=namespace, tags=["multimodal"])
        physical_ids = [
            int(record.id)
            for record in records
            if record.id is not None
            and (
                int(record.id) == int(logical_memory_id)
                or _logical_memory_id(record.id, record.metadata)
                == int(logical_memory_id)
            )
        ]
        deleted = 0
        for physical_id in dict.fromkeys(physical_ids):
            deleted += int(self.memory.forget(id=physical_id, namespace=namespace))
        return deleted

    def query(
        self,
        query: str,
        *,
        namespace: str = "default",
        top_k: int = 3,
        target_modalities: Iterable[str] | None = None,
        candidate_k: int | None = None,
        min_score: float | None = None,
    ) -> list[CrossModalQueryResult]:
        modalities = self._modalities(target_modalities)
        groups: list[tuple[str, str, float, Sequence[CrossModalQueryResult]]] = []
        for modality in modalities:
            encoder = self._encoder_for(modality)
            layer = self.layers[encoder.embedding_space.space_id]
            results = layer.query(
                query,
                namespace=namespace,
                top_k=max(candidate_k or top_k * 4, top_k),
                target_modality=modality,
                candidate_k=candidate_k,
            )
            groups.append(
                (
                    encoder.embedding_space.space_id,
                    modality,
                    self.modality_weights[modality],
                    results,
                )
            )
        return self._rank_fuse(groups, top_k=top_k, min_score=min_score)

    def query_mixed(
        self,
        parts: Sequence[LocalMultimodalQueryPart],
        *,
        namespace: str = "default",
        top_k: int = 3,
        target_modalities: Iterable[str] | None = None,
        candidate_k: int | None = None,
        min_score: float | None = None,
    ) -> list[CrossModalQueryResult]:
        selected = tuple(parts)
        if not selected:
            raise ValueError("Mixed multimodal query requires at least one part.")
        modalities = self._modalities(target_modalities)
        query_label = " | ".join(part.text for part in selected if part.text.strip())
        groups: list[tuple[str, str, float, Sequence[CrossModalQueryResult]]] = []
        for modality in modalities:
            for encoder in self._query_encoders_for(modality, selected):
                compatible = [
                    part
                    for part in selected
                    if part.modality == "text"
                    or self._encoder_for(part.modality).embedding_space.space_id
                    == encoder.embedding_space.space_id
                ]
                if not compatible:
                    continue
                vectors: list[np.ndarray] = []
                weights: list[float] = []
                part_details: list[dict[str, Any]] = []
                for part in compatible:
                    if part.modality == "text":
                        vector = encoder.encode_query(
                            part.text,
                            target_modality=modality,
                            descriptor=part.text,
                        )
                    else:
                        vector = encoder.encode_payload(
                            MemoryPayload(
                                kind=part.modality,
                                text=part.text,
                                metadata={**part.metadata, "uri": str(part.uri)},
                            ),
                            "",
                        )
                    vectors.append(_unit_vector(vector, vector_dim=encoder.vector_dim))
                    weights.append(part.weight)
                    part_details.append(
                        {
                            "modality": part.modality,
                            "weight": part.weight,
                            "space_id": encoder.embedding_space.space_id,
                            "source": "real_local_encoder",
                        }
                    )
                fused_vector = _weighted_mean_vectors(
                    vectors,
                    weights,
                    vector_dim=encoder.vector_dim,
                )
                layer = self.layers[encoder.embedding_space.space_id]
                results = layer.query(
                    query_label or "mixed local multimodal query",
                    namespace=namespace,
                    top_k=max(candidate_k or top_k * 4, top_k),
                    target_modality=modality,
                    candidate_k=candidate_k,
                    query_vector=fused_vector,
                    query_space_id=encoder.embedding_space.space_id,
                )
                results = [
                    replace(
                        result,
                        fusion={
                            "strategy": "within_space_normalized_weighted_sum",
                            "space_id": encoder.embedding_space.space_id,
                            "parts": part_details,
                            "incompatible_spaces_compared": False,
                        },
                    )
                    for result in results
                ]
                groups.append(
                    (
                        encoder.embedding_space.space_id,
                        modality,
                        self.modality_weights[modality],
                        results,
                    )
                )
        return self._rank_fuse(groups, top_k=top_k, min_score=min_score)

    def _remember_text_across_spaces(
        self,
        payload: MemoryPayload,
        *,
        namespace: str,
        ttl_seconds: float | None,
        priority: float,
        metadata: dict[str, Any] | None,
    ) -> int:
        merged_metadata = {**payload.metadata, **(metadata or {})}
        if "cross_modal_space_id" in merged_metadata:
            raise CrossModalSpaceMismatchError(
                "LocalMultimodalMemory controls text projection spaces; callers "
                "must not force one cross_modal_space_id."
            )
        text_encoder = self.encoders["text"]
        text_layer = self.layers[text_encoder.embedding_space.space_id]
        created: list[int] = []
        try:
            primary_id = text_layer.remember(
                payload,
                namespace=namespace,
                ttl_seconds=ttl_seconds,
                priority=priority,
                metadata=metadata,
            )
            created.append(primary_id)
            projection_encoders = {
                encoder.embedding_space.space_id: encoder
                for modality, encoder in self.encoders.items()
                if modality != "text"
                and "text" in encoder.embedding_space.modalities
            }
            for space_id, encoder in projection_encoders.items():
                projection_id = self.layers[space_id].remember(
                    payload,
                    namespace=namespace,
                    ttl_seconds=ttl_seconds,
                    priority=priority,
                    metadata={
                        **(metadata or {}),
                        "logical_memory_id": primary_id,
                        "derived_from_memory_id": primary_id,
                        "derived_memory_type": "cross_space_text_projection",
                        "derived_encoder": encoder.name,
                    },
                )
                created.append(projection_id)
            return primary_id
        except Exception:
            for memory_id in reversed(created):
                self.memory.forget(id=memory_id, namespace=namespace)
            raise

    def _query_encoders_for(
        self,
        target_modality: str,
        parts: Sequence[LocalMultimodalQueryPart],
    ) -> tuple[Any, ...]:
        if target_modality != "text":
            return (self._encoder_for(target_modality),)
        non_text = tuple(part for part in parts if part.modality != "text")
        if not non_text:
            return (self.encoders["text"],)
        return tuple(
            {
                self._encoder_for(part.modality).embedding_space.space_id: self._encoder_for(
                    part.modality
                )
                for part in non_text
                if "text" in self._encoder_for(part.modality).embedding_space.modalities
            }.values()
        )

    def _encoder_for(self, modality: str) -> Any:
        normalized = normalize_modality(modality)
        try:
            return self.encoders[normalized]
        except KeyError as exc:
            raise CrossModalSpaceError(
                f"No real local encoder is registered for modality `{normalized}`."
            ) from exc

    def _modalities(self, values: Iterable[str] | None) -> tuple[str, ...]:
        selected = tuple(
            dict.fromkeys(
                normalize_modality(value)
                for value in (values or self._REQUIRED_MODALITIES)
            )
        )
        if not selected:
            raise ValueError("At least one target modality is required.")
        for modality in selected:
            self._encoder_for(modality)
        return selected

    def _rank_fuse(
        self,
        groups: Sequence[
            tuple[str, str, float, Sequence[CrossModalQueryResult]]
        ],
        *,
        top_k: int,
        min_score: float | None,
    ) -> list[CrossModalQueryResult]:
        if top_k <= 0:
            return []
        active = [group for group in groups if group[3]]
        if not active:
            return []
        weighted_groups = [
            (
                space_id,
                modality,
                raw_weight,
                _rank_group_confidence(results),
                results,
            )
            for space_id, modality, raw_weight, results in active
        ]
        total_weight = sum(
            raw_weight * confidence
            for _, _, raw_weight, confidence, _ in weighted_groups
        )
        if total_weight <= 0.0:
            return []
        by_id: dict[int, CrossModalQueryResult] = {}
        scores: dict[int, float] = {}
        contributions: dict[int, list[dict[str, Any]]] = {}
        for space_id, modality, raw_weight, confidence, results in weighted_groups:
            normalized_weight = raw_weight * confidence / total_weight
            for rank, result in enumerate(results, start=1):
                logical_id = _logical_memory_id(result.id, result.metadata)
                rrf_factor = (self.rrf_k + 1.0) / (self.rrf_k + float(rank))
                contribution = normalized_weight * rrf_factor
                current = by_id.get(logical_id)
                if current is None or result.cross_modal_score > current.cross_modal_score:
                    by_id[logical_id] = replace(
                        result,
                        id=logical_id,
                        metadata={
                            **result.metadata,
                            "logical_memory_id": logical_id,
                            "embedding_record_id": result.id,
                        },
                    )
                scores[logical_id] = scores.get(logical_id, 0.0) + contribution
                contributions.setdefault(logical_id, []).append(
                    {
                        "space_id": space_id,
                        "target_modality": modality,
                        "rank": rank,
                        "group_confidence": confidence,
                        "normalized_modality_weight": normalized_weight,
                        "rrf_factor": rrf_factor,
                        "contribution": contribution,
                        "raw_space_score": result.score,
                    }
                )
        fused: list[CrossModalQueryResult] = []
        for memory_id, score in scores.items():
            if min_score is not None and score < min_score:
                continue
            result = by_id[memory_id]
            prior_fusion = dict(result.fusion)
            fused.append(
                replace(
                    result,
                    score=float(score),
                    fusion={
                        "strategy": "confidence_weighted_reciprocal_rank",
                        "rrf_k": self.rrf_k,
                        "score": float(score),
                        "contributions": contributions[memory_id],
                        "within_space": prior_fusion,
                        "incompatible_spaces_compared": False,
                    },
                )
            )
        fused.sort(key=lambda item: (item.score, item.cross_modal_score), reverse=True)
        return fused[:top_k]


def _require_pinned_revision(revision: str) -> None:
    normalized = str(revision).strip().lower()
    if not _REVISION_RE.fullmatch(normalized):
        raise ValueError(
            "Production local encoder revisions must be exact 40-character "
            "Hugging Face commit SHAs."
        )


def _logical_memory_id(memory_id: Any, metadata: Mapping[str, Any]) -> int:
    for key in ("logical_memory_id", "derived_from_memory_id"):
        value = metadata.get(key)
        if value is not None:
            try:
                return int(value)
            except (TypeError, ValueError):
                raise LocalMultimodalBackendError(
                    f"Invalid `{key}` value on cross-space projection: {value!r}."
                ) from None
    return int(memory_id)


def _reject_vector_shortcut(metadata: Mapping[str, Any], *, backend: str) -> None:
    present = sorted(key for key in _VECTOR_KEYS if key in metadata)
    if present:
        raise LocalMediaInputError(
            f"Real backend `{backend}` rejects precomputed vector fields "
            f"({', '.join(present)}); use PrecomputedCrossModalEncoder explicitly."
        )


def _load_sentence_transformer(
    model_name: str,
    *,
    revision: str,
    cache_folder: str | Path | None,
    local_files_only: bool,
) -> Any:
    try:
        from sentence_transformers import SentenceTransformer
    except ImportError as exc:
        raise LocalMultimodalBackendError(
            "Local text/CLIP encoding requires `wavemind[multimodal]`."
        ) from exc
    try:
        return SentenceTransformer(
            model_name,
            revision=revision,
            cache_folder=str(cache_folder) if cache_folder else None,
            local_files_only=local_files_only,
        )
    except Exception as exc:
        raise LocalMultimodalBackendError(
            f"Could not load pinned local model `{model_name}@{revision}`: {exc}"
        ) from exc


def _load_clap(
    model_name: str,
    *,
    revision: str,
    cache_folder: str | Path | None,
    local_files_only: bool,
) -> tuple[Any, Any]:
    try:
        from transformers import ClapModel, ClapProcessor
    except ImportError as exc:
        raise LocalMultimodalBackendError(
            "Local audio encoding requires `wavemind[multimodal]`."
        ) from exc
    options = {
        "revision": revision,
        "cache_dir": str(cache_folder) if cache_folder else None,
        "local_files_only": local_files_only,
    }
    try:
        return (
            ClapModel.from_pretrained(model_name, **options),
            ClapProcessor.from_pretrained(model_name, **options),
        )
    except Exception as exc:
        raise LocalMultimodalBackendError(
            f"Could not load pinned local CLAP model `{model_name}@{revision}`: {exc}"
        ) from exc


def _sentence_model_dimension(model: Any) -> int:
    for method_name in ("get_embedding_dimension", "get_sentence_embedding_dimension"):
        getter = getattr(model, method_name, None)
        if callable(getter):
            dimension = getter()
            if dimension:
                return int(dimension)
    raise LocalMultimodalBackendError(
        "Sentence-transformers backend does not expose an embedding dimension."
    )


def _clap_dimension(model: Any) -> int:
    config = getattr(model, "config", None)
    dimension = getattr(config, "projection_dim", None)
    if dimension:
        return int(dimension)
    text_projection = getattr(model, "text_projection", None)
    out_features = getattr(text_projection, "out_features", None)
    if out_features:
        return int(out_features)
    raise LocalMultimodalBackendError(
        "CLAP backend does not expose a projection dimension."
    )


def _encode_sentence_values(
    model: Any,
    values: Sequence[Any],
    *,
    vector_dim: int,
) -> np.ndarray:
    if not values:
        raise LocalMediaInputError("Encoder input batch must not be empty.")
    encoded = model.encode(
        list(values),
        convert_to_numpy=True,
        normalize_embeddings=False,
        show_progress_bar=False,
    )
    matrix = np.asarray(encoded, dtype=np.float32)
    if matrix.ndim == 1:
        matrix = matrix.reshape(1, -1)
    if matrix.ndim != 2 or matrix.shape[0] != len(values):
        raise LocalMultimodalBackendError(
            "Local sentence-transformers backend returned an invalid batch shape."
        )
    return np.stack(
        [_unit_vector(vector, vector_dim=vector_dim) for vector in matrix],
        axis=0,
    )


def _feature_vector(value: Any, *, vector_dim: int) -> np.ndarray:
    matrix = _raw_feature_array(value)
    if matrix.ndim == 2 and matrix.shape[0] == 1:
        matrix = matrix[0]
    return _unit_vector(matrix, vector_dim=vector_dim)


def _feature_matrix(
    value: Any,
    *,
    vector_dim: int,
    expected_rows: int,
) -> np.ndarray:
    matrix = _raw_feature_array(value)
    if matrix.ndim == 1 and expected_rows == 1:
        matrix = matrix.reshape(1, -1)
    if matrix.ndim != 2 or int(matrix.shape[0]) != int(expected_rows):
        raise LocalMultimodalBackendError(
            f"Encoder produced batch shape {tuple(matrix.shape)}, "
            f"expected ({expected_rows}, {vector_dim})."
        )
    return np.stack(
        [_unit_vector(row, vector_dim=vector_dim) for row in matrix],
        axis=0,
    )


def _raw_feature_array(value: Any) -> np.ndarray:
    if hasattr(value, "pooler_output"):
        value = value.pooler_output
    elif hasattr(value, "audio_embeds"):
        value = value.audio_embeds
    elif hasattr(value, "text_embeds"):
        value = value.text_embeds
    elif isinstance(value, Mapping):
        for key in ("pooler_output", "audio_embeds", "text_embeds"):
            if key in value:
                value = value[key]
                break
    elif isinstance(value, tuple) and value:
        value = value[0]
    if hasattr(value, "detach"):
        value = value.detach()
    if hasattr(value, "cpu"):
        value = value.cpu()
    if hasattr(value, "numpy"):
        value = value.numpy()
    return np.asarray(value, dtype=np.float32)


def _unit_vector(value: Any, *, vector_dim: int) -> np.ndarray:
    vector = np.asarray(value, dtype=np.float32)
    if vector.ndim != 1 or int(vector.shape[0]) != int(vector_dim):
        raise CrossModalSpaceMismatchError(
            f"Encoder produced shape {tuple(vector.shape)}, expected ({vector_dim},)."
        )
    if not np.all(np.isfinite(vector)):
        raise LocalMultimodalBackendError("Encoder produced non-finite values.")
    norm = float(np.linalg.norm(vector))
    if norm <= 1e-12:
        raise LocalMultimodalBackendError("Encoder produced a zero vector.")
    return (vector / norm).astype(np.float32)


def _mean_unit_vectors(vectors: np.ndarray, *, vector_dim: int) -> np.ndarray:
    if vectors.ndim != 2 or not vectors.shape[0]:
        raise LocalMultimodalBackendError("Expected a non-empty matrix of vectors.")
    return _unit_vector(np.mean(vectors, axis=0), vector_dim=vector_dim)


def _weighted_mean_vectors(
    vectors: Sequence[np.ndarray],
    weights: Sequence[float],
    *,
    vector_dim: int,
) -> np.ndarray:
    if len(vectors) == 0 or len(vectors) != len(weights):
        raise ValueError("Weighted fusion requires equally sized vector and weight lists.")
    total = float(sum(weights))
    if not math.isfinite(total) or total <= 0.0:
        raise ValueError("Weighted fusion requires a positive finite total weight.")
    fused = np.zeros(vector_dim, dtype=np.float32)
    for vector, weight in zip(vectors, weights, strict=True):
        fused += np.float32(float(weight) / total) * _unit_vector(
            vector,
            vector_dim=vector_dim,
        )
    return _unit_vector(fused, vector_dim=vector_dim)


def _semantic_focus(text: str) -> str:
    normalized = " ".join(str(text).strip().split())
    if not normalized:
        return ""
    request_patterns = (
        r"^find (?:an? )?(?:three[- ]dimensional|3d) model of\s+",
        r"^find (?:an? )?(?:image|photo|picture|video|clip|recording|sound|audio) of\s+",
        r"^show me (?:an? )?(?:three[- ]dimensional|3d) model of\s+",
        r"^show me (?:an? )?(?:image|photo|picture|video|clip|recording|sound|audio) of\s+",
    )
    focused = normalized
    for pattern in request_patterns:
        candidate = re.sub(pattern, "", focused, flags=re.IGNORECASE).strip(" .")
        if candidate != focused:
            focused = candidate
            break
    if focused == normalized:
        heading = normalized.split(".", maxsplit=1)[0].strip()
        if heading and len(heading.split()) <= 12:
            focused = heading
    return focused[:160].strip()


def _clip_text_views(text: str) -> tuple[str, ...]:
    normalized = " ".join(str(text).strip().split())
    focus = _semantic_focus(normalized)
    if not normalized or not focus:
        return (normalized,)
    return (
        normalized,
        f"a photo of {focus}",
        f"a video of {focus}",
        f"a 3D model of {focus}",
    )


def _clip_text_view_weights(text: str) -> tuple[float, ...]:
    views = _clip_text_views(text)
    if len(views) == 1:
        return (1.0,)
    return (2.0, 2.0, 1.0, 1.0)


def _clip_query_views(text: str, *, target_modality: str | None) -> tuple[str, ...]:
    normalized = " ".join(str(text).strip().split())
    focus = _semantic_focus(normalized)
    if not focus:
        return (normalized,)
    prompt = {
        "image": f"a photo of {focus}",
        "video": f"a video of {focus}",
        "3d": f"a 3D model of {focus}",
    }.get(str(target_modality or "").strip().lower())
    return tuple(dict.fromkeys((normalized, prompt or normalized)))


def _audio_text_view(text: str) -> str:
    normalized = " ".join(str(text).strip().split())
    focus = _semantic_focus(normalized)
    if not focus:
        return normalized
    return f"the sound of {focus}"


def _require_local_media_path(value: Any, *, modality: str) -> Path:
    raw = str(value or "").strip()
    if not raw:
        raise LocalMediaInputError(f"`{modality}` payload requires a local content URI.")
    if "://" in raw:
        raise LocalMediaInputError(
            f"`{modality}` encoding requires a downloaded local file; remote URI "
            "descriptor fallbacks are disabled."
        )
    path = Path(raw).expanduser()
    if not path.exists() or not path.is_file():
        raise LocalMediaInputError(
            f"`{modality}` content file does not exist or is not a file: {path}"
        )
    return path.resolve()


def _load_image(path: Path) -> Any:
    try:
        from PIL import Image
    except ImportError as exc:
        raise LocalMultimodalBackendError(
            "Image encoding requires Pillow from `wavemind[multimodal]`."
        ) from exc
    try:
        with Image.open(path) as image:
            image.load()
            return image.convert("RGB").copy()
    except Exception as exc:
        raise LocalMediaInputError(f"Could not decode image content `{path}`: {exc}") from exc


def _load_video_frames(path: Path, frame_count: int) -> Sequence[Any]:
    try:
        import cv2
        from PIL import Image
    except ImportError as exc:
        raise LocalMultimodalBackendError(
            "Video encoding requires opencv-python-headless and Pillow from "
            "`wavemind[multimodal]`."
        ) from exc
    capture = cv2.VideoCapture(str(path))
    if not capture.isOpened():
        capture.release()
        raise LocalMediaInputError(f"Could not open video content `{path}`.")
    try:
        total_frames = int(capture.get(cv2.CAP_PROP_FRAME_COUNT))
        if total_frames <= 0:
            raise LocalMediaInputError(f"Video `{path}` reports no decodable frames.")
        indices = np.linspace(
            0,
            max(0, total_frames - 1),
            num=min(frame_count, total_frames),
            dtype=int,
        )
        frames: list[Any] = []
        for index in dict.fromkeys(int(value) for value in indices):
            capture.set(cv2.CAP_PROP_POS_FRAMES, index)
            ok, frame = capture.read()
            if not ok or frame is None:
                raise LocalMediaInputError(
                    f"Could not decode frame {index} from video `{path}`."
                )
            rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            frames.append(Image.fromarray(rgb))
        return frames
    finally:
        capture.release()


def _read_off_geometry(path: Path) -> tuple[np.ndarray, np.ndarray]:
    lines = []
    with path.open("r", encoding="utf-8", errors="strict") as handle:
        for raw_line in handle:
            line = raw_line.partition("#")[0].strip()
            if line:
                lines.append(line)
    if not lines or not lines[0].startswith("OFF"):
        raise LocalMediaInputError(f"3D asset `{path}` is not valid OFF geometry.")
    header_tail = lines[0][3:].strip().split()
    cursor = 1
    if len(header_tail) >= 2:
        counts = header_tail
    elif cursor < len(lines):
        counts = lines[cursor].split()
        cursor += 1
    else:
        raise LocalMediaInputError(f"3D asset `{path}` has no OFF counts.")
    try:
        vertex_count = int(counts[0])
        face_count = int(counts[1])
    except (IndexError, ValueError) as exc:
        raise LocalMediaInputError(f"3D asset `{path}` has invalid OFF counts.") from exc
    if vertex_count < 3 or face_count < 0:
        raise LocalMediaInputError(f"3D asset `{path}` has invalid OFF geometry counts.")
    if cursor + vertex_count + face_count > len(lines):
        raise LocalMediaInputError(f"3D asset `{path}` is truncated.")
    try:
        vertices = np.asarray(
            [
                [float(value) for value in lines[index].split()[:3]]
                for index in range(cursor, cursor + vertex_count)
            ],
            dtype=np.float32,
        )
        cursor += vertex_count
        triangles: list[tuple[int, int, int]] = []
        for index in range(cursor, cursor + face_count):
            values = lines[index].split()
            polygon_size = int(values[0])
            polygon = [int(value) for value in values[1 : polygon_size + 1]]
            if len(polygon) != polygon_size:
                raise ValueError("truncated polygon")
            for offset in range(1, polygon_size - 1):
                triangles.append((polygon[0], polygon[offset], polygon[offset + 1]))
        faces = np.asarray(triangles, dtype=np.int64)
    except (IndexError, ValueError) as exc:
        raise LocalMediaInputError(f"3D asset `{path}` has invalid OFF rows.") from exc
    if faces.size and (int(faces.min()) < 0 or int(faces.max()) >= vertex_count):
        raise LocalMediaInputError(f"3D asset `{path}` has out-of-range OFF face indices.")
    return vertices, faces.reshape((-1, 3))


def _sample_mesh_pointcloud(path: Path, *, point_count: int) -> np.ndarray:
    if path.suffix.lower() == ".off":
        vertices, faces = _read_off_geometry(path)
    else:
        try:
            import trimesh
        except ImportError as exc:
            raise LocalMultimodalBackendError(
                "Non-OFF 3D encoding requires trimesh from `wavemind[multimodal]`."
            ) from exc
        try:
            loaded = trimesh.load(path, force="scene", process=False)
            if isinstance(loaded, trimesh.Scene):
                geometries = tuple(
                    geometry
                    for geometry in loaded.geometry.values()
                    if isinstance(geometry, trimesh.Trimesh)
                    and len(geometry.vertices) >= 3
                )
                if not geometries:
                    raise LocalMediaInputError(
                        f"3D asset `{path}` contains no mesh geometry."
                    )
                mesh = trimesh.util.concatenate(geometries)
            elif isinstance(loaded, trimesh.Trimesh):
                mesh = loaded
            else:
                raise LocalMediaInputError(
                    f"3D asset `{path}` is not a mesh or scene."
                )
            vertices = np.asarray(mesh.vertices, dtype=np.float32)
            faces = np.asarray(mesh.faces, dtype=np.int64)
        except LocalMediaInputError:
            raise
        except Exception as exc:
            raise LocalMediaInputError(
                f"Could not decode 3D geometry `{path}`: {exc}"
            ) from exc
    if vertices.ndim != 2 or vertices.shape[1] != 3 or len(vertices) < 3:
        raise LocalMediaInputError(f"3D asset `{path}` has invalid vertex geometry.")
    seed = int(hashlib.sha256(path.read_bytes()).hexdigest()[:16], 16)
    random = np.random.default_rng(seed)
    triangles = faces[:, :3] if faces.ndim == 2 and faces.shape[1] >= 3 else None
    if triangles is None or not len(triangles):
        sampled = vertices[
            random.choice(len(vertices), size=point_count, replace=True)
        ]
    else:
        values = vertices[triangles]
        cross = np.cross(
            values[:, 1] - values[:, 0],
            values[:, 2] - values[:, 0],
        )
        areas = np.linalg.norm(cross, axis=1) * 0.5
        total_area = float(np.sum(areas))
        if total_area <= 1e-12:
            raise LocalMediaInputError(f"3D asset `{path}` has degenerate faces.")
        selected = random.choice(
            len(triangles),
            size=point_count,
            replace=True,
            p=areas / total_area,
        )
        first = np.sqrt(random.random(point_count))
        second = random.random(point_count)
        selected_triangles = values[selected]
        sampled = (
            (1.0 - first)[:, None] * selected_triangles[:, 0]
            + (first * (1.0 - second))[:, None] * selected_triangles[:, 1]
            + (first * second)[:, None] * selected_triangles[:, 2]
        )
    sampled = np.asarray(sampled, dtype=np.float32)
    sampled -= np.mean(sampled, axis=0, keepdims=True)
    radius = float(np.max(np.linalg.norm(sampled, axis=1)))
    if radius <= 1e-12:
        raise LocalMediaInputError(f"3D asset `{path}` has degenerate geometry.")
    sampled /= radius
    sampled[:, [1, 2]] = sampled[:, [2, 1]]
    rgb = np.full_like(sampled, 0.4, dtype=np.float32)
    return np.concatenate((sampled, rgb), axis=1).astype(np.float32)


def _render_mesh_views(path: Path, view_count: int) -> Sequence[Any]:
    try:
        import cv2
        from PIL import Image
    except ImportError as exc:
        raise LocalMultimodalBackendError(
            "3D encoding requires OpenCV and Pillow from `wavemind[multimodal]`."
        ) from exc
    try:
        if path.suffix.lower() == ".off":
            vertices, faces = _read_off_geometry(path)
        else:
            try:
                import trimesh
            except ImportError as exc:
                raise LocalMultimodalBackendError(
                    "Non-OFF 3D encoding requires trimesh from "
                    "`wavemind[multimodal]`."
                ) from exc
            loaded = trimesh.load(path, force="scene", process=False)
            if isinstance(loaded, trimesh.Scene):
                geometries = tuple(
                    geometry
                    for geometry in loaded.geometry.values()
                    if isinstance(geometry, trimesh.Trimesh)
                    and len(geometry.vertices) >= 3
                )
                if not geometries:
                    raise LocalMediaInputError(
                        f"3D asset `{path}` contains no mesh geometry."
                    )
                mesh = trimesh.util.concatenate(geometries)
            elif isinstance(loaded, trimesh.Trimesh):
                mesh = loaded
            else:
                raise LocalMediaInputError(f"3D asset `{path}` is not a mesh or scene.")
            vertices = np.asarray(mesh.vertices, dtype=np.float32)
            faces = np.asarray(mesh.faces, dtype=np.int64)
    except LocalMediaInputError:
        raise
    except Exception as exc:
        raise LocalMediaInputError(f"Could not decode 3D geometry `{path}`: {exc}") from exc

    if vertices.ndim != 2 or vertices.shape[1] != 3 or len(vertices) < 3:
        raise LocalMediaInputError(f"3D asset `{path}` has invalid vertex geometry.")
    if not np.all(np.isfinite(vertices)):
        raise LocalMediaInputError(f"3D asset `{path}` contains non-finite vertices.")
    vertices = vertices - np.mean(vertices, axis=0, keepdims=True)
    scale = float(np.max(np.ptp(vertices, axis=0)))
    if scale <= 1e-9:
        raise LocalMediaInputError(f"3D asset `{path}` has degenerate geometry.")
    vertices = vertices / scale
    if faces.ndim != 2 or faces.shape[1] < 3:
        faces = np.empty((0, 3), dtype=np.int64)
    if len(faces) > 10000:
        face_indices = np.linspace(0, len(faces) - 1, num=10000, dtype=int)
        faces = faces[face_indices]

    images: list[Any] = []
    render_size = 224
    elevation = math.radians(22.0)
    light = np.asarray([0.35, -0.45, 0.82], dtype=np.float32)
    light /= float(np.linalg.norm(light))
    for angle in np.linspace(0.0, 2.0 * math.pi, num=view_count, endpoint=False):
        forward = np.asarray(
            [
                math.cos(angle) * math.cos(elevation),
                math.sin(angle) * math.cos(elevation),
                math.sin(elevation),
            ],
            dtype=np.float32,
        )
        right = np.asarray([-math.sin(angle), math.cos(angle), 0.0], dtype=np.float32)
        up = np.cross(forward, right)
        transformed = np.column_stack(
            (
                vertices @ right,
                vertices @ up,
                vertices @ forward,
            )
        )
        projected = transformed[:, :2]
        projected -= np.mean(projected, axis=0, keepdims=True)
        extent = float(np.max(np.ptp(projected, axis=0)))
        if extent <= 1e-9:
            raise LocalMediaInputError(f"3D asset `{path}` has degenerate projected geometry.")
        pixels = projected * (render_size * 0.82 / extent)
        pixels[:, 1] *= -1.0
        pixels += render_size / 2.0
        pixels = np.rint(pixels).astype(np.int32)
        canvas = np.full(
            (render_size, render_size, 3),
            (242, 244, 247),
            dtype=np.uint8,
        )
        if len(faces):
            triangles = faces[:, :3]
            triangle_vertices = vertices[triangles]
            normals = np.cross(
                triangle_vertices[:, 1] - triangle_vertices[:, 0],
                triangle_vertices[:, 2] - triangle_vertices[:, 0],
            )
            normal_lengths = np.linalg.norm(normals, axis=1)
            valid = normal_lengths > 1e-9
            normals[valid] /= normal_lengths[valid, None]
            intensity = np.clip(np.abs(normals @ light), 0.0, 1.0)
            depth = transformed[triangles, 2].mean(axis=1)
            for face_index in np.argsort(depth):
                points = [
                    tuple(int(value) for value in pixels[index])
                    for index in triangles[face_index]
                ]
                shade = int(72 + 142 * float(intensity[face_index]))
                cv2.fillConvexPoly(
                    canvas,
                    np.asarray(points, dtype=np.int32),
                    (shade, shade, shade),
                    lineType=cv2.LINE_AA,
                )
        else:
            for x, y in pixels:
                cv2.circle(canvas, (int(x), int(y)), 1, (45, 48, 54), -1)
        images.append(Image.fromarray(canvas, mode="RGB"))
    return images


def _load_audio(path: Path) -> tuple[np.ndarray, int]:
    try:
        import soundfile
    except ImportError as exc:
        raise LocalMultimodalBackendError(
            "Audio encoding requires soundfile from `wavemind[multimodal]`."
        ) from exc
    try:
        samples, sampling_rate = soundfile.read(
            path,
            dtype="float32",
            always_2d=False,
        )
    except Exception as exc:
        raise LocalMediaInputError(f"Could not decode audio content `{path}`: {exc}") from exc
    return np.asarray(samples, dtype=np.float32), int(sampling_rate)


def _mono_float_audio(value: np.ndarray) -> np.ndarray:
    samples = np.asarray(value, dtype=np.float32)
    if samples.ndim == 2:
        samples = np.mean(samples, axis=1)
    if samples.ndim != 1 or not samples.size:
        raise LocalMediaInputError("Audio content must contain a non-empty mono waveform.")
    if not np.all(np.isfinite(samples)):
        raise LocalMediaInputError("Audio content contains non-finite samples.")
    peak = float(np.max(np.abs(samples)))
    if peak > 1.0:
        samples = samples / peak
    return samples.astype(np.float32)


def _resample_audio(
    samples: np.ndarray,
    source_rate: int,
    target_rate: int,
) -> np.ndarray:
    if source_rate <= 0 or target_rate <= 0:
        raise LocalMediaInputError("Audio sample rates must be positive.")
    if source_rate == target_rate:
        return samples
    target_length = max(1, int(round(len(samples) * target_rate / source_rate)))
    source_positions = np.linspace(0.0, 1.0, num=len(samples), endpoint=False)
    target_positions = np.linspace(0.0, 1.0, num=target_length, endpoint=False)
    return np.interp(target_positions, source_positions, samples).astype(np.float32)


def _processor_sampling_rate(processor: Any) -> int:
    extractor = getattr(processor, "feature_extractor", None)
    sampling_rate = getattr(extractor, "sampling_rate", None)
    if not sampling_rate:
        raise LocalMultimodalBackendError(
            "CLAP processor does not expose its required sampling rate."
        )
    return int(sampling_rate)


def _processor_call(
    processor: Any,
    *,
    modality: str,
    value: Sequence[Any],
    sampling_rate: int | None = None,
) -> Mapping[str, Any]:
    options: dict[str, Any] = {
        "return_tensors": "pt",
        "padding": True,
    }
    if modality == "text":
        options["text"] = value
        options["truncation"] = True
        options["max_length"] = _processor_text_max_length(processor)
    elif modality == "audio":
        signature = inspect.signature(processor.__call__)
        parameter = "audio" if "audio" in signature.parameters else "audios"
        options[parameter] = value
        options["sampling_rate"] = sampling_rate
    else:
        raise ValueError(f"Unsupported CLAP processor modality `{modality}`.")
    result = processor(**options)
    if not isinstance(result, Mapping):
        raise LocalMultimodalBackendError(
            "CLAP processor returned a non-mapping input batch."
        )
    return result


def _processor_text_max_length(processor: Any) -> int:
    tokenizer = getattr(processor, "tokenizer", None)
    value = getattr(tokenizer, "model_max_length", None)
    try:
        resolved = int(value)
    except (TypeError, ValueError):
        resolved = 512
    if resolved <= 0 or resolved > 1_000_000:
        return 512
    return min(resolved, 512)


def _torch_inference_context() -> ContextManager[Any]:
    try:
        import torch
    except ImportError as exc:
        raise LocalMultimodalBackendError(
            "Local CLAP inference requires PyTorch from `wavemind[multimodal]`."
        ) from exc
    return torch.inference_mode()


def no_inference_context() -> ContextManager[Any]:
    """Testing hook for injected CPU models that return NumPy features."""

    return nullcontext()
