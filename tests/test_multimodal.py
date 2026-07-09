import pytest

import numpy as np

from wavemind import (
    CrossModalEncoderHealthReport,
    CrossModalMemoryLayer,
    HashingTextEncoder,
    KnowledgeGraphMemoryLayer,
    CrossModalContractFixture,
    ObjectStoreAssetReport,
    PrecomputedCrossModalEncoder,
    SentenceTransformersCrossModalEncoder,
    TemporalEventMemoryLayer,
    WaveMind,
    asset3d_payload,
    audio_payload,
    check_cross_modal_encoder_health,
    event_payload,
    graph_payload,
    image_payload,
    normalize_timestamp,
    remember_payload,
    table_payload,
    timestamp_epoch,
    validate_precomputed_cross_modal_contract,
    video_payload,
)


def _one_hot(index: int, dim: int = 4) -> list[float]:
    vector = [0.0] * dim
    vector[index] = 1.0
    return vector


class _FakeClipModel:
    def get_sentence_embedding_dimension(self):
        return 4

    def encode(self, values, **kwargs):
        vectors = []
        for value in values:
            text = str(value).lower()
            if "image-object:chart.png" in text or "chart" in text or "visual" in text:
                vectors.append(_one_hot(0))
            elif "audio" in text or "call" in text:
                vectors.append(_one_hot(1))
            elif "video" in text:
                vectors.append(_one_hot(2))
            else:
                vectors.append(_one_hot(3))
        return np.asarray(vectors, dtype=np.float32)


class _RuleBasedCrossModalEncoder:
    name = "rule-based-health"
    vector_dim = 7
    _modalities = ("image", "audio", "table", "event", "video", "3d", "graph")

    def encode_payload(self, payload, descriptor):
        return self._encode(descriptor)

    def encode_query(self, query, *, target_modality, descriptor):
        return self._encode(descriptor)

    def _encode(self, text):
        lowered = str(text).lower()
        for index, modality in enumerate(self._modalities):
            if f"modality: {modality}" in lowered or f"target modality: {modality}" in lowered:
                return np.asarray(_one_hot(index, self.vector_dim), dtype=np.float32)
        raise ValueError(f"cannot route fixture text: {text}")


class _CollapsedCrossModalEncoder:
    name = "collapsed-health"
    vector_dim = 7

    def encode_payload(self, payload, descriptor):
        return np.asarray(_one_hot(0, self.vector_dim), dtype=np.float32)

    def encode_query(self, query, *, target_modality, descriptor):
        return np.asarray(_one_hot(0, self.vector_dim), dtype=np.float32)


def test_structured_and_multimodal_payloads_are_queryable(tmp_path):
    memory = WaveMind(
        db_path=tmp_path / "payloads.sqlite3",
        encoder=HashingTextEncoder(vector_dim=64),
        width=16,
        height=16,
        layers=1,
    )
    try:
        image_id = remember_payload(
            memory,
            image_payload(
                "s3://bucket/chart.png",
                caption="monthly revenue chart shows enterprise expansion",
                tags=["report"],
            ),
            namespace="research",
        )
        audio_id = remember_payload(
            memory,
            audio_payload(
                "call.wav",
                transcript="customer asked for audit logs and SSO",
                tags=["call"],
            ),
            namespace="research",
        )
        table_id = remember_payload(
            memory,
            table_payload(
                [{"segment": "enterprise", "arr": 2000}],
                title="ARR by segment",
                tags=["table"],
            ),
            namespace="research",
        )
        event_id = remember_payload(
            memory,
            event_payload(
                "user upgraded plan",
                actor="tenant:acme",
                properties={"plan": "enterprise"},
                tags=["event"],
            ),
            namespace="research",
        )
        video_id = remember_payload(
            memory,
            video_payload(
                "s3://bucket/demo.mp4",
                summary="demo video shows a memory graph heatmap",
                transcript="the agent recalls stale facts and suppresses old preferences",
                scenes=["memory graph heatmap", "stale fact suppression"],
                duration_seconds=42.5,
                tags=["video"],
            ),
            namespace="research",
        )
        asset_id = remember_payload(
            memory,
            asset3d_payload(
                "s3://bucket/robot-arm.glb",
                description="3D robot arm model for warehouse picking simulation",
                format="glb",
                labels=["robot arm", "warehouse", "picking"],
                dimensions={"unit": "m", "height": 1.2},
                tags=["asset"],
            ),
            namespace="research",
        )
        graph_id = remember_payload(
            memory,
            graph_payload(
                [
                    ("Andrey", "works_on", "trading agent"),
                    {"subject": "trading agent", "predicate": "uses", "object": "WaveMind memory"},
                ],
                title="agent knowledge graph",
                summary="Andrey's trading agent uses WaveMind memory",
                tags=["graph"],
            ),
            namespace="research",
        )

        image = memory.query("enterprise expansion chart", namespace="research", tags=["image"], top_k=1)
        audio = memory.query("audit logs SSO", namespace="research", tags=["audio"], top_k=1)
        table = memory.query("ARR enterprise segment", namespace="research", tags=["table"], top_k=1)
        event = memory.query("upgraded enterprise plan", namespace="research", tags=["event"], top_k=1)
        video = memory.query("memory graph stale fact suppression", namespace="research", tags=["video"], top_k=1)
        asset = memory.query("warehouse robot arm picking", namespace="research", tags=["3d"], top_k=1)
        graph = memory.query("trading agent uses WaveMind memory", namespace="research", tags=["graph"], top_k=1)

        assert image[0].id == image_id
        assert audio[0].id == audio_id
        assert table[0].id == table_id
        assert event[0].id == event_id
        assert video[0].id == video_id
        assert asset[0].id == asset_id
        assert graph[0].id == graph_id
        assert image[0].metadata["modality"] == "image"
        assert audio[0].metadata["modality"] == "audio"
        assert video[0].metadata["modality"] == "video"
        assert video[0].metadata["duration_seconds"] == 42.5
        assert asset[0].metadata["modality"] == "3d"
        assert graph[0].metadata["modality"] == "graph"
        assert graph[0].metadata["triple_count"] == 2
    finally:
        memory.close()


def test_cross_modal_memory_layer_reranks_typed_payloads(tmp_path):
    memory = WaveMind(
        db_path=tmp_path / "cross-modal.sqlite3",
        encoder=HashingTextEncoder(vector_dim=64),
        width=16,
        height=16,
        layers=1,
    )
    try:
        layer = CrossModalMemoryLayer(memory, vector_dim=64)
        image_id = layer.remember(
            image_payload(
                "s3://bucket/revenue.png",
                caption="enterprise expansion revenue chart",
                tags=["report"],
            ),
            namespace="workspace",
        )
        audio_id = layer.remember(
            audio_payload(
                "support-call.wav",
                transcript="customer asked for SSO and audit log export",
                tags=["call"],
            ),
            namespace="workspace",
        )
        graph_id = layer.remember(
            graph_payload(
                [
                    ("trading agent", "uses", "WaveMind memory"),
                    ("WaveMind memory", "stores", "dynamic user preferences"),
                ],
                title="agent memory graph",
                summary="trading agent uses WaveMind memory",
                tags=["graph"],
            ),
            namespace="workspace",
        )

        image = layer.query(
            "visual chart about enterprise revenue expansion",
            namespace="workspace",
            target_modality="image",
            top_k=1,
        )
        audio = layer.query(
            "voice call where customer requested audit logs and SSO",
            namespace="workspace",
            target_modality="audio",
            top_k=1,
        )
        graph = layer.query(
            "relationship graph showing trading agent uses WaveMind memory",
            namespace="workspace",
            top_k=1,
        )

        assert image[0].id == image_id
        assert image[0].modality == "image"
        assert image[0].provenance["uri"] == "s3://bucket/revenue.png"
        assert image[0].matched_features
        assert audio[0].id == audio_id
        assert audio[0].modality == "audio"
        assert audio[0].provenance["uri"] == "support-call.wav"
        assert graph[0].id == graph_id
        assert graph[0].modality == "graph"
        assert graph[0].score >= graph[0].cross_modal_score * 0.7
    finally:
        memory.close()


def test_cross_modal_memory_layer_uses_persisted_payload_metadata(tmp_path):
    db_path = tmp_path / "cross-modal-persist.sqlite3"
    first = WaveMind(
        db_path=db_path,
        encoder=HashingTextEncoder(vector_dim=64),
        width=16,
        height=16,
        layers=1,
    )
    try:
        layer = CrossModalMemoryLayer(first, vector_dim=64)
        stored_id = layer.remember(
            video_payload(
                "s3://bucket/demo.mp4",
                summary="memory graph heatmap demo",
                transcript="agent suppresses stale facts after corrections",
                scenes=["memory graph heatmap", "stale fact suppression"],
                tags=["video"],
            ),
            namespace="workspace",
        )
    finally:
        first.close()

    second = WaveMind(
        db_path=db_path,
        encoder=HashingTextEncoder(vector_dim=64),
        width=16,
        height=16,
        layers=1,
    )
    try:
        layer = CrossModalMemoryLayer(second, vector_dim=64)
        results = layer.query(
            "video scene about stale fact suppression in a memory graph",
            namespace="workspace",
            target_modality="video",
            top_k=1,
        )
        assert results[0].id == stored_id
        assert results[0].metadata["cross_modal_version"] == "wavemind.cross_modal.v1"
        assert results[0].provenance["source"] == "wavemind_cross_modal"
    finally:
        second.close()


def test_cross_modal_payload_provenance_includes_verified_asset_manifest(tmp_path):
    asset = ObjectStoreAssetReport(
        uri="s3://wavemind-assets/media/aa/demo.mp4",
        bucket="wavemind-assets",
        key="media/aa/demo.mp4",
        total_bytes=1024,
        sha256="a" * 64,
        media_type="video/mp4",
        kind="video",
        verified=True,
        etag='"asset-etag"',
    )
    memory = WaveMind(
        db_path=tmp_path / "asset-provenance.sqlite3",
        encoder=HashingTextEncoder(vector_dim=64),
        width=16,
        height=16,
        layers=1,
    )
    try:
        layer = CrossModalMemoryLayer(memory, vector_dim=64)
        stored_id = layer.remember(
            video_payload(
                asset.uri,
                summary="verified product demo video",
                transcript="customer watches the product demo",
                metadata=asset.payload_metadata(),
                tags=["video"],
            ),
            namespace="workspace",
        )

        results = layer.query(
            "product demo video",
            namespace="workspace",
            target_modality="video",
            top_k=1,
        )

        assert results[0].id == stored_id
        assert results[0].provenance["asset_uri"] == asset.uri
        assert results[0].provenance["asset_sha256"] == asset.sha256
        assert results[0].provenance["asset_bytes"] == asset.total_bytes
        assert results[0].provenance["asset_media_type"] == "video/mp4"
        assert results[0].provenance["asset_verified"] is True
    finally:
        memory.close()


def test_cross_modal_memory_layer_uses_precomputed_vectors_without_descriptor_fallback(tmp_path):
    db_path = tmp_path / "precomputed-cross-modal.sqlite3"
    first = WaveMind(
        db_path=db_path,
        encoder=HashingTextEncoder(vector_dim=64),
        width=16,
        height=16,
        layers=1,
    )
    try:
        layer = CrossModalMemoryLayer(
            first,
            cross_modal_encoder=PrecomputedCrossModalEncoder(vector_dim=4, name="test-clip"),
        )
        image_id = layer.remember(
            image_payload(
                "s3://bucket/revenue.png",
                caption="generic image caption that should not drive ranking",
                metadata={"cross_modal_vector": _one_hot(0)},
                tags=["image"],
            ),
            namespace="workspace",
        )
        audio_id = layer.remember(
            audio_payload(
                "s3://bucket/revenue.wav",
                transcript="generic audio transcript that should not drive ranking",
                metadata={"cross_modal_vector": _one_hot(1)},
                tags=["audio"],
            ),
            namespace="workspace",
        )
    finally:
        first.close()

    second = WaveMind(
        db_path=db_path,
        encoder=HashingTextEncoder(vector_dim=64),
        width=16,
        height=16,
        layers=1,
    )
    try:
        layer = CrossModalMemoryLayer(
            second,
            cross_modal_encoder=PrecomputedCrossModalEncoder(vector_dim=4, name="test-clip"),
        )
        image = layer.query(
            "external clip vector query",
            namespace="workspace",
            target_modality="image",
            top_k=1,
            query_vector=np.asarray(_one_hot(0), dtype=np.float32),
        )
        audio = layer.query(
            "external audio vector query",
            namespace="workspace",
            target_modality="audio",
            top_k=1,
            query_vector=_one_hot(1),
        )

        assert image[0].id == image_id
        assert image[0].metadata["cross_modal_encoder"] == "test-clip"
        assert image[0].metadata["cross_modal_embedding_dim"] == 4
        assert image[0].metadata["cross_modal_vector"] == _one_hot(0)
        assert audio[0].id == audio_id
    finally:
        second.close()


def test_precomputed_cross_modal_encoder_requires_vectors(tmp_path):
    memory = WaveMind(
        db_path=tmp_path / "precomputed-required.sqlite3",
        encoder=HashingTextEncoder(vector_dim=64),
        width=16,
        height=16,
        layers=1,
    )
    try:
        layer = CrossModalMemoryLayer(
            memory,
            cross_modal_encoder=PrecomputedCrossModalEncoder(vector_dim=4),
        )
        with pytest.raises(ValueError, match="requires payload metadata"):
            layer.remember(
                image_payload(
                    "s3://bucket/missing-vector.png",
                    caption="no external embedding",
                ),
                namespace="workspace",
            )
    finally:
        memory.close()


def test_cross_modal_query_vector_dimension_is_validated(tmp_path):
    memory = WaveMind(
        db_path=tmp_path / "dimension-check.sqlite3",
        encoder=HashingTextEncoder(vector_dim=64),
        width=16,
        height=16,
        layers=1,
    )
    try:
        layer = CrossModalMemoryLayer(
            memory,
            cross_modal_encoder=PrecomputedCrossModalEncoder(vector_dim=4),
        )
        layer.remember(
            image_payload(
                "s3://bucket/revenue.png",
                caption="external image vector",
                metadata={"cross_modal_vector": _one_hot(0)},
            ),
            namespace="workspace",
        )
        with pytest.raises(ValueError, match="does not match 4"):
            layer.query(
                "wrong vector dim",
                namespace="workspace",
                target_modality="image",
                query_vector=[1.0, 0.0, 0.0],
            )
    finally:
        memory.close()


def test_precomputed_cross_modal_contract_validates_full_external_vector_roundtrip(tmp_path):
    memory = WaveMind(
        db_path=tmp_path / "multimodal-contract.sqlite3",
        encoder=HashingTextEncoder(vector_dim=64),
        width=16,
        height=16,
        layers=1,
    )
    try:
        report = validate_precomputed_cross_modal_contract(memory)

        assert report.ok is True
        assert report.vector_dim == 8
        assert report.modalities == ("image", "audio", "table", "event", "video", "3d", "graph")
        assert report.payloads == 7
        assert report.target_precision_at_1 == 1.0
        assert report.global_precision_at_1 == 1.0
        assert report.target_modality_routing_rate == 1.0
        assert report.persisted_vector_rate == 1.0
        assert report.normalized_vector_rate == 1.0
        assert report.finite_vector_rate == 1.0
        assert report.provenance_rate == 1.0
        assert report.min_global_margin >= report.min_required_margin
        assert report.failures == ()
        assert report.as_dict()["ok"] is True
    finally:
        memory.close()


def test_cross_modal_encoder_health_passes_for_separated_encoder():
    report = check_cross_modal_encoder_health(
        _RuleBasedCrossModalEncoder(),
        min_required_margin=0.20,
        max_payload_encode_ms=1000.0,
        max_query_encode_ms=1000.0,
    )

    assert isinstance(report, CrossModalEncoderHealthReport)
    assert report.ok is True
    assert report.encoder_name == "rule-based-health"
    assert report.vector_dim == 7
    assert report.modalities == ("image", "audio", "table", "event", "video", "3d", "graph")
    assert report.global_precision_at_1 == 1.0
    assert report.target_modality_routing_rate == 1.0
    assert report.finite_payload_vector_rate == 1.0
    assert report.normalized_payload_vector_rate == 1.0
    assert report.finite_query_vector_rate == 1.0
    assert report.normalized_query_vector_rate == 1.0
    assert report.dimension_match_rate == 1.0
    assert report.min_global_margin >= 0.20
    assert report.as_dict()["ok"] is True


def test_cross_modal_encoder_health_fails_collapsed_embedding_space():
    report = check_cross_modal_encoder_health(
        _CollapsedCrossModalEncoder(),
        min_required_margin=0.20,
        max_payload_encode_ms=1000.0,
        max_query_encode_ms=1000.0,
    )

    assert report.ok is False
    assert report.global_precision_at_1 < 1.0
    assert report.min_global_margin < report.min_required_margin
    assert "global precision@1 below required threshold" in report.failures
    assert "global separation margin below required threshold" in report.failures


def test_precomputed_cross_modal_contract_fails_when_vectors_are_not_separated(tmp_path):
    memory = WaveMind(
        db_path=tmp_path / "multimodal-contract-fail.sqlite3",
        encoder=HashingTextEncoder(vector_dim=64),
        width=16,
        height=16,
        layers=1,
    )
    try:
        shared = (1.0, 0.0, 0.0, 0.0)
        fixtures = (
            CrossModalContractFixture(
                modality="image",
                payload=image_payload(
                    "s3://contract/revenue.png",
                    caption="revenue chart",
                    metadata={"cross_modal_vector": shared},
                ),
                query="revenue chart",
                query_vector=shared,
            ),
            CrossModalContractFixture(
                modality="audio",
                payload=audio_payload(
                    "s3://contract/revenue.wav",
                    transcript="revenue call",
                    metadata={"cross_modal_vector": shared},
                ),
                query="revenue call",
                query_vector=shared,
            ),
        )

        report = validate_precomputed_cross_modal_contract(
            memory,
            fixtures=fixtures,
            vector_dim=4,
            min_required_margin=0.20,
        )

        assert report.ok is False
        assert report.min_global_margin < report.min_required_margin
        assert "global separation margin below required threshold" in report.failures
    finally:
        memory.close()


def test_sentence_transformers_cross_modal_encoder_uses_local_image_loader(tmp_path):
    image_path = tmp_path / "chart.png"
    image_path.write_bytes(b"not-a-real-image-for-fake-loader")
    memory = WaveMind(
        db_path=tmp_path / "st-clip.sqlite3",
        encoder=HashingTextEncoder(vector_dim=64),
        width=16,
        height=16,
        layers=1,
    )
    try:
        encoder = SentenceTransformersCrossModalEncoder(
            "fake-clip",
            model=_FakeClipModel(),
            image_loader=lambda path: f"image-object:{path.name}",
        )
        layer = CrossModalMemoryLayer(memory, cross_modal_encoder=encoder)
        image_id = layer.remember(
            image_payload(
                image_path,
                caption="generic local image payload",
            ),
            namespace="workspace",
        )

        results = layer.query(
            "visual chart query",
            namespace="workspace",
            target_modality="image",
            top_k=1,
        )

        assert results[0].id == image_id
        assert results[0].metadata["cross_modal_encoder"] == "sentence-transformers/fake-clip"
        assert results[0].metadata["cross_modal_embedding_dim"] == 4
        assert results[0].metadata["cross_modal_vector"] == _one_hot(0)
    finally:
        memory.close()


def test_sentence_transformers_cross_modal_encoder_uses_descriptor_for_remote_assets(tmp_path):
    memory = WaveMind(
        db_path=tmp_path / "st-remote.sqlite3",
        encoder=HashingTextEncoder(vector_dim=64),
        width=16,
        height=16,
        layers=1,
    )
    try:
        calls = []
        encoder = SentenceTransformersCrossModalEncoder(
            "fake-clip",
            model=_FakeClipModel(),
            image_loader=lambda path: calls.append(path) or f"image-object:{path.name}",
        )
        layer = CrossModalMemoryLayer(memory, cross_modal_encoder=encoder)
        image_id = layer.remember(
            image_payload(
                "s3://bucket/chart.png",
                caption="remote chart payload descriptor",
            ),
            namespace="workspace",
        )

        results = layer.query(
            "chart",
            namespace="workspace",
            target_modality="image",
            top_k=1,
        )

        assert results[0].id == image_id
        assert calls == []
        assert results[0].metadata["cross_modal_vector"] == _one_hot(0)
    finally:
        memory.close()


def test_knowledge_graph_memory_layer_filters_triples(tmp_path):
    memory = WaveMind(
        db_path=tmp_path / "knowledge-graph.sqlite3",
        encoder=HashingTextEncoder(vector_dim=64),
        width=16,
        height=16,
        layers=1,
    )
    try:
        layer = KnowledgeGraphMemoryLayer(memory)
        graph_id = layer.remember_triples(
            [
                ("Andrey", "works_on", "trading agent"),
                ("trading agent", "uses", "WaveMind memory"),
                ("WaveMind memory", "stores", "dynamic preferences"),
            ],
            namespace="graph",
            title="agent memory graph",
            summary="Andrey's trading agent uses WaveMind memory",
            tags=["agent"],
        )

        results = layer.query(
            "what does the trading agent use?",
            namespace="graph",
            subject="trading agent",
            predicate="uses",
            top_k=1,
        )

        assert results[0].id == graph_id
        assert results[0].subject == "trading agent"
        assert results[0].predicate == "uses"
        assert results[0].object == "WaveMind memory"
        assert results[0].depth == 1
        assert results[0].path == ({"subject": "trading agent", "predicate": "uses", "object": "WaveMind memory"},)
        assert results[0].provenance["memory_id"] == graph_id
        assert results[0].provenance["modality"] == "graph"
        assert results[0].provenance["triple"]["object"] == "WaveMind memory"
    finally:
        memory.close()


def test_knowledge_graph_memory_layer_traverses_paths(tmp_path):
    memory = WaveMind(
        db_path=tmp_path / "knowledge-graph-path.sqlite3",
        encoder=HashingTextEncoder(vector_dim=64),
        width=16,
        height=16,
        layers=1,
    )
    try:
        layer = KnowledgeGraphMemoryLayer(memory)
        layer.remember_triples(
            [("Andrey", "works_on", "trading agent")],
            namespace="graph",
            title="person project edge",
            tags=["agent"],
        )
        final_id = layer.remember_triples(
            [("trading agent", "uses", "WaveMind memory")],
            namespace="graph",
            title="project memory edge",
            tags=["agent"],
        )

        results = layer.query(
            "how is Andrey connected to WaveMind memory?",
            namespace="graph",
            subject="Andrey",
            object="WaveMind memory",
            max_depth=2,
            top_k=1,
        )

        assert results[0].id == final_id
        assert results[0].depth == 2
        assert [step["predicate"] for step in results[0].path] == ["works_on", "uses"]
        assert results[0].subject == "trading agent"
        assert results[0].object == "WaveMind memory"
        assert results[0].provenance["path"][0]["subject"] == "Andrey"
    finally:
        memory.close()


def test_knowledge_graph_memory_layer_persists_graph_records(tmp_path):
    db_path = tmp_path / "knowledge-graph-persist.sqlite3"
    first = WaveMind(
        db_path=db_path,
        encoder=HashingTextEncoder(vector_dim=64),
        width=16,
        height=16,
        layers=1,
    )
    try:
        layer = KnowledgeGraphMemoryLayer(first)
        stored_id = layer.remember_triples(
            [
                ("research agent", "reads", "market filings"),
                ("market filings", "contain", "risk disclosures"),
            ],
            namespace="graph",
            title="research graph",
            tags=["research"],
        )
    finally:
        first.close()

    second = WaveMind(
        db_path=db_path,
        encoder=HashingTextEncoder(vector_dim=64),
        width=16,
        height=16,
        layers=1,
    )
    try:
        layer = KnowledgeGraphMemoryLayer(second)
        results = layer.query(
            "risk disclosures",
            namespace="graph",
            subject="research agent",
            object="risk disclosures",
            max_depth=2,
            top_k=1,
        )

        assert results[0].id == stored_id
        assert results[0].depth == 2
        assert results[0].provenance["triple_count"] == 2
    finally:
        second.close()


def test_knowledge_graph_memory_layer_uses_full_persisted_graph_not_preview(tmp_path):
    memory = WaveMind(
        db_path=tmp_path / "knowledge-graph-full.sqlite3",
        encoder=HashingTextEncoder(vector_dim=64),
        width=16,
        height=16,
        layers=1,
    )
    try:
        layer = KnowledgeGraphMemoryLayer(memory)
        triples = [(f"node-{index}", "connects_to", f"node-{index + 1}") for index in range(14)]
        graph_id = layer.remember_triples(
            triples,
            namespace="graph",
            title="long graph",
            tags=["long"],
        )

        results = layer.query(
            "node 14",
            namespace="graph",
            subject="node-0",
            object="node-14",
            max_depth=14,
            top_k=1,
        )

        assert results[0].id == graph_id
        assert results[0].depth == 14
        assert results[0].path[-1]["object"] == "node-14"
        assert results[0].provenance["triple_count"] == 14
    finally:
        memory.close()


def test_temporal_event_payload_normalizes_interval_metadata(tmp_path):
    memory = WaveMind(
        db_path=tmp_path / "temporal-payload.sqlite3",
        encoder=HashingTextEncoder(vector_dim=64),
        width=16,
        height=16,
        layers=1,
    )
    try:
        payload = event_payload(
            "budget increased",
            actor="tenant:acme",
            timestamp="2026-07-07T10:00:00+03:00",
            duration_seconds=3600,
            properties={"budget": 2000},
            tags=["billing"],
        )
        event_id = remember_payload(memory, payload, namespace="events")
        result = memory.query("budget increased", namespace="events", tags=["event"], top_k=1)[0]

        assert result.id == event_id
        assert result.metadata["timestamp"] == "2026-07-07T07:00:00Z"
        assert result.metadata["timestamp_epoch"] == timestamp_epoch("2026-07-07T07:00:00Z")
        assert result.metadata["end_timestamp"] == "2026-07-07T08:00:00Z"
        assert result.metadata["duration_seconds"] == 3600.0
        assert normalize_timestamp(result.metadata["timestamp"])[0] == "2026-07-07T07:00:00Z"
    finally:
        memory.close()


def test_temporal_event_layer_filters_and_reranks_by_time_window(tmp_path):
    memory = WaveMind(
        db_path=tmp_path / "temporal-layer.sqlite3",
        encoder=HashingTextEncoder(vector_dim=64),
        width=16,
        height=16,
        layers=1,
    )
    try:
        layer = TemporalEventMemoryLayer(memory, base_weight=0.45, temporal_weight=0.55)
        morning_id = layer.remember(
            "risk limits reviewed",
            namespace="events",
            actor="agent:trading",
            timestamp="2026-07-07T09:00:00Z",
            properties={"limit": "morning"},
            tags=["risk"],
        )
        midday_id = layer.remember(
            "risk limits reviewed",
            namespace="events",
            actor="agent:trading",
            timestamp="2026-07-07T12:00:00Z",
            properties={"limit": "midday"},
            tags=["risk"],
        )
        layer.remember(
            "risk limits reviewed",
            namespace="events",
            actor="agent:trading",
            timestamp="2026-07-08T12:00:00Z",
            properties={"limit": "next-day"},
            tags=["risk"],
        )

        around = layer.query(
            "risk limits",
            namespace="events",
            actor="agent:trading",
            around="2026-07-07T12:10:00Z",
            tolerance_seconds=1800,
            top_k=2,
        )
        window = layer.query(
            "risk limits",
            namespace="events",
            start="2026-07-07T08:00:00Z",
            end="2026-07-07T10:00:00Z",
            top_k=5,
        )

        assert around[0].id == midday_id
        assert around[0].temporal_score > around[1].temporal_score
        assert around[0].time_distance_seconds == 600.0
        assert [item.id for item in window] == [morning_id]
    finally:
        memory.close()


def test_temporal_event_layer_recency_and_persistence(tmp_path):
    db_path = tmp_path / "temporal-persist.sqlite3"
    first = WaveMind(
        db_path=db_path,
        encoder=HashingTextEncoder(vector_dim=64),
        width=16,
        height=16,
        layers=1,
    )
    try:
        layer = TemporalEventMemoryLayer(first, base_weight=0.20, temporal_weight=0.80)
        old_id = layer.remember(
            "customer requested SSO",
            namespace="events",
            actor="tenant:acme",
            timestamp="2026-07-01T12:00:00Z",
        )
        fresh_id = layer.remember(
            "customer requested SSO",
            namespace="events",
            actor="tenant:acme",
            timestamp="2026-07-07T12:00:00Z",
        )
    finally:
        first.close()

    second = WaveMind(
        db_path=db_path,
        encoder=HashingTextEncoder(vector_dim=64),
        width=16,
        height=16,
        layers=1,
    )
    try:
        layer = TemporalEventMemoryLayer(second, base_weight=0.20, temporal_weight=0.80)
        results = layer.query(
            "customer requested SSO",
            namespace="events",
            actor="tenant:acme",
            recency_anchor="2026-07-07T13:00:00Z",
            recency_half_life_seconds=24 * 3600,
            top_k=2,
        )

        assert [item.id for item in results] == [fresh_id, old_id]
        assert results[0].temporal_score > results[1].temporal_score
        assert results[0].provenance["timestamp"] == "2026-07-07T12:00:00Z"
        assert results[0].as_dict()["end_timestamp_epoch"] == results[0].timestamp_epoch
    finally:
        second.close()
