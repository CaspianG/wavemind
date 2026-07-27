from __future__ import annotations

import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

from wavemind.multimodal import CrossModalEmbeddingSpace, MemoryPayload
from wavemind.multimodal_public_benchmark import (
    PUBLIC_MULTIMODAL_RESULT_SCHEMA,
    _quality_verdict,
    _rank_fuse_asset_ids,
    load_public_multimodal_suite,
    write_public_multimodal_benchmark_artifacts,
)


_CONCEPTS = {
    "alpha": 0,
    "bravo": 1,
    "charlie": 2,
    "delta": 3,
    "echo": 4,
}


def test_quality_verdict_gates_retrieval_separately_from_media_encoding():
    summary = {
        "precision_at_1": 0.90,
        "cross_modal_precision_at_1": 0.90,
        "mixed_multimodal_precision_at_1": 0.90,
        "persisted_vector_parity": 1.0,
        "reload_query_parity": 1.0,
        "retrieval_p99_ms": 249.0,
        "query_p99_ms": 2_000.0,
        "error_rate": 0.0,
    }
    assert _quality_verdict(summary) == "pass"
    summary["retrieval_p99_ms"] = 251.0
    assert _quality_verdict(summary) == "fail"


def test_rank_fusion_uses_group_confidence_instead_of_first_group_ties():
    weak = [
        SimpleNamespace(id=1, score=0.90),
        SimpleNamespace(id=2, score=0.89),
    ]
    decisive = [
        SimpleNamespace(id=3, score=0.90),
        SimpleNamespace(id=4, score=0.50),
    ]

    ranked = _rank_fuse_asset_ids(
        [
            ("visual", "image", weak),
            ("audio", "audio", decisive),
        ],
        memory_to_asset={
            "visual": {1: "visual-first", 2: "visual-second"},
            "audio": {3: "audio-first", 4: "audio-second"},
        },
        top_k=4,
    )

    assert ranked[0]["asset_id"] == "audio-first"
    by_asset = {row["asset_id"]: row for row in ranked}
    assert by_asset["audio-first"]["contributions"][0]["group_confidence"] > (
        by_asset["visual-first"]["contributions"][0]["group_confidence"]
    )


class _ContentEncoder:
    def __init__(self, space_id: str, modalities: tuple[str, ...], revision: str):
        self.name = f"local-{space_id}"
        self.vector_dim = 8
        self.embedding_space = CrossModalEmbeddingSpace(
            space_id=space_id,
            vector_dim=self.vector_dim,
            modalities=modalities,
            encoder_name=self.name,
            model_revision=revision,
            production_eligible=True,
        )

    def encode_payloads(self, payloads):
        return [self.encode_payload(payload, "") for payload in payloads]

    def encode_payload(self, payload: MemoryPayload, descriptor: str):
        del descriptor
        if payload.kind == "text":
            content = payload.text
        else:
            content = Path(payload.metadata["uri"]).read_bytes().decode(
                "utf-8",
                errors="ignore",
            )
        return self._vector(content)

    def encode_query(self, query: str, *, target_modality: str | None, descriptor: str):
        del target_modality, descriptor
        return self._vector(query)

    def _vector(self, content: str):
        lowered = content.lower()
        vector = np.zeros(self.vector_dim, dtype=np.float32)
        for concept, index in _CONCEPTS.items():
            if concept in lowered:
                vector[index] = 1.0
                return vector
        raise ValueError(f"fixture content has no known concept: {content!r}")


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_json(path: Path, payload) -> None:
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def _opaque(prefix: str, value: int) -> str:
    return f"{prefix}_{value:032x}"


def _build_suite(tmp_path: Path, *, leak: bool = False) -> Path:
    root = tmp_path / "suite"
    assets_root = root / "assets"
    queries_root = root / "queries"
    assets_root.mkdir(parents=True)
    queries_root.mkdir(parents=True)

    asset_specs = (
        ("text", "alpha"),
        ("image", "bravo"),
        ("audio", "charlie"),
        ("video", "delta"),
        ("3d", "echo"),
    )
    assets = []
    asset_ids = {}
    for index, (modality, concept) in enumerate(asset_specs, start=1):
        asset_id = _opaque("a", index)
        asset_ids[modality] = asset_id
        path = assets_root / f"{asset_id}.bin"
        path.write_text(concept, encoding="utf-8")
        row = {
            "id": asset_id,
            "modality": modality,
            "path": path.relative_to(root).as_posix(),
            "sha256": _sha256(path),
            "bytes": path.stat().st_size,
            "media_type": "application/octet-stream",
            "dataset_id": "fixture",
            "object_uri": f"s3://wavemind-public/{asset_id}",
            "object_verified": True,
        }
        if leak and index == 1:
            row["label"] = concept
        assets.append(row)

    query_specs = (
        ("text", "bravo", ("image",), ("image",)),
        ("image", "alpha", ("text",), ("text",)),
        ("text", "charlie", ("audio",), ("audio",)),
        ("audio", "alpha", ("text",), ("text",)),
        ("text", "delta", ("video",), ("video",)),
        ("video", "alpha", ("text",), ("text",)),
        ("text", "echo", ("3d",), ("3d",)),
        ("3d", "alpha", ("text",), ("text",)),
    )
    queries = []
    relevant = {}
    for index, (modality, concept, targets, relevant_modalities) in enumerate(
        query_specs,
        start=1,
    ):
        query_id = _opaque("q", index)
        path = queries_root / f"{query_id}.bin"
        path.write_text(concept, encoding="utf-8")
        queries.append(
            {
                "id": query_id,
                "parts": [
                    {
                        "modality": modality,
                        "path": path.relative_to(root).as_posix(),
                        "sha256": _sha256(path),
                        "weight": 1.0,
                    }
                ],
                "target_modalities": list(targets),
            }
        )
        relevant[query_id] = [
            asset_ids[target] for target in relevant_modalities
        ]

    mixed_id = _opaque("q", 9)
    mixed_parts = []
    for extension, modality, concept in (
        ("img", "image", "bravo"),
        ("wav", "audio", "charlie"),
    ):
        path = queries_root / f"{mixed_id}.{extension}"
        path.write_text(concept, encoding="utf-8")
        mixed_parts.append(
            {
                "modality": modality,
                "path": path.relative_to(root).as_posix(),
                "sha256": _sha256(path),
                "weight": 1.0,
            }
        )
    queries.append(
        {
            "id": mixed_id,
            "parts": mixed_parts,
            "target_modalities": ["image", "audio"],
        }
    )
    relevant[mixed_id] = [asset_ids["image"], asset_ids["audio"]]

    asset_manifest = root / "assets.json"
    query_manifest = root / "queries.json"
    ground_truth = root / "ground-truth.json"
    _write_json(asset_manifest, assets)
    _write_json(query_manifest, queries)
    _write_json(ground_truth, {"relevant_asset_ids": relevant})
    suite = root / "suite.json"
    _write_json(
        suite,
        {
            "schema": "wavemind.public_multimodal_suite.v1",
            "name": "public-fixture",
            "revision": "fixture-revision-1",
            "license": "CC0-1.0",
            "datasets": [
                {
                    "id": "fixture",
                    "name": "public-fixture",
                    "revision": "fixture-revision-1",
                    "license": "CC0-1.0",
                    "source_url": "https://example.test/public-fixture",
                }
            ],
            "asset_manifest": asset_manifest.name,
            "asset_manifest_sha256": _sha256(asset_manifest),
            "query_manifest": query_manifest.name,
            "query_manifest_sha256": _sha256(query_manifest),
            "ground_truth": ground_truth.name,
            "ground_truth_sha256": _sha256(ground_truth),
        },
    )
    return suite


def _lifecycle_artifact(tmp_path: Path) -> Path:
    path = tmp_path / "asset-lifecycle.json"
    checks = {
        f"{name}_pass": True
        for name in (
            "ingest",
            "checksum",
            "reload",
            "persistence",
            "namespace_isolation",
            "ttl",
            "physical_delete",
            "tombstone",
            "backup_restore",
            "orphan_cleanup",
        )
    }
    _write_json(
        path,
        {
            "schema": "wavemind.asset-lifecycle-evidence.v1",
            "source_ref": "a" * 40,
            "status": "pass",
            "lifecycle": {
                "object_store_backend": "minio",
                "object_store_pass": True,
                **checks,
            },
        },
    )
    return path


def _encoder_factory():
    encoders = (
        _ContentEncoder("semantic-space", ("text",), "a" * 40),
        _ContentEncoder(
            "visual-space",
            ("text", "image", "video", "3d"),
            "b" * 40,
        ),
        _ContentEncoder("audio-space", ("text", "audio"), "c" * 40),
    )
    return {encoder.embedding_space.space_id: encoder for encoder in encoders}


def test_public_suite_rejects_semantic_asset_metadata(tmp_path):
    suite = _build_suite(tmp_path, leak=True)

    with pytest.raises(ValueError, match="semantic leakage fields: label"):
        load_public_multimodal_suite(suite)


def test_public_benchmark_exercises_cross_modal_restart_and_evidence(tmp_path):
    suite = _build_suite(tmp_path)
    result_path = tmp_path / "multimodal-result.json"
    result = write_public_multimodal_benchmark_artifacts(
        suite,
        output_dir=tmp_path / "output",
        result_path=result_path,
        repeats=3,
        batch_size=2,
        top_k=2,
        lifecycle_artifact=_lifecycle_artifact(tmp_path),
        encoder_factory=_encoder_factory,
    )

    assert result["schema"] == PUBLIC_MULTIMODAL_RESULT_SCHEMA
    assert result["status"] == "fail"
    assert result["admission_eligible"] is False
    assert result["payload_count"] == 5
    assert result["query_count"] == 9
    assert result["metrics"]["macro_precision_at_1"] == 1.0
    assert result["metrics"]["cross_modal_precision_at_1"] == 1.0
    assert result["metrics"]["mixed_multimodal_precision_at_1"] == 1.0
    assert result["metrics"]["persisted_vector_parity"] == 1.0
    assert result["metrics"]["reload_query_parity"] == 1.0
    assert result["repeatability"]["run_count"] == 3
    assert result["repeatability"]["stable_verdict"] is True
    assert {row["precision_at_1"] for row in result["cross_modal_pairs"]} == {
        1.0
    }
    assert result["lifecycle"]["object_store_pass"] is True
    assert len(result["evidence_files"]["per_asset"]["sha256"]) == 64
    assert len(result["evidence_files"]["per_query"]["sha256"]) == 64
    assert json.loads(result_path.read_text(encoding="utf-8")) == result
