from wavemind import (
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
