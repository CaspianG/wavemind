from wavemind import (
    HashingTextEncoder,
    WaveMind,
    audio_payload,
    event_payload,
    image_payload,
    remember_payload,
    table_payload,
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

        image = memory.query("enterprise expansion chart", namespace="research", tags=["image"], top_k=1)
        audio = memory.query("audit logs SSO", namespace="research", tags=["audio"], top_k=1)
        table = memory.query("ARR enterprise segment", namespace="research", tags=["table"], top_k=1)
        event = memory.query("upgraded enterprise plan", namespace="research", tags=["event"], top_k=1)

        assert image[0].id == image_id
        assert audio[0].id == audio_id
        assert table[0].id == table_id
        assert event[0].id == event_id
        assert image[0].metadata["modality"] == "image"
        assert audio[0].metadata["modality"] == "audio"
    finally:
        memory.close()
