from __future__ import annotations

import hashlib
import json
import time
from dataclasses import dataclass, field
from typing import Any, Iterable, Mapping

from .storage import MemoryRecord


FIELD_STATE_DELTA_FORMAT = "wavemind.field_state_delta.v1"


def stable_memory_key(
    *,
    namespace: str,
    text: str,
    tags: Iterable[str] = (),
    metadata: dict[str, Any] | None = None,
) -> str:
    """Build the same public memory key on independent replicas."""

    metadata = metadata or {}
    replica_key = metadata.get("_wavemind_replica_key")
    if isinstance(replica_key, str) and replica_key:
        return replica_key
    public_metadata = {
        str(key): value
        for key, value in metadata.items()
        if not str(key).startswith("_wavemind_")
    }
    payload = {
        "namespace": namespace,
        "text": text,
        "tags": sorted(str(tag) for tag in tags),
        "metadata": public_metadata,
    }
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def stable_record_key(record: MemoryRecord) -> str:
    return stable_memory_key(
        namespace=record.namespace,
        text=record.text,
        tags=record.tags,
        metadata=record.metadata,
    )


@dataclass(frozen=True)
class FieldStateDelta:
    """Serializable active-active delta for field activation state."""

    namespace: str
    positive: dict[str, dict[str, float]] = field(default_factory=dict)
    negative: dict[str, dict[str, float]] = field(default_factory=dict)
    tombstones: dict[str, dict[str, float]] = field(default_factory=dict)
    watermarks: dict[str, float] = field(default_factory=dict)
    created_at: float = field(default_factory=time.time)
    format: str = FIELD_STATE_DELTA_FORMAT

    def to_dict(self) -> dict[str, Any]:
        return {
            "format": self.format,
            "namespace": self.namespace,
            "created_at": float(self.created_at),
            "positive": _copy_counter_tree(self.positive),
            "negative": _copy_counter_tree(self.negative),
            "tombstones": _copy_counter_tree(self.tombstones),
            "watermarks": {
                str(actor): float(value)
                for actor, value in sorted(self.watermarks.items())
            },
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "FieldStateDelta":
        if payload.get("format") != FIELD_STATE_DELTA_FORMAT:
            raise ValueError("Unsupported field state delta format")
        return cls(
            namespace=str(payload.get("namespace") or "default"),
            created_at=float(payload.get("created_at", time.time())),
            positive=_coerce_counter_tree(payload.get("positive")),
            negative=_coerce_counter_tree(payload.get("negative")),
            tombstones=_coerce_counter_tree(payload.get("tombstones")),
            watermarks=_coerce_watermarks(payload.get("watermarks")),
        )


@dataclass
class FieldStateMergeReport:
    namespace: str
    positive_keys: int = 0
    negative_keys: int = 0
    tombstone_keys: int = 0
    changed_cells: int = 0
    watermark_actors: int = 0
    changed_watermarks: int = 0

    @property
    def changed(self) -> bool:
        return self.changed_cells > 0 or self.changed_watermarks > 0

    def as_dict(self) -> dict[str, Any]:
        return {
            "namespace": self.namespace,
            "positive_keys": self.positive_keys,
            "negative_keys": self.negative_keys,
            "tombstone_keys": self.tombstone_keys,
            "changed_cells": self.changed_cells,
            "watermark_actors": self.watermark_actors,
            "changed_watermarks": self.changed_watermarks,
            "changed": self.changed,
        }


@dataclass(frozen=True)
class FieldStateWatermarkHealthReport:
    namespace: str
    region_count: int
    expected_actors: tuple[str, ...]
    observed_actors: tuple[str, ...]
    max_lag_seconds: float
    missing_by_region: dict[str, tuple[str, ...]] = field(default_factory=dict)
    lag_by_region: dict[str, dict[str, float]] = field(default_factory=dict)
    stale_by_region: dict[str, dict[str, float]] = field(default_factory=dict)

    @property
    def healthy(self) -> bool:
        return not any(self.missing_by_region.values()) and not any(
            self.stale_by_region.values()
        )

    @property
    def status(self) -> str:
        return "pass" if self.healthy else "action_required"

    @property
    def max_observed_lag_seconds(self) -> float:
        max_lag = 0.0
        for actor_lags in self.lag_by_region.values():
            for lag in actor_lags.values():
                max_lag = max(max_lag, float(lag))
        return max_lag

    def as_dict(self) -> dict[str, Any]:
        return {
            "namespace": self.namespace,
            "region_count": self.region_count,
            "expected_actors": list(self.expected_actors),
            "observed_actors": list(self.observed_actors),
            "max_lag_seconds": self.max_lag_seconds,
            "max_observed_lag_seconds": self.max_observed_lag_seconds,
            "missing_by_region": {
                region: list(actors)
                for region, actors in sorted(self.missing_by_region.items())
            },
            "lag_by_region": {
                region: {
                    actor: float(lag)
                    for actor, lag in sorted(actor_lags.items())
                }
                for region, actor_lags in sorted(self.lag_by_region.items())
            },
            "stale_by_region": {
                region: {
                    actor: float(lag)
                    for actor, lag in sorted(actor_lags.items())
                }
                for region, actor_lags in sorted(self.stale_by_region.items())
            },
            "healthy": self.healthy,
            "status": self.status,
        }


class FieldStateCRDT:
    """PN-counter field state with add-wins tombstones.

    The vector index still finds candidates. This state captures distributed
    memory-field signals such as repeated recall, explicit suppression, and
    deletion. Merge is deterministic, commutative, and idempotent, so regions
    can exchange deltas in any order without double-counting signals.
    """

    def __init__(self, namespace: str = "default", actor: str = "local") -> None:
        self.namespace = str(namespace or "default")
        self.actor = str(actor or "local")
        self.positive: dict[str, dict[str, float]] = {}
        self.negative: dict[str, dict[str, float]] = {}
        self.tombstones: dict[str, dict[str, float]] = {}
        self.watermarks: dict[str, float] = {}

    def boost(
        self,
        key: str,
        amount: float = 1.0,
        *,
        actor: str | None = None,
        observed_at: float | None = None,
    ) -> None:
        self._increment(self.positive, key, amount, actor=actor, observed_at=observed_at)

    def suppress(
        self,
        key: str,
        amount: float = 1.0,
        *,
        actor: str | None = None,
        observed_at: float | None = None,
    ) -> None:
        self._increment(self.negative, key, amount, actor=actor, observed_at=observed_at)

    def tombstone(
        self,
        key: str,
        *,
        actor: str | None = None,
        deleted_at: float | None = None,
    ) -> None:
        key = str(key)
        if not key:
            return
        actor = str(actor or self.actor)
        deleted_at = time.time() if deleted_at is None else float(deleted_at)
        by_actor = self.tombstones.setdefault(key, {})
        by_actor[actor] = max(float(by_actor.get(actor, 0.0)), deleted_at)
        self._mark_watermark(actor, deleted_at)

    def merge(self, other: "FieldStateCRDT | FieldStateDelta | dict[str, Any]") -> FieldStateMergeReport:
        delta = _as_delta(other)
        if delta.namespace != self.namespace:
            raise ValueError(
                f"Cannot merge field state for namespace {delta.namespace!r} "
                f"into {self.namespace!r}"
            )
        report = FieldStateMergeReport(namespace=self.namespace)
        report.changed_cells += _merge_counter_tree(self.positive, delta.positive)
        report.changed_cells += _merge_counter_tree(self.negative, delta.negative)
        report.changed_cells += _merge_counter_tree(self.tombstones, delta.tombstones)
        report.changed_watermarks += _merge_watermarks(self.watermarks, delta.watermarks)
        report.positive_keys = len(delta.positive)
        report.negative_keys = len(delta.negative)
        report.tombstone_keys = len(delta.tombstones)
        report.watermark_actors = len(delta.watermarks)
        return report

    def delta(self, keys: Iterable[str] | None = None) -> FieldStateDelta:
        selected = None if keys is None else {str(key) for key in keys}
        positive = _select_counter_tree(self.positive, selected)
        negative = _select_counter_tree(self.negative, selected)
        tombstones = _select_counter_tree(self.tombstones, selected)
        actors = None if selected is None else _actors_in_counter_trees(
            positive,
            negative,
            tombstones,
        )
        return FieldStateDelta(
            namespace=self.namespace,
            positive=positive,
            negative=negative,
            tombstones=tombstones,
            watermarks=_select_watermarks(self.watermarks, actors),
        )

    def to_dict(self) -> dict[str, Any]:
        return self.delta().to_dict()

    @classmethod
    def from_dict(cls, payload: dict[str, Any], *, actor: str = "local") -> "FieldStateCRDT":
        delta = FieldStateDelta.from_dict(payload)
        state = cls(namespace=delta.namespace, actor=actor)
        state.merge(delta)
        return state

    def is_tombstoned(self, key: str) -> bool:
        return bool(self.tombstones.get(str(key)))

    def signed_energy(self, key: str) -> float:
        key = str(key)
        if self.is_tombstoned(key):
            return 0.0
        return _sum_counter(self.positive.get(key, {})) - _sum_counter(
            self.negative.get(key, {})
        )

    def activation(self, key: str) -> float:
        return max(0.0, self.signed_energy(key))

    def top(self, limit: int = 10) -> list[tuple[str, float]]:
        scored = [
            (key, self.activation(key))
            for key in set(self.positive) | set(self.negative)
            if not self.is_tombstoned(key)
        ]
        scored = [(key, value) for key, value in scored if value > 0.0]
        scored.sort(key=lambda item: (-item[1], item[0]))
        return scored[: max(0, int(limit))]

    def watermark(self, actor: str | None = None) -> float:
        if actor is not None:
            return float(self.watermarks.get(str(actor), 0.0))
        if not self.watermarks:
            return 0.0
        return max(float(value) for value in self.watermarks.values())

    def covered_actors(self) -> tuple[str, ...]:
        return tuple(sorted(self.watermarks))

    def stats(self) -> dict[str, Any]:
        return {
            "namespace": self.namespace,
            "positive_keys": len(self.positive),
            "negative_keys": len(self.negative),
            "tombstone_keys": len(self.tombstones),
            "watermark_actors": len(self.watermarks),
            "watermark": self.watermark(),
            "total_activation": round(sum(value for _, value in self.top(limit=100_000)), 6),
        }

    def _increment(
        self,
        target: dict[str, dict[str, float]],
        key: str,
        amount: float,
        *,
        actor: str | None = None,
        observed_at: float | None = None,
    ) -> None:
        key = str(key)
        amount = float(amount)
        if not key or amount <= 0.0:
            return
        actor = str(actor or self.actor)
        by_actor = target.setdefault(key, {})
        by_actor[actor] = float(by_actor.get(actor, 0.0)) + amount
        self._mark_watermark(actor, observed_at)

    def _mark_watermark(self, actor: str, observed_at: float | None = None) -> None:
        actor = str(actor or self.actor)
        if not actor:
            return
        observed_at = time.time() if observed_at is None else float(observed_at)
        self.watermarks[actor] = max(float(self.watermarks.get(actor, 0.0)), observed_at)


def _as_delta(value: FieldStateCRDT | FieldStateDelta | dict[str, Any]) -> FieldStateDelta:
    if isinstance(value, FieldStateCRDT):
        return value.delta()
    if isinstance(value, FieldStateDelta):
        return value
    if isinstance(value, dict):
        return FieldStateDelta.from_dict(value)
    raise TypeError(f"Unsupported field state payload: {type(value)!r}")


def audit_field_state_watermarks(
    regions: Mapping[str, FieldStateCRDT | FieldStateDelta | dict[str, Any]],
    *,
    expected_actors: Iterable[str] | None = None,
    max_lag_seconds: float = 0.0,
) -> FieldStateWatermarkHealthReport:
    """Compare actor watermarks across active-active field-state replicas."""

    if not regions:
        raise ValueError("At least one region is required")
    max_lag_seconds = max(0.0, float(max_lag_seconds))
    namespace: str | None = None
    region_watermarks: dict[str, dict[str, float]] = {}
    observed_actors: set[str] = set()
    for raw_region, payload in sorted(regions.items()):
        region = str(raw_region)
        if not region:
            raise ValueError("Region id cannot be empty")
        delta = _as_delta(payload)
        if namespace is None:
            namespace = delta.namespace
        elif delta.namespace != namespace:
            raise ValueError(
                f"Cannot audit field state for namespace {delta.namespace!r} "
                f"with namespace {namespace!r}"
            )
        watermarks = {
            str(actor): float(value)
            for actor, value in sorted(delta.watermarks.items())
        }
        region_watermarks[region] = watermarks
        observed_actors.update(watermarks)
    actors = set(observed_actors)
    if expected_actors is not None:
        actors.update(str(actor) for actor in expected_actors)
    global_watermarks = {
        actor: max(
            float(watermarks.get(actor, 0.0))
            for watermarks in region_watermarks.values()
        )
        for actor in actors
    }
    missing_by_region: dict[str, tuple[str, ...]] = {}
    lag_by_region: dict[str, dict[str, float]] = {}
    stale_by_region: dict[str, dict[str, float]] = {}
    for region, watermarks in sorted(region_watermarks.items()):
        missing = tuple(sorted(actor for actor in actors if actor not in watermarks))
        missing_by_region[region] = missing
        actor_lags = {
            actor: round(max(0.0, global_watermarks[actor] - float(value)), 6)
            for actor, value in sorted(watermarks.items())
            if actor in actors
        }
        stale = {
            actor: lag
            for actor, lag in actor_lags.items()
            if lag > max_lag_seconds
        }
        lag_by_region[region] = actor_lags
        stale_by_region[region] = stale
    return FieldStateWatermarkHealthReport(
        namespace=namespace or "default",
        region_count=len(region_watermarks),
        expected_actors=tuple(sorted(actors)),
        observed_actors=tuple(sorted(observed_actors)),
        max_lag_seconds=max_lag_seconds,
        missing_by_region=missing_by_region,
        lag_by_region=lag_by_region,
        stale_by_region=stale_by_region,
    )


def _copy_counter_tree(source: dict[str, dict[str, float]]) -> dict[str, dict[str, float]]:
    return {
        str(key): {str(actor): float(value) for actor, value in counters.items()}
        for key, counters in source.items()
    }


def _coerce_counter_tree(value: Any) -> dict[str, dict[str, float]]:
    if not isinstance(value, dict):
        return {}
    tree: dict[str, dict[str, float]] = {}
    for raw_key, raw_counters in value.items():
        if not isinstance(raw_counters, dict):
            continue
        counters: dict[str, float] = {}
        for raw_actor, raw_value in raw_counters.items():
            try:
                counter = float(raw_value)
            except (TypeError, ValueError):
                continue
            if counter >= 0.0:
                counters[str(raw_actor)] = counter
        if counters:
            tree[str(raw_key)] = counters
    return tree


def _coerce_watermarks(value: Any) -> dict[str, float]:
    if not isinstance(value, dict):
        return {}
    watermarks: dict[str, float] = {}
    for raw_actor, raw_value in value.items():
        try:
            observed_at = float(raw_value)
        except (TypeError, ValueError):
            continue
        if observed_at >= 0.0:
            watermarks[str(raw_actor)] = observed_at
    return watermarks


def _select_counter_tree(
    source: dict[str, dict[str, float]],
    selected: set[str] | None,
) -> dict[str, dict[str, float]]:
    if selected is None:
        return _copy_counter_tree(source)
    return {
        key: {actor: float(value) for actor, value in counters.items()}
        for key, counters in source.items()
        if key in selected
    }


def _actors_in_counter_trees(
    *trees: dict[str, dict[str, float]],
) -> set[str]:
    actors: set[str] = set()
    for tree in trees:
        for counters in tree.values():
            actors.update(str(actor) for actor in counters)
    return actors


def _select_watermarks(
    source: dict[str, float],
    selected_actors: set[str] | None,
) -> dict[str, float]:
    if selected_actors is None:
        return {str(actor): float(value) for actor, value in source.items()}
    return {
        str(actor): float(value)
        for actor, value in source.items()
        if actor in selected_actors
    }


def _merge_counter_tree(
    target: dict[str, dict[str, float]],
    incoming: dict[str, dict[str, float]],
) -> int:
    changed = 0
    for key, counters in incoming.items():
        target_counters = target.setdefault(str(key), {})
        for actor, value in counters.items():
            actor = str(actor)
            value = float(value)
            if value > float(target_counters.get(actor, 0.0)):
                target_counters[actor] = value
                changed += 1
    return changed


def _merge_watermarks(target: dict[str, float], incoming: dict[str, float]) -> int:
    changed = 0
    for actor, value in incoming.items():
        actor = str(actor)
        value = float(value)
        if value > float(target.get(actor, 0.0)):
            target[actor] = value
            changed += 1
    return changed


def _sum_counter(counter: dict[str, float]) -> float:
    return float(sum(float(value) for value in counter.values()))
