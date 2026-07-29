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

    def __init__(self, memory: Any):
        self.memory = memory

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
                            dict.fromkeys((*record.tags, output_tag))
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
