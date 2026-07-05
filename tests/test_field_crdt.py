import pytest

from wavemind.field_crdt import FieldStateCRDT, FieldStateDelta, stable_memory_key


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
