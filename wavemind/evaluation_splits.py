from __future__ import annotations

import json
import subprocess
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Mapping, Sequence

from .evidence import (
    attach_artifact_integrity,
    build_source_manifest,
    canonical_json_bytes,
    file_sha256,
    repository_commit,
    sha256_bytes,
    utc_now,
    validate_artifact_integrity,
    validate_source_manifest,
)


SCHEMA = "wavemind.evaluation_split_manifest.v1"
STATE_BENCH_REVISION = "5644b1838d96bc4483da29642d058ecaa6f80f7f"
MEMOPS_REVISION = "312af65e2c7b6d1b70f062ffa8b4cde32aaf6f35"
SPLITS = ("development", "validation", "final")
STATE_DOMAINS = ("travel", "customer_support", "shopping_assistant")
SOURCE_PATHS = (
    "wavemind/evaluation_splits.py",
    "benchmarks/evaluation_split_manifest.py",
    "tests/test_evaluation_splits.py",
)


def _git_revision(root: Path) -> str:
    return subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=root, text=True, encoding="utf-8"
    ).strip()


def _stable_partition(
    identifiers: Sequence[str],
    *,
    salt: str,
    counts: tuple[int, int, int],
) -> dict[str, str]:
    if sum(counts) != len(identifiers):
        raise ValueError("split counts do not match identifier count")
    ranked = sorted(
        identifiers,
        key=lambda item: (sha256_bytes(f"{salt}:{item}".encode()), item),
    )
    boundaries = (counts[0], counts[0] + counts[1])
    result = {}
    for index, identifier in enumerate(ranked):
        if index < boundaries[0]:
            split = "development"
        elif index < boundaries[1]:
            split = "validation"
        else:
            split = "final"
        result[identifier] = split
    return result


def _json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _state_units(root: Path) -> list[dict[str, Any]]:
    units: list[dict[str, Any]] = []
    for domain in STATE_DOMAINS:
        domain_root = root / "state_bench" / "domains" / domain
        official = _json(domain_root / "splits" / "train_test.json")["splits"]
        train_ids = list(official["train"])
        test_ids = list(official["test"])
        if len(train_ids) != 100 or len(test_ids) != 50:
            raise ValueError(f"STATE-Bench official split size changed: {domain}")
        train_partition = _stable_partition(
            train_ids,
            salt=f"{STATE_BENCH_REVISION}:{domain}:train",
            counts=(80, 20, 0),
        )
        for source_split, task_ids in (("train", train_ids), ("test", test_ids)):
            for task_id in task_ids:
                task_path = domain_root / "tasks" / f"{task_id}.json"
                environment_path = domain_root / "task_envs" / f"{task_id}.json"
                if not task_path.is_file() or not environment_path.is_file():
                    raise ValueError(
                        f"STATE-Bench task files missing: {domain}/{task_id}"
                    )
                trajectory_path = (
                    root
                    / "datasets"
                    / "train_task_trajectories"
                    / domain
                    / f"{task_id}.json"
                )
                if source_split == "train" and not trajectory_path.is_file():
                    raise ValueError(
                        f"STATE-Bench train trajectory missing: {domain}/{task_id}"
                    )
                split = train_partition[task_id] if source_split == "train" else "final"
                task_digest = file_sha256(task_path)
                environment_digest = file_sha256(environment_path)
                trajectory_digest = (
                    file_sha256(trajectory_path) if trajectory_path.is_file() else None
                )
                fingerprint_payload = {
                    "dataset": "state-bench",
                    "domain": domain,
                    "task_id": task_id,
                    "task_sha256": task_digest,
                    "environment_sha256": environment_digest,
                    "trajectory_sha256": trajectory_digest,
                }
                units.append(
                    {
                        **fingerprint_payload,
                        "unit_id": f"state-bench:{domain}:{task_id}",
                        "source_split": source_split,
                        "split": split,
                        "conversation_fingerprint": trajectory_digest,
                        "trajectory_fingerprint": trajectory_digest,
                        "derived_fingerprint": sha256_bytes(
                            canonical_json_bytes(fingerprint_payload)
                        ),
                    }
                )
    return units


def _memops_units(root: Path) -> list[dict[str, Any]]:
    evidence_root = root / "generated_result" / "2-evidence_conversation"
    paths = sorted(evidence_root.glob("*.json"))
    subjects = sorted({path.stem.split("_", 1)[0] for path in paths})
    if len(paths) != 403 or len(subjects) != 100:
        raise ValueError("MemOps pinned corpus size changed")
    subject_partition = _stable_partition(
        subjects,
        salt=f"{MEMOPS_REVISION}:subject",
        counts=(60, 20, 20),
    )
    units = []
    for path in paths:
        payload = _json(path)
        subject_id = path.stem.split("_", 1)[0]
        operation_type = str(payload.get("operation_type", ""))
        conversations = payload.get("conversations")
        operations = payload.get("operations")
        if not operation_type:
            raise ValueError(f"MemOps operation_type missing: {path.name}")
        if not isinstance(conversations, list) or not conversations:
            raise ValueError(f"MemOps conversations missing: {path.name}")
        if not isinstance(operations, list) or not operations:
            raise ValueError(f"MemOps operations missing: {path.name}")
        conversation_fingerprint = sha256_bytes(canonical_json_bytes(conversations))
        trajectory_fingerprint = sha256_bytes(
            canonical_json_bytes(
                {
                    "subject_id": subject_id,
                    "operations": operations,
                    "conversations": conversations,
                }
            )
        )
        fingerprint_payload = {
            "dataset": "memops",
            "unit_id": path.stem,
            "subject_id": subject_id,
            "operation_type": operation_type,
            "source_sha256": file_sha256(path),
            "conversation_fingerprint": conversation_fingerprint,
            "trajectory_fingerprint": trajectory_fingerprint,
        }
        units.append(
            {
                **fingerprint_payload,
                "split": subject_partition[subject_id],
                "derived_fingerprint": sha256_bytes(
                    canonical_json_bytes(fingerprint_payload)
                ),
            }
        )
    return units


def _overlaps(units: Sequence[Mapping[str, Any]]) -> dict[str, list[str]]:
    fields = (
        "unit_id",
        "conversation_fingerprint",
        "trajectory_fingerprint",
        "derived_fingerprint",
    )
    result: dict[str, list[str]] = {}
    for field in fields:
        seen: dict[str, set[str]] = defaultdict(set)
        for unit in units:
            value = unit.get(field)
            if value:
                seen[str(value)].add(str(unit["split"]))
        result[field] = sorted(
            value for value, splits in seen.items() if len(splits) > 1
        )
    return result


def build_evaluation_split_manifest(
    *,
    project_root: str | Path,
    state_bench_root: str | Path,
    memops_root: str | Path,
    expected_state_revision: str = STATE_BENCH_REVISION,
    expected_memops_revision: str = MEMOPS_REVISION,
) -> dict[str, Any]:
    project = Path(project_root).resolve()
    state_root = Path(state_bench_root).resolve()
    memops = Path(memops_root).resolve()
    state_revision = _git_revision(state_root)
    memops_revision = _git_revision(memops)
    if state_revision != expected_state_revision:
        raise ValueError("STATE-Bench checkout does not match pinned revision")
    if memops_revision != expected_memops_revision:
        raise ValueError("MemOps checkout does not match pinned revision")
    state_units = _state_units(state_root)
    memops_units = _memops_units(memops)
    all_units = [*state_units, *memops_units]
    overlaps = _overlaps(all_units)
    counts = Counter((unit["dataset"], unit["split"]) for unit in all_units)
    subject_splits: dict[str, set[str]] = defaultdict(set)
    for unit in memops_units:
        subject_splits[unit["subject_id"]].add(unit["split"])
    payload = {
        "schema": SCHEMA,
        "generated_at": utc_now(),
        "source_sha": repository_commit(project),
        "upstream": {
            "state-bench": {
                "revision": state_revision,
                "official_train_test_preserved": True,
                "official_test_usage": "final_only",
            },
            "memops": {
                "revision": memops_revision,
                "subject_grouping": "all operations for one subject stay in one split",
            },
        },
        "split_policy": {
            "state-bench": "official train deterministically partitions 80/20 development/validation per domain; official test remains final",
            "memops": "100 subject trajectories deterministically partition 60/20/20; operation cases inherit the subject split",
            "salted_by_upstream_revision": True,
            "final_rows_forbidden_for_tuning": True,
        },
        "counts": {
            dataset: {split: counts[(dataset, split)] for split in SPLITS}
            for dataset in ("state-bench", "memops")
        },
        "subject_split_breaches": sorted(
            subject for subject, splits in subject_splits.items() if len(splits) > 1
        ),
        "overlaps": overlaps,
        "units": all_units,
        "source_manifest": build_source_manifest(project, SOURCE_PATHS),
        "claim_boundary": (
            "Split isolation for pinned STATE-Bench and MemOps units only. No benchmark "
            "was executed and final rows remain unopened for product tuning."
        ),
    }
    return attach_artifact_integrity(payload)


def validate_evaluation_split_manifest(
    payload: Mapping[str, Any],
    *,
    project_root: str | Path,
    expected_source_sha: str,
) -> list[str]:
    errors = validate_artifact_integrity(payload)
    if payload.get("schema") != SCHEMA:
        errors.append("evaluation split manifest schema is invalid")
    if payload.get("source_sha") != expected_source_sha:
        errors.append("evaluation split manifest source SHA mismatch")
    source_manifest = payload.get("source_manifest")
    if not isinstance(source_manifest, Mapping):
        errors.append("evaluation split source manifest is missing")
    else:
        errors.extend(
            validate_source_manifest(
                Path(project_root), source_manifest, require_current_files=True
            )
        )
    upstream = payload.get("upstream")
    if not isinstance(upstream, Mapping):
        errors.append("evaluation split upstream revisions are missing")
    else:
        if upstream.get("state-bench", {}).get("revision") != STATE_BENCH_REVISION:
            errors.append("STATE-Bench split revision mismatch")
        if upstream.get("memops", {}).get("revision") != MEMOPS_REVISION:
            errors.append("MemOps split revision mismatch")
    units = payload.get("units")
    if not isinstance(units, list) or not units:
        errors.append("evaluation split units are missing")
        return errors
    for unit in units:
        if not isinstance(unit, Mapping):
            errors.append("evaluation split unit is invalid")
            continue
        if unit.get("split") not in SPLITS:
            errors.append("evaluation split unit has invalid split")
        if unit.get("dataset") == "state-bench":
            if unit.get("source_split") == "test" and unit.get("split") != "final":
                errors.append("STATE-Bench official test row is not final-only")
            if unit.get("source_split") == "train" and unit.get("split") == "final":
                errors.append("STATE-Bench train row leaked into final")
    calculated_overlaps = _overlaps(units)
    if calculated_overlaps != payload.get("overlaps"):
        errors.append("evaluation split overlap summary mismatch")
    for field, values in calculated_overlaps.items():
        if values:
            errors.append(f"evaluation split overlap detected: {field}")
    subject_splits: dict[str, set[str]] = defaultdict(set)
    for unit in units:
        if unit.get("dataset") == "memops":
            subject_splits[str(unit.get("subject_id"))].add(str(unit.get("split")))
    if any(len(splits) > 1 for splits in subject_splits.values()):
        errors.append("MemOps subject trajectory crosses splits")
    return errors
