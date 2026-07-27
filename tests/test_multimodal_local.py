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


_TEXT_REVISION = "a" * 40
_CLIP_REVISION = "b" * 40
_CLAP_REVISION = "c" * 40


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

    def __call__(
        self,
        *,
        text=None,
        audio=None,
        sampling_rate=None,
        return_tensors=None,
        padding=None,
    ):
        if text is not None:
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
            result.fusion["strategy"] == "weighted_reciprocal_rank"
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
