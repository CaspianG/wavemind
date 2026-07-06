from wavemind import (
    CrossModalMemoryLayer,
    HashingTextEncoder,
    WaveMind,
    asset3d_payload,
    audio_payload,
    event_payload,
    graph_payload,
    image_payload,
    remember_payload,
    table_payload,
    video_payload,
)


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
