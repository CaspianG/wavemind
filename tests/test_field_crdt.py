import pytest

from wavemind.field_crdt import (
    FieldStateCRDT,
    FieldStateDelta,
    audit_field_state_watermarks,
    stable_memory_key,
)


def test_field_state_crdt_merge_is_commutative_and_idempotent():
    key_a = stable_memory_key(namespace="tenant", text="user likes concise answers")
    key_b = stable_memory_key(namespace="tenant", text="user prefers weekly reports")
    region_a = FieldStateCRDT(namespace="tenant", actor="region-a")
    region_b = FieldStateCRDT(namespace="tenant", actor="region-b")

    region_a.boost(key_a, 1.0)
    region_a.suppress(key_b, 0.2)
    region_b.boost(key_a, 0.5)
    region_b.boost(key_b, 1.2)

    left = FieldStateCRDT(namespace="tenant", actor="left")
    left.merge(region_a.delta())
    left.merge(region_b.delta())
    left.merge(region_b.delta())

    right = FieldStateCRDT(namespace="tenant", actor="right")
    right.merge(region_b.delta())
    right.merge(region_a.delta())
    right.merge(region_a.delta())

    assert left.to_dict()["positive"] == right.to_dict()["positive"]
    assert left.to_dict()["negative"] == right.to_dict()["negative"]
    assert left.activation(key_a) == pytest.approx(1.5)
    assert left.activation(key_b) == pytest.approx(1.0)
    assert left.top(limit=2) == [(key_a, pytest.approx(1.5)), (key_b, pytest.approx(1.0))]


def test_field_state_crdt_tombstone_wins_over_stale_boost():
    key = stable_memory_key(namespace="tenant", text="deleted stale memory")
    live_region = FieldStateCRDT(namespace="tenant", actor="region-a")
    stale_region = FieldStateCRDT(namespace="tenant", actor="region-b")

    live_region.boost(key, 10.0)
    stale_region.boost(key, 99.0)
    live_region.tombstone(key, deleted_at=100.0)

    merged = FieldStateCRDT(namespace="tenant", actor="region-c")
    merged.merge(stale_region.delta())
    merged.merge(live_region.delta())
    merged.merge(stale_region.delta())

    assert merged.is_tombstoned(key) is True
    assert merged.activation(key) == 0.0
    assert merged.top(limit=5) == []


def test_field_state_delta_round_trip_and_namespace_guard():
    key = stable_memory_key(namespace="tenant", text="round trip memory")
    state = FieldStateCRDT(namespace="tenant", actor="region-a")
    state.boost(key, 2.5)
    state.suppress(key, 0.5)
    payload = state.to_dict()

    restored = FieldStateCRDT.from_dict(payload, actor="region-b")

    assert restored.activation(key) == pytest.approx(2.0)
    assert FieldStateDelta.from_dict(payload).to_dict()["positive"] == payload["positive"]
    with pytest.raises(ValueError):
        FieldStateCRDT(namespace="other", actor="region-c").merge(payload)


def test_field_state_crdt_watermarks_merge_by_actor_max():
    key = stable_memory_key(namespace="tenant", text="regional hot memory")
    region_a = FieldStateCRDT(namespace="tenant", actor="region-a")
    region_b = FieldStateCRDT(namespace="tenant", actor="region-b")

    region_a.boost(key, 1.0, observed_at=10.0)
    region_a.boost(key, 1.0, observed_at=12.0)
    region_a.suppress(key, 0.25, actor="region-c", observed_at=11.0)
    region_b.boost(key, 3.0, observed_at=9.0)
    region_b.tombstone("stale-key", deleted_at=20.0)

    merged = FieldStateCRDT(namespace="tenant", actor="merged")
    first = merged.merge(region_a.delta())
    second = merged.merge(region_b.delta())
    idempotent = merged.merge(region_b.delta())

    assert first.changed_watermarks == 2
    assert second.changed_watermarks == 1
    assert idempotent.changed is False
    assert merged.watermark("region-a") == 12.0
    assert merged.watermark("region-b") == 20.0
    assert merged.watermark("region-c") == 11.0
    assert merged.watermark() == 20.0
    assert merged.covered_actors() == ("region-a", "region-b", "region-c")
    assert merged.stats()["watermark_actors"] == 3
    assert merged.stats()["watermark"] == 20.0


def test_field_state_partial_delta_carries_only_relevant_actor_watermarks():
    key_a = stable_memory_key(namespace="tenant", text="active memory")
    key_b = stable_memory_key(namespace="tenant", text="other memory")
    state = FieldStateCRDT(namespace="tenant", actor="region-a")
    state.boost(key_a, 1.0, actor="region-a", observed_at=10.0)
    state.boost(key_b, 1.0, actor="region-b", observed_at=20.0)

    delta = state.delta(keys=[key_a]).to_dict()
    restored = FieldStateCRDT(namespace="tenant", actor="region-c")
    report = restored.merge(delta)

    assert delta["watermarks"] == {"region-a": 10.0}
    assert report.watermark_actors == 1
    assert restored.activation(key_a) == 1.0
    assert restored.activation(key_b) == 0.0
    assert restored.watermark("region-a") == 10.0
    assert restored.watermark("region-b") == 0.0


def test_field_state_delta_accepts_legacy_payload_without_watermarks():
    key = stable_memory_key(namespace="tenant", text="legacy memory")
    legacy_payload = {
        "format": "wavemind.field_state_delta.v1",
        "namespace": "tenant",
        "created_at": 1.0,
        "positive": {key: {"legacy-region": 2.0}},
        "negative": {},
        "tombstones": {},
    }

    state = FieldStateCRDT(namespace="tenant", actor="region-a")
    report = state.merge(legacy_payload)

    assert report.changed is True
    assert report.watermark_actors == 0
    assert state.activation(key) == 2.0
    assert state.watermark() == 0.0


def test_field_state_watermark_health_passes_when_regions_cover_same_actors():
    key = stable_memory_key(namespace="tenant", text="shared memory")
    region_a = FieldStateCRDT(namespace="tenant", actor="region-a")
    region_b = FieldStateCRDT(namespace="tenant", actor="region-b")
    region_a.boost(key, actor="region-a", observed_at=10.0)
    region_a.boost(key, actor="region-b", observed_at=20.0)
    region_b.merge(region_a.delta())

    health = audit_field_state_watermarks(
        {"region-a": region_a, "region-b": region_b},
        expected_actors=["region-a", "region-b"],
    )

    assert health.healthy is True
    assert health.status == "pass"
    assert health.expected_actors == ("region-a", "region-b")
    assert health.observed_actors == ("region-a", "region-b")
    assert health.max_observed_lag_seconds == 0.0
    assert health.missing_by_region == {"region-a": (), "region-b": ()}
    assert health.stale_by_region == {"region-a": {}, "region-b": {}}
    assert health.as_dict()["healthy"] is True


def test_field_state_watermark_health_detects_missing_and_stale_actors():
    key = stable_memory_key(namespace="tenant", text="regional memory")
    fresh = FieldStateCRDT(namespace="tenant", actor="region-a")
    stale = FieldStateCRDT(namespace="tenant", actor="region-b")
    fresh.boost(key, actor="region-a", observed_at=100.0)
    fresh.boost(key, actor="region-b", observed_at=90.0)
    stale.boost(key, actor="region-a", observed_at=80.0)

    health = audit_field_state_watermarks(
        {"fresh": fresh, "stale": stale.delta()},
        expected_actors=["region-a", "region-b", "region-c"],
        max_lag_seconds=5.0,
    )

    assert health.healthy is False
    assert health.status == "action_required"
    assert health.missing_by_region["fresh"] == ("region-c",)
    assert health.missing_by_region["stale"] == ("region-b", "region-c")
    assert health.lag_by_region["stale"]["region-a"] == 20.0
    assert health.stale_by_region["stale"] == {"region-a": 20.0}
    assert health.as_dict()["max_observed_lag_seconds"] == 20.0


def test_field_state_watermark_health_rejects_mixed_namespaces():
    left = FieldStateCRDT(namespace="left", actor="region-a")
    right = FieldStateCRDT(namespace="right", actor="region-b")

    with pytest.raises(ValueError):
        audit_field_state_watermarks({"left": left, "right": right})
