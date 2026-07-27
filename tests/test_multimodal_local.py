from __future__ import annotations

from dataclasses import dataclass
from types import SimpleNamespace

import numpy as np
import pytest

from wavemind import (
    HashingTextEncoder,
    LocalClapAudioEncoder,
    LocalClipMediaEncoder,
    LocalMediaInputError,
    LocalMultimodalBackendError,
    LocalMultimodalMemory,
    LocalMultimodalQueryPart,
    LocalSentenceTextEncoder,
    MemoryPayload,
    WaveMind,
    audio_payload,
    cross_modal_space_tag,
    image_payload,
    no_inference_context,
    video_payload,
)
from wavemind.multimodal_local import _read_off_geometry, _sample_mesh_pointcloud


_TEXT_REVISION = "a" * 40
_CLIP_REVISION = "b" * 40
_CLAP_REVISION = "c" * 40


def test_off_geometry_reader_triangulates_without_descriptor_data(tmp_path):
    path = tmp_path / "opaque.off"
    path.write_text(
        "OFF\n4 1 0\n0 0 0\n1 0 0\n1 1 0\n0 1 0\n4 0 1 2 3\n",
        encoding="utf-8",
    )
    vertices, faces = _read_off_geometry(path)
    assert vertices.shape == (4, 3)
    assert faces.tolist() == [[0, 1, 2], [0, 2, 3]]


def test_mesh_pointcloud_sampling_is_content_based_and_deterministic(tmp_path):
    path = tmp_path / "opaque.off"
    path.write_text(
        "OFF\n4 2 0\n0 0 0\n1 0 0\n0 1 0\n0 0 1\n"
        "3 0 1 2\n3 0 1 3\n",
        encoding="utf-8",
    )
    first = _sample_mesh_pointcloud(path, point_count=64)
    second = _sample_mesh_pointcloud(path, point_count=64)
    assert first.shape == (64, 6)
    assert np.array_equal(first, second)
    assert np.allclose(first[:, 3:], 0.4)
    assert np.isclose(np.linalg.norm(first[:, :3], axis=1).max(), 1.0)


def test_clip_3d_backend_encodes_xyz_rgb_pointclouds(tmp_path):
    torch = pytest.importorskip("torch")

    class _PointcloudModel(torch.nn.Module):
        def __init__(self):
            super().__init__()
            self.anchor = torch.nn.Parameter(torch.zeros(1))
            self.shapes = []

        def forward(self, values):
            self.shapes.append(tuple(values.shape))
            assert values.shape[1] == 6
            return torch.tensor(
                [[3.0, 4.0, 0.0, 0.0]] * values.shape[0],
                dtype=values.dtype,
                device=values.device,
            )

    path = tmp_path / "opaque.off"
    path.write_text(
        "OFF\n4 2 0\n0 0 0\n1 0 0\n0 1 0\n0 0 1\n"
        "3 0 1 2\n3 0 1 3\n",
        encoding="utf-8",
    )
    model = _PointcloudModel()
    encoder = LocalClipMediaEncoder(
        "tests/clip",
        model_revision=_CLIP_REVISION,
        model=_ContentModel(),
        pointcloud_model=model,
        use_openshape_3d=True,
        pointcloud_size=64,
        pointcloud_batch_size=2,
    )
    payload = MemoryPayload(kind="3d", text="", metadata={"uri": str(path)})

    single = encoder.encode_payload(payload, "")
    batch = encoder.encode_payloads([payload, payload])

    assert model.shapes == [(1, 6, 64), (2, 6, 64)]
    assert np.allclose(single, np.asarray([0.6, 0.8, 0.0, 0.0]))
    assert all(np.array_equal(single, vector) for vector in batch)


def _vector(index: int) -> np.ndarray:
    value = np.zeros(4, dtype=np.float32)
    value[index] = 1.0
    return value


class _ContentModel:
    def get_sentence_embedding_dimension(self):
        return 4

    def encode(self, values, **kwargs):
        vectors = []
        for value in values:
            text = str(value).lower()
            if "dashboard" in text:
                vectors.append(_vector(0))
            elif "forklift" in text:
                vectors.append(_vector(1))
            elif "gear" in text:
                vectors.append(_vector(2))
            else:
                vectors.append(_vector(3))
        return np.asarray(vectors, dtype=np.float32)


class _TextModel:
    def get_sentence_embedding_dimension(self):
        return 4

    def encode(self, values, **kwargs):
        return np.asarray(
            [
                _vector(0) if "release" in str(value).lower() else _vector(3)
                for value in values
            ],
            dtype=np.float32,
        )


class _FakeClapProcessor:
    feature_extractor = SimpleNamespace(sampling_rate=48000)
    tokenizer = SimpleNamespace(model_max_length=512)

    def __init__(self):
        self.text_calls = []

    def __call__(
        self,
        *,
        text=None,
        audio=None,
        sampling_rate=None,
        return_tensors=None,
        padding=None,
        truncation=None,
        max_length=None,
    ):
        if text is not None:
            self.text_calls.append(
                {
                    "text": list(text),
                    "truncation": truncation,
                    "max_length": max_length,
                }
            )
            return {"texts": list(text)}
        return {
            "audio_values": list(audio),
            "sampling_rate": int(sampling_rate),
        }


class _FakeClapModel:
    config = SimpleNamespace(projection_dim=4)

    def eval(self):
        return self

    def get_text_features(self, *, texts):
        return np.asarray(
            [
                _vector(0) if "bell" in str(text).lower() else _vector(1)
                for text in texts
            ],
            dtype=np.float32,
        )

    def get_audio_features(self, *, audio_values, sampling_rate):
        assert sampling_rate == 48000
        return SimpleNamespace(
            pooler_output=np.asarray(
                [
                    _vector(0) if float(np.mean(value)) > 0.0 else _vector(1)
                    for value in audio_values
                ],
                dtype=np.float32,
            )
        )


@dataclass(frozen=True)
class _Backends:
    text: LocalSentenceTextEncoder
    clip: LocalClipMediaEncoder
    clap: LocalClapAudioEncoder


def _backends() -> _Backends:
    return _Backends(
        text=LocalSentenceTextEncoder(
            "tests/text",
            model_revision=_TEXT_REVISION,
            model=_TextModel(),
        ),
        clip=LocalClipMediaEncoder(
            "tests/clip",
            model_revision=_CLIP_REVISION,
            model=_ContentModel(),
            image_loader=lambda path: path.read_text(encoding="utf-8"),
            video_frame_loader=lambda path, count: [
                path.read_text(encoding="utf-8")
            ]
            * count,
            mesh_view_renderer=lambda path, count: [
                path.read_text(encoding="utf-8")
            ]
            * count,
            use_openshape_3d=False,
            video_frame_count=2,
            mesh_view_count=2,
        ),
        clap=LocalClapAudioEncoder(
            "tests/clap",
            model_revision=_CLAP_REVISION,
            model=_FakeClapModel(),
            processor=_FakeClapProcessor(),
            audio_loader=lambda path: (
                np.full(2400, 0.5 if b"bell" in path.read_bytes() else -0.5),
                24000,
            ),
            inference_context=no_inference_context,
        ),
    )


def _memory(tmp_path):
    return WaveMind(
        db_path=tmp_path / "local-multimodal.sqlite3",
        encoder=HashingTextEncoder(vector_dim=64),
        width=16,
        height=16,
        layers=1,
    )


def test_real_local_backends_require_pinned_revisions():
    with pytest.raises(ValueError, match="40-character"):
        LocalSentenceTextEncoder("tests/text", model_revision="main", model=_TextModel())
    with pytest.raises(ValueError, match="40-character"):
        LocalClipMediaEncoder("tests/clip", model_revision="latest", model=_ContentModel())
    with pytest.raises(ValueError, match="40-character"):
        LocalClapAudioEncoder(
            "tests/clap",
            model_revision="v1",
            model=_FakeClapModel(),
            processor=_FakeClapProcessor(),
            inference_context=no_inference_context,
        )


def test_bundled_openshape_rejects_an_unaligned_clip_space():
    with pytest.raises(LocalMultimodalBackendError, match="aligned only"):
        LocalClipMediaEncoder(
            "tests/custom-clip",
            model_revision=_CLIP_REVISION,
            model=_ContentModel(),
        )


def test_clap_text_encoding_always_truncates_to_model_limit():
    backends = _backends()
    long_text = "bell " * 700

    vector = backends.clap.encode_payload(
        MemoryPayload(kind="text", text=long_text),
        long_text,
    )
    vectors = backends.clap.encode_payloads(
        [
            MemoryPayload(kind="text", text=long_text),
            MemoryPayload(kind="text", text="bell"),
        ]
    )

    assert vector.shape == (4,)
    assert len(vectors) == 2
    assert backends.clap.processor.text_calls
    assert all(
        call["truncation"] is True and call["max_length"] == 512
        for call in backends.clap.processor.text_calls
    )


def test_real_local_backends_reject_precomputed_vector_shortcuts(tmp_path):
    backends = _backends()
    image = tmp_path / "image.bin"
    image.write_text("dashboard", encoding="utf-8")
    audio = tmp_path / "audio.bin"
    audio.write_bytes(b"bell")
    metadata = {"cross_modal_vector": [1.0, 0.0, 0.0, 0.0]}

    with pytest.raises(LocalMediaInputError, match="rejects precomputed"):
        backends.text.encode_payload(
            MemoryPayload(kind="text", text="release note", metadata=metadata),
            "",
        )
    with pytest.raises(LocalMediaInputError, match="rejects precomputed"):
        backends.clip.encode_payload(
            MemoryPayload(
                kind="image",
                text="ignored caption",
                metadata={**metadata, "uri": str(image)},
            ),
            "",
        )
    with pytest.raises(LocalMediaInputError, match="rejects precomputed"):
        backends.clap.encode_payload(
            MemoryPayload(
                kind="audio",
                text="ignored transcript",
                metadata={**metadata, "uri": str(audio)},
            ),
            "",
        )


def test_clip_backend_uses_real_file_content_for_image_video_and_3d(tmp_path):
    encoder = _backends().clip
    paths = {}
    for modality, content in (
        ("image", "dashboard pixels"),
        ("video", "forklift frames"),
        ("3d", "gear geometry"),
    ):
        path = tmp_path / f"opaque-{modality}.bin"
        path.write_text(content, encoding="utf-8")
        paths[modality] = path

    image = encoder.encode_payload(
        MemoryPayload(
            kind="image",
            text="uninformative",
            metadata={"uri": str(paths["image"])},
        ),
        "metadata must not drive encoding",
    )
    video = encoder.encode_payload(
        MemoryPayload(
            kind="video",
            text="uninformative",
            metadata={"uri": str(paths["video"])},
        ),
        "metadata must not drive encoding",
    )
    mesh = encoder.encode_payload(
        MemoryPayload(
            kind="3d",
            text="uninformative",
            metadata={"uri": str(paths["3d"])},
        ),
        "metadata must not drive encoding",
    )

    assert np.allclose(image, _vector(0))
    assert np.allclose(video, _vector(1))
    assert np.allclose(mesh, _vector(2))


def test_real_local_batch_encoders_match_individual_content_encoding(tmp_path):
    backends = _backends()
    image = tmp_path / "opaque-image.bin"
    image.write_text("dashboard pixels", encoding="utf-8")
    video = tmp_path / "opaque-video.bin"
    video.write_text("forklift frames", encoding="utf-8")
    mesh = tmp_path / "opaque-mesh.bin"
    mesh.write_text("gear geometry", encoding="utf-8")
    bell = tmp_path / "opaque-bell.bin"
    bell.write_bytes(b"bell waveform")
    noise = tmp_path / "opaque-noise.bin"
    noise.write_bytes(b"noise waveform")

    text_payloads = [
        MemoryPayload(kind="text", text="release checklist"),
        MemoryPayload(kind="text", text="other note"),
    ]
    clip_payloads = [
        MemoryPayload(kind="image", text="ignored", metadata={"uri": str(image)}),
        MemoryPayload(kind="video", text="ignored", metadata={"uri": str(video)}),
        MemoryPayload(kind="3d", text="ignored", metadata={"uri": str(mesh)}),
    ]
    audio_payloads = [
        MemoryPayload(kind="audio", text="ignored", metadata={"uri": str(bell)}),
        MemoryPayload(kind="audio", text="ignored", metadata={"uri": str(noise)}),
    ]

    for encoder, payloads in (
        (backends.text, text_payloads),
        (backends.clip, clip_payloads),
        (backends.clap, audio_payloads),
    ):
        batched = encoder.encode_payloads(payloads)
        individual = [
            encoder.encode_payload(payload, "descriptor must be ignored")
            for payload in payloads
        ]
        assert len(batched) == len(payloads)
        assert all(
            np.allclose(batch_vector, individual_vector)
            for batch_vector, individual_vector in zip(
                batched,
                individual,
                strict=True,
            )
        )


def test_missing_media_is_a_clear_error_without_descriptor_fallback(tmp_path):
    encoder = _backends().clip
    with pytest.raises(LocalMediaInputError, match="does not exist"):
        encoder.encode_payload(
            MemoryPayload(
                kind="image",
                text="a caption that would otherwise be enough",
                metadata={"uri": str(tmp_path / "missing.png")},
            ),
            "a highly descriptive fallback",
        )
    with pytest.raises(LocalMediaInputError, match="remote URI.*disabled"):
        encoder.encode_payload(
            MemoryPayload(
                kind="video",
                text="remote video description",
                metadata={"uri": "s3://bucket/video.mp4"},
            ),
            "remote descriptor fallback",
        )


def test_multiple_real_spaces_coexist_and_are_exactly_tagged(tmp_path):
    files = {
        "image": tmp_path / "asset-a.bin",
        "video": tmp_path / "asset-b.bin",
        "3d": tmp_path / "asset-c.bin",
        "audio": tmp_path / "asset-d.bin",
    }
    files["image"].write_text("dashboard pixels", encoding="utf-8")
    files["video"].write_text("forklift frames", encoding="utf-8")
    files["3d"].write_text("gear geometry", encoding="utf-8")
    files["audio"].write_bytes(b"bell waveform")
    memory = _memory(tmp_path)
    try:
        backends = _backends()
        local = LocalMultimodalMemory(
            memory,
            text_encoder=backends.text,
            visual_encoder=backends.clip,
            audio_encoder=backends.clap,
        )
        ids = {
            "text": local.remember(
                MemoryPayload(kind="text", text="release checklist"),
                namespace="tenant:a",
            ),
            "dashboard_text": local.remember(
                MemoryPayload(kind="text", text="dashboard analysis"),
                namespace="tenant:a",
            ),
            "bell_text": local.remember(
                MemoryPayload(kind="text", text="bell incident recording"),
                namespace="tenant:a",
            ),
            "image": local.remember(
                image_payload(files["image"], caption="uninformative"),
                namespace="tenant:a",
            ),
            "video": local.remember(
                video_payload(files["video"], summary="uninformative"),
                namespace="tenant:a",
            ),
            "3d": local.remember(
                MemoryPayload(
                    kind="3d",
                    text="uninformative",
                    metadata={"uri": str(files["3d"])},
                ),
                namespace="tenant:a",
            ),
            "audio": local.remember(
                audio_payload(files["audio"], transcript="uninformative"),
                namespace="tenant:a",
            ),
        }

        assert (
            local.query(
                "dashboard",
                namespace="tenant:a",
                target_modalities=["image"],
                top_k=1,
            )[0].id
            == ids["image"]
        )
        assert (
            local.query(
                "bell sound",
                namespace="tenant:a",
                target_modalities=["audio"],
                top_k=1,
            )[0].id
            == ids["audio"]
        )
        assert (
            local.query(
                "release",
                namespace="tenant:a",
                target_modalities=["text"],
                top_k=1,
            )[0].id
            == ids["text"]
        )

        records = memory.store.list(namespace="tenant:a", tags=["multimodal"])
        assert len(records) == 13
        for record in records:
            space_id = record.metadata["cross_modal_space_id"]
            assert cross_modal_space_tag(space_id) in record.tags
        assert len(local.spaces) == 3

        image_to_text = local.query_mixed(
            [LocalMultimodalQueryPart(modality="image", uri=files["image"])],
            namespace="tenant:a",
            target_modalities=["text"],
            top_k=1,
        )
        audio_to_text = local.query_mixed(
            [LocalMultimodalQueryPart(modality="audio", uri=files["audio"])],
            namespace="tenant:a",
            target_modalities=["text"],
            top_k=1,
        )
        assert image_to_text[0].id == ids["dashboard_text"]
        assert audio_to_text[0].id == ids["bell_text"]
        assert image_to_text[0].metadata["embedding_record_id"] != ids["dashboard_text"]
        assert audio_to_text[0].metadata["embedding_record_id"] != ids["bell_text"]

        assert local.forget(ids["dashboard_text"], namespace="tenant:a") == 3
        assert all(
            record.id != ids["dashboard_text"]
            and record.metadata.get("logical_memory_id") != ids["dashboard_text"]
            for record in memory.store.list(namespace="tenant:a", tags=["multimodal"])
        )
    finally:
        memory.close()


def test_mixed_query_fuses_spaces_by_rank_without_raw_vector_comparison(tmp_path):
    image = tmp_path / "opaque-image.bin"
    image.write_text("dashboard pixels", encoding="utf-8")
    audio = tmp_path / "opaque-audio.bin"
    audio.write_bytes(b"bell waveform")
    memory = _memory(tmp_path)
    try:
        backends = _backends()
        local = LocalMultimodalMemory(
            memory,
            text_encoder=backends.text,
            visual_encoder=backends.clip,
            audio_encoder=backends.clap,
        )
        image_id = local.remember(
            image_payload(image, caption="uninformative"),
            namespace="tenant:a",
        )
        audio_id = local.remember(
            audio_payload(audio, transcript="uninformative"),
            namespace="tenant:a",
        )

        results = local.query_mixed(
            [
                LocalMultimodalQueryPart(
                    modality="image",
                    uri=image,
                    weight=2.0,
                ),
                LocalMultimodalQueryPart(
                    modality="audio",
                    uri=audio,
                    weight=1.0,
                ),
            ],
            namespace="tenant:a",
            target_modalities=["image", "audio"],
            top_k=2,
        )

        assert {result.id for result in results} == {image_id, audio_id}
        assert all(
            result.fusion["strategy"] == "confidence_weighted_reciprocal_rank"
            for result in results
        )
        assert all(
            result.fusion["incompatible_spaces_compared"] is False
            for result in results
        )
        for result in results:
            contributions = result.fusion["contributions"]
            assert len({item["space_id"] for item in contributions}) == 1
            assert all("raw_space_score" in item for item in contributions)
            assert all(0.0 < item["group_confidence"] <= 1.0 for item in contributions)
    finally:
        memory.close()


def test_mixed_query_rejects_vector_shortcut_in_real_media_part(tmp_path):
    image = tmp_path / "opaque-image.bin"
    image.write_text("dashboard pixels", encoding="utf-8")
    memory = _memory(tmp_path)
    try:
        backends = _backends()
        local = LocalMultimodalMemory(
            memory,
            text_encoder=backends.text,
            visual_encoder=backends.clip,
            audio_encoder=backends.clap,
        )
        with pytest.raises(LocalMediaInputError, match="rejects precomputed"):
            local.query_mixed(
                [
                    LocalMultimodalQueryPart(
                        modality="image",
                        uri=image,
                        metadata={"vector": [1.0, 0.0, 0.0, 0.0]},
                    )
                ],
                target_modalities=["image"],
            )
    finally:
        memory.close()
