from __future__ import annotations

import json
import statistics
import time
from collections import Counter
from pathlib import Path
from typing import Any, Mapping, Protocol, Sequence

from .core import WaveMind
from .evaluation_development_protocol import (
    validate_evaluation_development_protocol,
)
from .evidence import (
    attach_artifact_integrity,
    build_source_manifest,
    execution_environment,
    repository_commit,
    validate_artifact_integrity,
)


SCHEMA = "wavemind.evaluation_lifecycle_diagnostic.v2"
MEMOPS_REVISION = "312af65e2c7b6d1b70f062ffa8b4cde32aaf6f35"
SOURCE_PATHS = (
    "wavemind/core.py",
    "wavemind/storage.py",
    "wavemind/evaluation_lifecycle_diagnostic.py",
    "benchmarks/evaluation_lifecycle_diagnostic.py",
    "benchmarks/evaluation_candidate1_latency_protocol_addendum.json",
    "tests/test_evaluation_lifecycle_diagnostic.py",
)


class LifecycleBackend(Protocol):
    name: str

    def apply(self, operation: Mapping[str, Any]) -> None: ...

    def observe(self, target_id: str, target_name: str) -> dict[str, Any]: ...

    def close(self) -> None: ...


def _json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def measure_warm_observation(
    backend: LifecycleBackend,
    target_id: str,
    target_name: str,
    *,
    warmup_count: int,
    measured_count: int,
) -> tuple[dict[str, Any], float, list[float]]:
    if warmup_count < 0 or measured_count <= 0:
        raise ValueError("warmup_count must be non-negative and measured_count positive")
    for _ in range(warmup_count):
        backend.observe(target_id, target_name)
    samples: list[float] = []
    observation: dict[str, Any] | None = None
    for _ in range(measured_count):
        started = time.perf_counter()
        observation = backend.observe(target_id, target_name)
        samples.append((time.perf_counter() - started) * 1000.0)
    if observation is None:
        raise RuntimeError("warm observation produced no measured result")
    return observation, float(statistics.median(samples)), samples


def _target(operation: Mapping[str, Any]) -> tuple[str, str]:
    value = operation.get("target")
    if not isinstance(value, Mapping):
        raise ValueError("MemOps operation target is missing")
    target_id = str(value.get("target_id") or "").strip()
    target_name = str(value.get("target_name") or target_id).strip()
    if not target_id:
        raise ValueError("MemOps operation target id is missing")
    return target_id, target_name


def _confirmed(operation: Mapping[str, Any]) -> bool:
    return str(operation.get("validity") or "confirmed").lower() == "confirmed"


def _value(operation: Mapping[str, Any]) -> str | None:
    raw = operation.get("new_value")
    if raw is None:
        return None
    if isinstance(raw, str):
        return raw
    return json.dumps(raw, sort_keys=True, ensure_ascii=False)


def expected_state(
    operations: Sequence[Mapping[str, Any]],
) -> dict[str, dict[str, Any]]:
    state: dict[str, dict[str, Any]] = {}
    for operation in operations:
        target_id, target_name = _target(operation)
        if not _confirmed(operation):
            continue
        kind = str(operation.get("type") or "").lower()
        if kind == "forget":
            state.pop(target_id, None)
            continue
        if kind not in {"remember", "update", "reflect"}:
            raise ValueError(f"unsupported MemOps operation type: {kind}")
        value = _value(operation)
        if value is None:
            raise ValueError(f"MemOps {kind} operation has no new value")
        state[target_id] = {
            "value": value,
            "target_name": target_name,
            "operation_id": str(operation.get("operation_id") or ""),
            "provenance": list(operation.get("evidence_spans") or []),
        }
    return state


def target_catalog(
    operations: Sequence[Mapping[str, Any]],
) -> dict[str, str]:
    catalog: dict[str, str] = {}
    for operation in operations:
        target_id, target_name = _target(operation)
        catalog[target_id] = target_name
    return catalog


class NoMemoryBackend:
    name = "no_memory"

    def apply(self, operation: Mapping[str, Any]) -> None:
        _target(operation)

    def observe(self, target_id: str, target_name: str) -> dict[str, Any]:
        return {"selected": None, "active": [], "wrong_namespace": []}

    def close(self) -> None:
        return None


class StaticLastWriteWinsBackend:
    name = "static_lww"

    def __init__(self) -> None:
        self._state: dict[str, dict[str, Any]] = {}

    def apply(self, operation: Mapping[str, Any]) -> None:
        target_id, target_name = _target(operation)
        if not _confirmed(operation):
            return
        kind = str(operation.get("type") or "").lower()
        if kind == "forget":
            self._state.pop(target_id, None)
            return
        value = _value(operation)
        if kind not in {"remember", "update", "reflect"} or value is None:
            raise ValueError(f"unsupported MemOps operation type: {kind}")
        self._state[target_id] = {
            "value": value,
            "target_name": target_name,
            "verified": True,
            "provenance": list(operation.get("evidence_spans") or []),
        }

    def observe(self, target_id: str, target_name: str) -> dict[str, Any]:
        record = self._state.get(target_id)
        active = [record] if record is not None else []
        return {"selected": record, "active": active, "wrong_namespace": []}

    def close(self) -> None:
        return None


class WaveMindCoreLifecycleBackend:
    name = "wavemind_core"

    def __init__(self, db_path: str | Path, *, namespace: str) -> None:
        self.namespace = namespace
        self._ids_by_target: dict[str, list[int]] = {}
        self.mind = WaveMind(
            db_path=db_path,
            width=16,
            height=16,
            layers=2,
            evolve_on_feed=1,
            confidence_gate=True,
            persist_access_on_query=False,
            query_feedback_strength=0.0,
        )

    def apply(self, operation: Mapping[str, Any]) -> None:
        target_id, target_name = _target(operation)
        kind = str(operation.get("type") or "").lower()
        validity = str(operation.get("validity") or "confirmed").lower()
        if kind == "forget" and _confirmed(operation):
            for memory_id in self._ids_by_target.pop(target_id, []):
                self.mind.forget(id=memory_id, namespace=self.namespace)
            return
        if kind not in {"remember", "update", "reflect"}:
            raise ValueError(f"unsupported MemOps operation type: {kind}")
        value = _value(operation)
        if value is None:
            raise ValueError(f"MemOps {kind} operation has no new value")
        verified = validity == "confirmed"
        memory_id = self.mind.remember(
            f"{target_name}: {value}",
            namespace=self.namespace,
            metadata={
                "target_id": target_id,
                "target_name": target_name,
                "value": value,
                "operation_type": kind,
                "operation_id": str(operation.get("operation_id") or ""),
                "verification_status": "verified" if verified else "unverified",
                "verified": verified,
                "provenance": list(operation.get("evidence_spans") or []),
            },
        )
        self._ids_by_target.setdefault(target_id, []).append(memory_id)

    def observe(self, target_id: str, target_name: str) -> dict[str, Any]:
        results = self.mind.query(
            target_name,
            namespace=self.namespace,
            top_k=20,
            metadata_filters={"target_id": target_id},
        )
        wrong_namespace = self.mind.query(
            target_name,
            namespace=f"{self.namespace}:wrong",
            top_k=20,
            metadata_filters={"target_id": target_id},
        )
        active = [
            {
                "value": str(result.metadata.get("value")),
                "target_name": str(result.metadata.get("target_name")),
                "verified": bool(result.metadata.get("verified")),
                "provenance": list(result.metadata.get("provenance") or []),
                "memory_id": result.id,
                "score": result.score,
            }
            for result in results
        ]
        return {
            "selected": active[0] if active else None,
            "active": active,
            "wrong_namespace": [result.id for result in wrong_namespace],
        }

    def close(self) -> None:
        self.mind.close()


class WaveMindVersionedLifecycleBackend(WaveMindCoreLifecycleBackend):
    name = "wavemind_versioned"

    def __init__(self, db_path: str | Path, *, namespace: str) -> None:
        super().__init__(db_path, namespace=namespace)
        self._active_id_by_target: dict[str, int] = {}

    def apply(self, operation: Mapping[str, Any]) -> None:
        target_id, target_name = _target(operation)
        kind = str(operation.get("type") or "").lower()
        confirmed = _confirmed(operation)
        if kind == "forget" and confirmed:
            super().apply(operation)
            self._active_id_by_target.pop(target_id, None)
            return
        if kind == "update" and confirmed:
            value = _value(operation)
            if value is None:
                raise ValueError("MemOps update operation has no new value")
            predecessor_id = self._active_id_by_target.get(target_id)
            if predecessor_id is None:
                super().apply(operation)
                self._active_id_by_target[target_id] = self._ids_by_target[target_id][
                    -1
                ]
                return
            replacement_id = self.mind.supersede(
                predecessor_id,
                f"{target_name}: {value}",
                namespace=self.namespace,
                metadata={
                    "target_id": target_id,
                    "target_name": target_name,
                    "value": value,
                    "operation_type": kind,
                    "operation_id": str(operation.get("operation_id") or ""),
                    "verification_status": "verified",
                    "verified": True,
                    "provenance": list(operation.get("evidence_spans") or []),
                },
                transition_id=(
                    f"{self.namespace}:{str(operation.get('operation_id') or '')}"
                ),
            )
            self._ids_by_target.setdefault(target_id, []).append(replacement_id)
            self._active_id_by_target[target_id] = replacement_id
            return
        super().apply(operation)
        if confirmed and kind in {"remember", "reflect"}:
            self._active_id_by_target[target_id] = self._ids_by_target[target_id][-1]


def score_observation(
    *,
    expected: Mapping[str, Any] | None,
    observation: Mapping[str, Any],
) -> dict[str, Any]:
    selected = observation.get("selected")
    active = observation.get("active")
    wrong_namespace = observation.get("wrong_namespace")
    active = active if isinstance(active, list) else []
    wrong_namespace = wrong_namespace if isinstance(wrong_namespace, list) else []
    expected_value = str(expected["value"]) if expected is not None else None
    selected_value = (
        str(selected.get("value")) if isinstance(selected, Mapping) else None
    )
    active_values = [
        str(item.get("value")) for item in active if isinstance(item, Mapping)
    ]
    context_characters = sum(len(value) for value in active_values)
    target_correct = (
        selected_value == expected_value
        if expected is not None
        else selected_value is None and not active_values
    )
    stale_values = (
        [value for value in active_values if value != expected_value]
        if expected is not None
        else list(active_values)
    )
    unverified = [
        item
        for item in active
        if isinstance(item, Mapping) and item.get("verified") is False
    ]
    provenance = (
        list(selected.get("provenance") or [])
        if isinstance(selected, Mapping)
        else []
    )
    operation_state_transition = bool(
        target_correct
        and not stale_values
        and not (expected is not None and selected_value is None)
        and not (expected is None and bool(active_values))
        and not unverified
        and not wrong_namespace
        and (expected is None or bool(provenance))
    )
    return {
        "operation_state_transition": operation_state_transition,
        "target_correct": target_correct,
        "selected_value": selected_value,
        "expected_value": expected_value,
        "stale_leakage": bool(stale_values),
        "stale_values": stale_values,
        "over_forgetting": expected is not None and selected_value is None,
        "deleted_resurfacing": expected is None and bool(active_values),
        "unverified_injection": bool(unverified),
        "namespace_leakage": bool(wrong_namespace),
        "provenance_supported": expected is None or bool(provenance),
        "context_characters": context_characters,
    }


def classify_error(
    *, operation_type: str, score: Mapping[str, Any]
) -> str | None:
    if score.get("namespace_leakage"):
        return "retrieval_miss"
    if score.get("unverified_injection") or score.get("stale_leakage"):
        return "stale_or_contradictory_selection"
    if score.get("deleted_resurfacing") or score.get("over_forgetting"):
        return "missing_state_transition"
    if not score.get("target_correct"):
        if operation_type in {"Update", "Forget", "TrajectoryOps"}:
            return "missing_state_transition"
        if operation_type == "Reflect":
            return "bad_consolidation"
        return "retrieval_miss"
    if not score.get("provenance_supported"):
        return "bad_consolidation"
    return None


def _backend_summary(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    total = len(rows)
    if total == 0:
        raise ValueError("lifecycle diagnostic backend has no target rows")
    fields = (
        "operation_state_transition",
        "target_correct",
        "stale_leakage",
        "over_forgetting",
        "deleted_resurfacing",
        "unverified_injection",
        "namespace_leakage",
        "provenance_supported",
    )
    latencies = sorted(float(row["latency_ms"]) for row in rows)

    def percentile(fraction: float) -> float:
        if len(latencies) == 1:
            return latencies[0]
        position = fraction * (len(latencies) - 1)
        lower = int(position)
        upper = min(len(latencies) - 1, lower + 1)
        weight = position - lower
        return latencies[lower] * (1.0 - weight) + latencies[upper] * weight

    return {
        "target_count": total,
        **{
            field: sum(bool(row[field]) for row in rows) / total for field in fields
        },
        "context_characters_mean": sum(
            int(row["context_characters"]) for row in rows
        )
        / total,
        "latency_ms": {
            "mean": sum(latencies) / total,
            "p50": percentile(0.50),
            "p95": percentile(0.95),
            "p99": percentile(0.99),
            "max": latencies[-1],
        },
    }


def compact_lifecycle_diagnostic(
    payload: Mapping[str, Any],
    *,
    raw_filename: str,
    raw_sha256: str,
) -> dict[str, Any]:
    rows = payload.get("per_target")
    if not isinstance(rows, list) or not rows:
        raise ValueError("lifecycle diagnostic raw target rows are missing")
    compact = {
        key: value
        for key, value in payload.items()
        if key not in {"per_target", "integrity"}
    }
    compact["raw_evidence"] = {
        "filename": Path(raw_filename).name,
        "sha256": raw_sha256,
        "row_count": len(rows),
        "retention": "CI artifact; not checked into the repository",
    }
    return attach_artifact_integrity(compact)


def run_memops_lifecycle_diagnostic(
    *,
    project_root: str | Path,
    memops_root: str | Path,
    protocol_path: str | Path,
    dataset_manifest_path: str | Path,
    split_manifest_path: str | Path,
    judge_policy_path: str | Path,
    latency_addendum_path: str | Path,
    temp_root: str | Path,
) -> dict[str, Any]:
    root = Path(project_root).resolve()
    memops = Path(memops_root).resolve()
    temporary = Path(temp_root).resolve()
    temporary.mkdir(parents=True, exist_ok=True)
    protocol = _json(Path(protocol_path))
    protocol_errors = validate_evaluation_development_protocol(
        protocol,
        project_root=root,
        dataset_manifest_path=dataset_manifest_path,
        split_manifest_path=split_manifest_path,
        judge_policy_path=judge_policy_path,
    )
    if protocol_errors:
        raise ValueError(f"development protocol is invalid: {protocol_errors}")
    latency_addendum = _json(Path(latency_addendum_path))
    latency_integrity_errors = validate_artifact_integrity(latency_addendum)
    if latency_integrity_errors:
        raise ValueError(
            f"latency protocol addendum is invalid: {latency_integrity_errors}"
        )
    correction = latency_addendum.get("frozen_correction")
    if not isinstance(correction, Mapping):
        raise ValueError("latency protocol addendum has no frozen correction")
    warmup_count = int(correction.get("warmup_queries_per_target", -1))
    measured_count = int(correction.get("measured_queries_per_target", 0))
    if warmup_count != 2 or measured_count != 5:
        raise ValueError("latency protocol addendum does not match the frozen 2/5 plan")
    if correction.get("heldout_access") != "forbidden":
        raise ValueError("latency protocol addendum must forbid heldout access")
    revision = (
        __import__("subprocess")
        .check_output(
            ["git", "rev-parse", "HEAD"], cwd=memops, text=True, encoding="utf-8"
        )
        .strip()
    )
    if revision != MEMOPS_REVISION:
        raise ValueError("MemOps checkout does not match the pinned revision")
    units = [
        unit
        for unit in protocol["bounded_sample"]["units"]
        if unit["dataset"] == "memops"
    ]
    raw_rows: list[dict[str, Any]] = []
    taxonomy_by_backend: dict[str, Counter[str]] = {
        "wavemind_core": Counter(),
        "wavemind_versioned": Counter(),
    }
    for case_index, unit in enumerate(units):
        case_id = str(unit["unit_id"])
        case_path = memops / "generated_result" / "2-evidence_conversation" / f"{case_id}.json"
        payload = _json(case_path)
        operations = payload.get("operations")
        if not isinstance(operations, list) or not operations:
            raise ValueError(f"MemOps operations are missing: {case_id}")
        expected = expected_state(operations)
        catalog = target_catalog(operations)
        namespace = f"evaluation:memops:{case_index}"
        backends: list[LifecycleBackend] = [
            NoMemoryBackend(),
            StaticLastWriteWinsBackend(),
            WaveMindCoreLifecycleBackend(
                temporary / f"{case_index:03d}-{case_id}.sqlite3",
                namespace=namespace,
            ),
            WaveMindVersionedLifecycleBackend(
                temporary / f"{case_index:03d}-{case_id}-versioned.sqlite3",
                namespace=namespace,
            ),
        ]
        try:
            for backend in backends:
                started = time.perf_counter()
                for operation in operations:
                    backend.apply(operation)
                apply_ms = (time.perf_counter() - started) * 1000.0
                target_ids = sorted(set(catalog).union(expected))
                for target_id in target_ids:
                    observation, latency_ms, latency_samples_ms = (
                        measure_warm_observation(
                            backend,
                            target_id,
                            catalog[target_id],
                            warmup_count=warmup_count,
                            measured_count=measured_count,
                        )
                    )
                    score = score_observation(
                        expected=expected.get(target_id), observation=observation
                    )
                    error = classify_error(
                        operation_type=str(payload.get("operation_type") or ""),
                        score=score,
                    )
                    row = {
                        "case_id": case_id,
                        "cluster_id": str(unit["cluster_id"]),
                        "operation_type": str(payload.get("operation_type") or ""),
                        "target_id": target_id,
                        "backend": backend.name,
                        "apply_ms": apply_ms,
                        "latency_ms": latency_ms,
                        "latency_samples_ms": latency_samples_ms,
                        **score,
                        "error_taxonomy": error,
                    }
                    raw_rows.append(row)
                    if backend.name in taxonomy_by_backend and error is not None:
                        taxonomy_by_backend[backend.name][error] += 1
        finally:
            for backend in backends:
                backend.close()

    backend_names = (
        "no_memory",
        "static_lww",
        "wavemind_core",
        "wavemind_versioned",
    )
    by_backend = {
        backend: _backend_summary(
            [row for row in raw_rows if row["backend"] == backend]
        )
        for backend in backend_names
    }
    operation_types = sorted({str(row["operation_type"]) for row in raw_rows})
    by_operation_type = {
        operation_type: {
            backend: _backend_summary(
                [
                    row
                    for row in raw_rows
                    if row["operation_type"] == operation_type
                    and row["backend"] == backend
                ]
            )
            for backend in backend_names
        }
        for operation_type in operation_types
    }
    payload = {
        "schema": SCHEMA,
        "status": "diagnostic_complete",
        "source_sha": repository_commit(root),
        "protocol": {
            "revision": protocol["revision"],
            "payload_sha256": protocol["integrity"]["payload_sha256"],
            "heldout_access": protocol["heldout_access"],
            "latency_addendum": {
                "id": latency_addendum["id"],
                "payload_sha256": latency_addendum["integrity"]["payload_sha256"],
                "warmup_queries_per_target": warmup_count,
                "measured_queries_per_target": measured_count,
                "per_target_latency_value": correction["per_target_latency_value"],
            },
        },
        "upstream": {"memops_revision": revision},
        "scope": {
            "split": "development",
            "case_count": len(units),
            "target_row_count": len(
                [row for row in raw_rows if row["backend"] == "wavemind_core"]
            ),
            "quality_claim_eligible": False,
            "reason": (
                "Operation-level typed-event capability diagnostic; it does not "
                "measure conversation extraction or generated-answer quality."
            ),
        },
        "summary": by_backend,
        "by_operation_type": by_operation_type,
        "wavemind_error_taxonomy": dict(
            sorted(taxonomy_by_backend["wavemind_core"].items())
        ),
        "candidate_error_taxonomy": dict(
            sorted(taxonomy_by_backend["wavemind_versioned"].items())
        ),
        "per_target": raw_rows,
        "source_manifest": build_source_manifest(root, SOURCE_PATHS),
        "environment": execution_environment(
            profile="goal8-memops-bounded-development"
        ),
        "claim_boundary": (
            "Development-only MemOps typed lifecycle diagnostic. No validation/final "
            "rows, product tuning, general quality claim, or held-out verdict."
        ),
    }
    return attach_artifact_integrity(payload)
