from __future__ import annotations

import hashlib
import json
import re
from collections import defaultdict
from dataclasses import asdict, dataclass
from typing import Any, Iterable


_QUOTED_LABEL_RE = re.compile(r"'([^'\r\n]{1,240})'")


@dataclass(frozen=True)
class TrajectoryConsolidationReport:
    namespace: str | None
    scanned_memories: int
    eligible_memories: int
    trajectories: int
    created: int
    skipped_existing: int
    skipped_empty: int
    source_memories_with_provenance: int
    output_tag: str
    max_summary_chars: int
    errors: tuple[str, ...] = ()

    @property
    def ok(self) -> bool:
        return not self.errors

    @property
    def provenance_coverage(self) -> float:
        if self.created <= 0:
            return 1.0
        return self.source_memories_with_provenance / self.created

    def as_dict(self) -> dict[str, Any]:
        return {
            **asdict(self),
            "errors": list(self.errors),
            "ok": self.ok,
            "provenance_coverage": self.provenance_coverage,
        }


class TrajectoryDeltaConsolidator:
    """Build compact, extractive memories from ordered agent states.

    The consolidator keeps source states intact and adds a derived retrieval
    view containing the goal, outcome, action, thought, and labels newly
    observed at each step. Every derived memory points back to its source
    memory and carries an idempotency signature.
    """

    SOURCE = "wavemind_trajectory_delta"
    TRAJECTORY_SOURCE = "wavemind_trajectory_experience"

    def __init__(self, memory: Any):
        self.memory = memory
        self._summary_by_source_id: dict[int, str] | None = None

    def run_once(
        self,
        *,
        namespace: str | None = None,
        group_metadata_key: str = "trajectory_id",
        position_metadata_key: str = "state_index",
        input_tag: str | None = "trajectory-state",
        output_tag: str = "trajectory-delta",
        max_summary_chars: int = 2_800,
        batch_size: int = 512,
    ) -> TrajectoryConsolidationReport:
        group_metadata_key = group_metadata_key.strip()
        position_metadata_key = position_metadata_key.strip()
        output_tag = output_tag.strip()
        if not group_metadata_key:
            raise ValueError("group_metadata_key must not be empty")
        if not position_metadata_key:
            raise ValueError("position_metadata_key must not be empty")
        if not output_tag:
            raise ValueError("output_tag must not be empty")
        if max_summary_chars < 256:
            raise ValueError("max_summary_chars must be at least 256")
        if batch_size <= 0:
            raise ValueError("batch_size must be positive")

        records = self._records(namespace)
        existing_signatures = {
            str(record.metadata.get("trajectory_delta_signature"))
            for record in records
            if record.metadata.get("source") == self.SOURCE
            and record.metadata.get("trajectory_delta_signature")
        }
        groups: dict[tuple[str, str], list[Any]] = defaultdict(list)
        eligible = 0
        for record in records:
            if record.metadata.get("source") == self.SOURCE:
                continue
            if input_tag and input_tag not in set(record.tags):
                continue
            group = str(record.metadata.get(group_metadata_key) or "").strip()
            if not group:
                continue
            try:
                int(record.metadata.get(position_metadata_key))
            except (TypeError, ValueError):
                continue
            groups[(record.namespace, group)].append(record)
            eligible += 1

        pending: list[dict[str, Any]] = []
        skipped_existing = 0
        skipped_empty = 0
        provenance_count = 0
        for (_, group), group_records in sorted(groups.items()):
            group_records.sort(
                key=lambda record: (
                    int(record.metadata.get(position_metadata_key)),
                    int(record.id or 0),
                )
            )
            prior_labels: set[str] = set()
            for record in group_records:
                labels = _observed_labels(record.text)
                novel_labels = [
                    label
                    for label in labels
                    if label.casefold() not in prior_labels
                ]
                prior_labels.update(label.casefold() for label in labels)
                signature = _signature(
                    record,
                    group=group,
                    position_metadata_key=position_metadata_key,
                    max_summary_chars=max_summary_chars,
                )
                if signature in existing_signatures:
                    skipped_existing += 1
                    continue
                summary = _trajectory_summary(
                    record,
                    labels=labels,
                    novel_labels=novel_labels,
                    position_metadata_key=position_metadata_key,
                    max_chars=max_summary_chars,
                )
                if not summary:
                    skipped_empty += 1
                    continue
                source_id = int(record.id)
                metadata = dict(record.metadata)
                metadata.update(
                    {
                        "source_original": metadata.get("source"),
                        "source": self.SOURCE,
                        "source_memory_ids": [source_id],
                        "trajectory_delta_signature": signature,
                        "trajectory_delta_group": group,
                    }
                )
                pending.append(
                    {
                        "text": summary,
                        "namespace": record.namespace,
                        "tags": tuple(
                            dict.fromkeys(
                                (
                                    *(
                                        tag
                                        for tag in record.tags
                                        if tag != input_tag
                                    ),
                                    output_tag,
                                )
                            )
                        ),
                        "metadata": metadata,
                        "priority": float(record.priority),
                    }
                )
                existing_signatures.add(signature)
                provenance_count += 1

        created = 0
        errors: list[str] = []
        for offset in range(0, len(pending), batch_size):
            batch = pending[offset : offset + batch_size]
            try:
                created += len(self.memory.remember_batch(batch))
            except Exception as exc:  # pragma: no cover - defensive worker boundary
                errors.append(
                    f"batch {offset // batch_size + 1}: "
                    f"{type(exc).__name__}: {exc}"
                )
                break

        self._summary_by_source_id = None
        report = TrajectoryConsolidationReport(
            namespace=namespace,
            scanned_memories=len(records),
            eligible_memories=eligible,
            trajectories=len(groups),
            created=created,
            skipped_existing=skipped_existing,
            skipped_empty=skipped_empty,
            source_memories_with_provenance=min(provenance_count, created),
            output_tag=output_tag,
            max_summary_chars=max_summary_chars,
            errors=tuple(errors),
        )
        store = getattr(self.memory, "store", None)
        log_event = getattr(store, "log_audit_event", None)
        if callable(log_event):
            log_event(
                "consolidate_trajectory_deltas",
                namespace=namespace,
                metadata=report.as_dict(),
            )
        return report

    def run_trajectory_once(
        self,
        *,
        namespace: str | None = None,
        group_metadata_key: str = "trajectory_id",
        position_metadata_key: str = "state_index",
        input_tag: str | None = "trajectory-state",
        output_tag: str = "trajectory-experience",
        max_summary_chars: int = 4_800,
        batch_size: int = 128,
    ) -> TrajectoryConsolidationReport:
        """Build one ordered, extractive experience memory per trajectory."""

        group_metadata_key = group_metadata_key.strip()
        position_metadata_key = position_metadata_key.strip()
        output_tag = output_tag.strip()
        if not group_metadata_key:
            raise ValueError("group_metadata_key must not be empty")
        if not position_metadata_key:
            raise ValueError("position_metadata_key must not be empty")
        if not output_tag:
            raise ValueError("output_tag must not be empty")
        if max_summary_chars < 512:
            raise ValueError("max_summary_chars must be at least 512")
        if batch_size <= 0:
            raise ValueError("batch_size must be positive")

        records = self._records(namespace)
        existing_signatures = {
            str(record.metadata.get("trajectory_experience_signature"))
            for record in records
            if record.metadata.get("source") == self.TRAJECTORY_SOURCE
            and record.metadata.get("trajectory_experience_signature")
        }
        groups: dict[tuple[str, str], list[Any]] = defaultdict(list)
        eligible = 0
        for record in records:
            if record.metadata.get("source") in {
                self.SOURCE,
                self.TRAJECTORY_SOURCE,
            }:
                continue
            if input_tag and input_tag not in set(record.tags):
                continue
            group = str(record.metadata.get(group_metadata_key) or "").strip()
            if not group:
                continue
            try:
                int(record.metadata.get(position_metadata_key))
            except (TypeError, ValueError):
                continue
            groups[(record.namespace, group)].append(record)
            eligible += 1

        pending: list[dict[str, Any]] = []
        skipped_existing = 0
        skipped_empty = 0
        for (record_namespace, group), group_records in sorted(groups.items()):
            group_records.sort(
                key=lambda record: (
                    int(record.metadata.get(position_metadata_key)),
                    int(record.id or 0),
                )
            )
            signature = _trajectory_group_signature(
                group_records,
                group=group,
                position_metadata_key=position_metadata_key,
                max_summary_chars=max_summary_chars,
            )
            if signature in existing_signatures:
                skipped_existing += 1
                continue
            summary = _trajectory_group_summary(
                group_records,
                position_metadata_key=position_metadata_key,
                max_chars=max_summary_chars,
            )
            if not summary:
                skipped_empty += 1
                continue
            source_ids = [int(record.id) for record in group_records]
            metadata = dict(group_records[-1].metadata)
            metadata.update(
                {
                    "source_original": metadata.get("source"),
                    "source": self.TRAJECTORY_SOURCE,
                    "source_memory_ids": source_ids,
                    "trajectory_experience_signature": signature,
                    "trajectory_experience_group": group,
                    "trajectory_state_count": len(source_ids),
                    "trajectory_state_start": int(
                        group_records[0].metadata.get(position_metadata_key)
                    ),
                    "trajectory_state_end": int(
                        group_records[-1].metadata.get(position_metadata_key)
                    ),
                }
            )
            pending.append(
                {
                    "text": summary,
                    "namespace": record_namespace,
                    "tags": tuple(
                        dict.fromkeys(
                            (
                                *(
                                    tag
                                    for tag in group_records[-1].tags
                                    if tag != input_tag
                                ),
                                output_tag,
                            )
                        )
                    ),
                    "metadata": metadata,
                    "priority": max(
                        float(record.priority) for record in group_records
                    ),
                }
            )
            existing_signatures.add(signature)

        created = 0
        errors: list[str] = []
        for offset in range(0, len(pending), batch_size):
            batch = pending[offset : offset + batch_size]
            try:
                created += len(self.memory.remember_batch(batch))
            except Exception as exc:  # pragma: no cover - worker boundary
                errors.append(
                    f"batch {offset // batch_size + 1}: "
                    f"{type(exc).__name__}: {exc}"
                )
                break

        self._summary_by_source_id = None
        report = TrajectoryConsolidationReport(
            namespace=namespace,
            scanned_memories=len(records),
            eligible_memories=eligible,
            trajectories=len(groups),
            created=created,
            skipped_existing=skipped_existing,
            skipped_empty=skipped_empty,
            source_memories_with_provenance=created,
            output_tag=output_tag,
            max_summary_chars=max_summary_chars,
            errors=tuple(errors),
        )
        store = getattr(self.memory, "store", None)
        log_event = getattr(store, "log_audit_event", None)
        if callable(log_event):
            log_event(
                "consolidate_trajectory_experiences",
                namespace=namespace,
                metadata=report.as_dict(),
            )
        return report

    def source_text(self, result: Any) -> str:
        """Return immutable source evidence for a derived query result."""

        source_ids = result.metadata.get("source_memory_ids") or ()
        if not source_ids:
            return str(result.text)
        try:
            source_id = int(source_ids[0])
        except (TypeError, ValueError, IndexError):
            return str(result.text)
        cached = getattr(self.memory, "_records_by_id", None)
        if isinstance(cached, dict):
            record = cached.get(source_id)
            if record is not None:
                return str(record.text)
        store = getattr(self.memory, "store", None)
        get_record = getattr(store, "get", None)
        if callable(get_record):
            record = get_record(source_id)
            if record is not None:
                return str(record.text)
        return str(result.text)

    def source_records(self, result: Any) -> list[Any]:
        """Return all immutable source records linked to a derived result."""

        source_ids = result.metadata.get("source_memory_ids") or ()
        records: list[Any] = []
        cached = getattr(self.memory, "_records_by_id", None)
        store = getattr(self.memory, "store", None)
        get_record = getattr(store, "get", None)
        for raw_id in source_ids:
            try:
                source_id = int(raw_id)
            except (TypeError, ValueError):
                continue
            record = (
                cached.get(source_id)
                if isinstance(cached, dict)
                else None
            )
            if record is None and callable(get_record):
                record = get_record(source_id)
            if record is not None:
                records.append(record)
        return records

    def summary_text(self, result: Any) -> str:
        """Return the extractive summary linked to a raw source result."""

        try:
            source_id = int(result.id)
        except (TypeError, ValueError):
            return ""
        if self._summary_by_source_id is None:
            summaries: dict[int, str] = {}
            for record in self._records(namespace=None):
                if record.metadata.get("source") not in {
                    self.SOURCE,
                    self.TRAJECTORY_SOURCE,
                }:
                    continue
                source_ids = record.metadata.get("source_memory_ids") or ()
                for raw_id in source_ids:
                    try:
                        linked_id = int(raw_id)
                    except (TypeError, ValueError):
                        continue
                    summaries.setdefault(linked_id, str(record.text))
            self._summary_by_source_id = summaries
        return self._summary_by_source_id.get(source_id, "")

    def experience_packet_text(
        self,
        result: Any,
        *,
        source_text: str,
        max_summary_chars: int = 1_000,
    ) -> str:
        """Enrich selected source evidence without changing the shortlist."""

        if max_summary_chars <= 0:
            raise ValueError("max_summary_chars must be positive")
        summary = self.summary_text(result)[:max_summary_chars].strip()
        if not summary:
            return source_text
        return (
            "Exact source state:\n"
            f"{source_text}\n"
            "Related trajectory summary:\n"
            f"{summary}"
        )

    def _records(self, namespace: str | None) -> list[Any]:
        cached = getattr(self.memory, "_records_by_id", None)
        if isinstance(cached, dict):
            records = list(cached.values())
            if namespace is not None:
                records = [
                    record
                    for record in records
                    if record.namespace == namespace
                ]
            return records
        store = getattr(self.memory, "store", None)
        list_records = getattr(store, "list", None)
        if not callable(list_records):
            raise TypeError("memory must expose records or store.list()")
        return list(list_records(namespace=namespace))


def _signature(
    record: Any,
    *,
    group: str,
    position_metadata_key: str,
    max_summary_chars: int,
) -> str:
    payload = {
        "schema": "wavemind.trajectory_delta.v1",
        "namespace": record.namespace,
        "group": group,
        "position": int(record.metadata.get(position_metadata_key)),
        "source_memory_id": int(record.id),
        "source_text_sha256": hashlib.sha256(
            record.text.encode("utf-8")
        ).hexdigest(),
        "max_summary_chars": int(max_summary_chars),
    }
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode(
            "utf-8"
        )
    ).hexdigest()


def _trajectory_group_signature(
    records: list[Any],
    *,
    group: str,
    position_metadata_key: str,
    max_summary_chars: int,
) -> str:
    payload = {
        "schema": "wavemind.trajectory_experience.v1",
        "namespace": records[0].namespace,
        "group": group,
        "states": [
            {
                "position": int(
                    record.metadata.get(position_metadata_key)
                ),
                "source_memory_id": int(record.id),
                "source_text_sha256": hashlib.sha256(
                    record.text.encode("utf-8")
                ).hexdigest(),
            }
            for record in records
        ],
        "max_summary_chars": int(max_summary_chars),
    }
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode(
            "utf-8"
        )
    ).hexdigest()


def _trajectory_group_summary(
    records: list[Any],
    *,
    position_metadata_key: str,
    max_chars: int,
) -> str:
    goal = next(
        (
            value
            for record in records
            if (
                value := _section(
                    record.text,
                    "Trajectory goal:",
                    ("Trajectory outcome:",),
                )
            )
        ),
        "",
    )[:1_000]
    outcome = next(
        (
            str(record.metadata.get("outcome")).strip()
            for record in reversed(records)
            if record.metadata.get("outcome")
        ),
        "unknown",
    )
    pieces = [
        f"Trajectory goal: {goal}" if goal else "",
        f"Trajectory outcome: {outcome}",
        f"States: {len(records)}",
        "Ordered experience:",
    ]
    prior_labels: set[str] = set()
    prior_actions: set[str] = set()
    for record in records:
        position = int(record.metadata.get(position_metadata_key) or 0)
        action = _section(
            record.text,
            "Action:",
            ("Thought:", "Observed page:"),
        )[:500]
        action_key = action.casefold()
        labels = _observed_labels(record.text)
        novel_labels = [
            label
            for label in labels
            if label.casefold() not in prior_labels
        ]
        prior_labels.update(label.casefold() for label in labels)
        step_parts: list[str] = []
        if action and action_key not in prior_actions:
            step_parts.append(f"Action: {action}")
            prior_actions.add(action_key)
        if novel_labels:
            step_parts.append(
                "New observed labels: " + " | ".join(novel_labels[:40])
            )
        if not step_parts:
            continue
        line = f"Step {position}: " + "; ".join(step_parts)
        if sum(len(piece) + 1 for piece in pieces) + len(line) > max_chars:
            break
        pieces.append(line)
    summary = "\n".join(piece for piece in pieces if piece).strip()
    return summary if len(summary) >= 120 else ""


def _trajectory_summary(
    record: Any,
    *,
    labels: Iterable[str],
    novel_labels: Iterable[str],
    position_metadata_key: str,
    max_chars: int,
) -> str:
    goal = _section(
        record.text,
        "Trajectory goal:",
        ("Trajectory outcome:",),
    )[:900]
    action = _section(
        record.text,
        "Action:",
        ("Thought:", "Observed page:"),
    )[:500]
    thought = _section(
        record.text,
        "Thought:",
        ("Observed page:",),
    )[:900]
    novel = list(novel_labels)
    all_labels = list(labels)
    pieces = [
        f"Trajectory goal: {goal}" if goal else "",
        f"Trajectory outcome: {record.metadata.get('outcome') or 'unknown'}",
        (
            f"State index: "
            f"{int(record.metadata.get(position_metadata_key) or 0)}"
        ),
        f"Action: {action}" if action else "",
        f"Thought: {thought}" if thought else "",
    ]
    if novel:
        pieces.append("New observed labels: " + " | ".join(novel))
    elif all_labels:
        pieces.append("Observed labels: " + " | ".join(all_labels[:20]))
    summary = "\n".join(piece for piece in pieces if piece)[:max_chars].strip()
    return summary if len(summary) >= 80 else ""


def _section(text: str, start: str, ends: tuple[str, ...]) -> str:
    offset = text.find(start)
    if offset < 0:
        return ""
    value = text[offset + len(start) :]
    valid = [
        position
        for marker in ends
        if (position := value.find(marker)) >= 0
    ]
    if valid:
        value = value[: min(valid)]
    return " ".join(value.split())


def _observed_labels(text: str) -> list[str]:
    observed = text.split("Observed page:", 1)
    if len(observed) != 2:
        return []
    labels: list[str] = []
    seen: set[str] = set()
    ignored = {"true", "false", "polite", "assertive"}
    for line in observed[1].splitlines():
        for raw in _QUOTED_LABEL_RE.findall(line):
            value = " ".join(raw.split())
            key = value.casefold()
            if not value or key in seen or key in ignored:
                continue
            seen.add(key)
            labels.append(value)
    if labels:
        return labels
    for raw in observed[1].splitlines():
        value = re.sub(r"^\s*\[\d+\]\s*", "", raw).strip()
        value = " ".join(value.split())
        key = value.casefold()
        if not value or key in seen:
            continue
        seen.add(key)
        labels.append(value[:240])
        if len(labels) >= 20:
            break
    return labels
