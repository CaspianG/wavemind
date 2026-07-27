from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from benchmarks.prepare_public_multimodal_suite import (
    SourceSample,
    UploadResult,
    WikipediaDocument,
    prepare_public_multimodal_suite,
)
from wavemind.multimodal_public_benchmark import load_public_multimodal_suite


class _VerifiedUploader:
    def __init__(self):
        self.objects: dict[str, bytes] = {}

    def upload(self, path: Path, *, modality: str, asset_id: str) -> UploadResult:
        key = f"fixture/{modality}/{path.name}"
        self.objects[key] = path.read_bytes()
        return UploadResult(uri=f"s3://fixture/{key}", verified=True)


class _UnverifiedUploader:
    def upload(self, path: Path, *, modality: str, asset_id: str) -> UploadResult:
        del path, modality, asset_id
        return UploadResult(uri="s3://fixture/unverified", verified=False)


def _samples() -> dict[str, dict[str, list[SourceSample]]]:
    specs = {
        "image": ("ibex", ".png", "image/png"),
        "audio": ("rainfall", ".wav", "audio/wav"),
        "video": ("juggling", ".mp4", "video/mp4"),
        "3d": ("teapot", ".off", "model/vnd.off"),
    }
    result: dict[str, dict[str, list[SourceSample]]] = {}
    for modality, (concept, suffix, media_type) in specs.items():
        result[modality] = {
            concept: [
                SourceSample(
                    dataset_id=f"fixture-{modality}",
                    modality=modality,
                    concept=concept,
                    source_ref=f"{modality}:{index}",
                    source_url=f"https://example.test/{modality}/{index}",
                    media_type=media_type,
                    suffix=suffix,
                    content=f"{concept} independent sample {index}".encode(),
                )
                for index in range(3)
            ]
        }
    return result


def _documents() -> dict[str, WikipediaDocument]:
    documents = {}
    for concept in ("ibex", "rainfall", "juggling", "teapot"):
        documents[concept] = WikipediaDocument(
            concept=concept,
            title=concept.title(),
            revision=hashlib.sha1(concept.encode()).hexdigest(),
            timestamp="2026-01-01T00:00:00Z",
            source_url=f"https://example.test/wiki/{concept}",
            text=(
                f"{concept.title()} is the subject of this independent public "
                "reference paragraph. It contains enough descriptive context "
                "to produce a real text asset without using a filename, class "
                "field, caption field, or metadata fallback. "
            )
            * 3,
        )
    return documents


def _metadata() -> list[dict[str, str]]:
    return [
        {
            "id": dataset_id,
            "name": dataset_id,
            "revision": "a" * 40,
            "license": "CC0-1.0",
            "source_url": f"https://example.test/{dataset_id}",
        }
        for dataset_id in (
            "fixture-image",
            "fixture-audio",
            "fixture-video",
            "fixture-3d",
            "wikipedia",
        )
    ]


def test_builder_writes_strict_round_trip_suite(tmp_path):
    uploader = _VerifiedUploader()
    suite_path = prepare_public_multimodal_suite(
        output_dir=tmp_path / "suite",
        samples=_samples(),
        wikipedia_documents=_documents(),
        uploader=uploader,
        stored_per_concept=2,
        text_asset_total=4,
        mixed_queries_per_pair=1,
        suite_revision="fixture-v1",
        dataset_metadata=_metadata(),
    )

    suite = load_public_multimodal_suite(suite_path)
    raw_suite = json.loads(suite_path.read_text(encoding="utf-8"))
    assets = json.loads(
        (suite_path.parent / raw_suite["asset_manifest"]).read_text(encoding="utf-8")
    )
    queries = json.loads(
        (suite_path.parent / raw_suite["query_manifest"]).read_text(encoding="utf-8")
    )
    provenance = json.loads(
        (suite_path.parent / raw_suite["provenance_manifest"]).read_text(
            encoding="utf-8"
        )
    )

    assert len(suite.assets) == 12
    assert len(suite.queries) == 10
    assert raw_suite["counts"]["assets_by_modality"] == {
        "3d": 2,
        "audio": 2,
        "image": 2,
        "text": 4,
        "video": 2,
    }
    assert raw_suite["counts"]["direct_cross_modal_queries"] == 8
    assert raw_suite["counts"]["mixed_queries"] == 2
    assert len(uploader.objects) == 12
    assert all(row["object_verified"] for row in assets)
    assert all(row["object_uri"].startswith("s3://fixture/") for row in assets)
    assert all(
        set(row).isdisjoint({"label", "caption", "title", "description", "target"})
        for row in assets
    )
    assert all(Path(row["path"]).stem == row["id"] for row in assets)
    assert all(
        Path(part["path"]).stem == row["id"] for row in queries for part in row["parts"]
    )
    assert len(provenance["assets"]) == 12
    assert len(provenance["queries"]) == 10


def test_builder_is_deterministic_for_identical_sources(tmp_path):
    first = prepare_public_multimodal_suite(
        output_dir=tmp_path / "one",
        samples=_samples(),
        wikipedia_documents=_documents(),
        uploader=_VerifiedUploader(),
        stored_per_concept=2,
        text_asset_total=4,
        mixed_queries_per_pair=1,
        suite_revision="fixture-v1",
        dataset_metadata=_metadata(),
    )
    second = prepare_public_multimodal_suite(
        output_dir=tmp_path / "two",
        samples=_samples(),
        wikipedia_documents=_documents(),
        uploader=_VerifiedUploader(),
        stored_per_concept=2,
        text_asset_total=4,
        mixed_queries_per_pair=1,
        suite_revision="fixture-v1",
        dataset_metadata=_metadata(),
    )
    first_suite = json.loads(first.read_text(encoding="utf-8"))
    second_suite = json.loads(second.read_text(encoding="utf-8"))
    for key in (
        "asset_manifest_sha256",
        "query_manifest_sha256",
        "ground_truth_sha256",
        "provenance_manifest_sha256",
        "counts",
    ):
        assert first_suite[key] == second_suite[key]


def test_builder_rejects_unverified_object_storage(tmp_path):
    with pytest.raises(RuntimeError, match="was not verified"):
        prepare_public_multimodal_suite(
            output_dir=tmp_path / "suite",
            samples=_samples(),
            wikipedia_documents=_documents(),
            uploader=_UnverifiedUploader(),
            stored_per_concept=2,
            text_asset_total=4,
            mixed_queries_per_pair=1,
            suite_revision="fixture-v1",
            dataset_metadata=_metadata(),
        )


def test_builder_requires_independent_held_out_sample(tmp_path):
    samples = _samples()
    samples["audio"]["rainfall"] = samples["audio"]["rainfall"][:2]
    with pytest.raises(ValueError, match="needs at least 3 independent samples"):
        prepare_public_multimodal_suite(
            output_dir=tmp_path / "suite",
            samples=samples,
            wikipedia_documents=_documents(),
            uploader=_VerifiedUploader(),
            stored_per_concept=2,
            text_asset_total=4,
            mixed_queries_per_pair=1,
            suite_revision="fixture-v1",
            dataset_metadata=_metadata(),
        )
