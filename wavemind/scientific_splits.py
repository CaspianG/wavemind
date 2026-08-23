from __future__ import annotations

import math
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
    validate_artifact_integrity,
    validate_source_manifest,
)


MEMORYAGENTBENCH_SPLIT_SCHEMA = "wavemind.memoryagentbench_split_manifest.v1"
MEMORYAGENTBENCH_REVISION = "7ea066982b140a19337e17e60d45d4076e042faf"
SPLITS = ("development", "validation", "final")
SOURCE_PATHS = (
    "wavemind/scientific_splits.py",
    "benchmarks/memoryagentbench_split_manifest.py",
    "tests/test_scientific_splits.py",
)


def _stable_partition(
    identifiers: Sequence[str],
    *,
    salt: str,
) -> dict[str, str]:
    ranked = sorted(
        identifiers,
        key=lambda item: (sha256_bytes(f"{salt}:{item}".encode()), item),
    )
    total = len(ranked)
    development = math.ceil(total * 0.60)
    validation = max(1, math.floor(total * 0.20))
    if development + validation >= total:
        development = max(1, total - 2)
        validation = 1
    result = {}
    for index, identifier in enumerate(ranked):
        if index < development:
            split = "development"
        elif index < development + validation:
            split = "validation"
        else:
            split = "final"
        result[identifier] = split
    return result


def build_memoryagentbench_split_manifest(
    *,
    project_root: str | Path,
    dataset_root: str | Path,
) -> dict[str, Any]:
    import pyarrow.parquet as parquet

    project = Path(project_root).resolve()
    dataset = Path(dataset_root).resolve()
    units: list[dict[str, Any]] = []
    for path in sorted((dataset / "data").glob("*.parquet")):
        family = path.name.split("-00000-", 1)[0]
        table = parquet.read_table(path, columns=["context", "questions", "metadata"])
        family_units: list[dict[str, Any]] = []
        for row_index, row in enumerate(table.to_pylist()):
            metadata = row.get("metadata") or {}
            context_sha = sha256_bytes(str(row.get("context") or "").encode("utf-8"))
            question_ids = list(metadata.get("question_ids") or [])
            question_fingerprint = sha256_bytes(canonical_json_bytes(question_ids))
            unit_id = f"{family}:{row_index:04d}:{context_sha[:16]}"
            family_units.append(
                {
                    "dataset": "memoryagentbench",
                    "family": family,
                    "unit_id": unit_id,
                    "row_index": row_index,
                    "question_count": len(row.get("questions") or []),
                    "context_sha256": context_sha,
                    "question_ids_sha256": question_fingerprint,
                    "source_file": f"data/{path.name}",
                    "source_file_sha256": file_sha256(path),
                }
            )
        units.extend(family_units)
    if not units:
        raise ValueError("MemoryAgentBench parquet files are missing")
    context_partition = _stable_partition(
        sorted({unit["context_sha256"] for unit in units}),
        salt=f"{MEMORYAGENTBENCH_REVISION}:unique-contexts",
    )
    for unit in units:
        unit["split"] = context_partition[unit["context_sha256"]]
    counts = Counter((unit["family"], unit["split"]) for unit in units)
    fingerprint_splits: dict[str, set[str]] = defaultdict(set)
    for unit in units:
        fingerprint_splits[unit["context_sha256"]].add(unit["split"])
    breaches = sorted(
        fingerprint
        for fingerprint, split_set in fingerprint_splits.items()
        if len(split_set) > 1
    )
    payload = {
        "schema": MEMORYAGENTBENCH_SPLIT_SCHEMA,
        "source_sha": repository_commit(project),
        "upstream": {
            "dataset": "ai-hyz/MemoryAgentBench",
            "revision": MEMORYAGENTBENCH_REVISION,
        },
        "policy": {
            "unit": "whole parquet context row",
            "partition": "deterministic 60/20/20 over unique context fingerprints",
            "salted_by_upstream_revision": True,
            "questions_from_one_context_never_cross_splits": True,
            "final_rows_forbidden_for_tuning": True,
        },
        "counts": {
            family: {split: counts[(family, split)] for split in SPLITS}
            for family in sorted({unit["family"] for unit in units})
        },
        "context_split_breaches": breaches,
        "units": units,
        "source_manifest": build_source_manifest(project, SOURCE_PATHS),
        "claim_boundary": (
            "Deterministic split isolation only. No MemoryAgentBench answer was "
            "generated or scored and final rows remain unavailable for tuning."
        ),
    }
    return attach_artifact_integrity(payload)


def validate_memoryagentbench_split_manifest(
    payload: Mapping[str, Any],
    *,
    project_root: str | Path,
    expected_source_sha: str,
) -> list[str]:
    errors = validate_artifact_integrity(payload)
    if payload.get("schema") != MEMORYAGENTBENCH_SPLIT_SCHEMA:
        errors.append("MemoryAgentBench split schema is invalid")
    if payload.get("source_sha") != expected_source_sha:
        errors.append("MemoryAgentBench split source SHA mismatch")
    upstream = payload.get("upstream")
    if not isinstance(upstream, Mapping) or upstream.get("revision") != MEMORYAGENTBENCH_REVISION:
        errors.append("MemoryAgentBench split revision mismatch")
    manifest = payload.get("source_manifest")
    if not isinstance(manifest, Mapping):
        errors.append("MemoryAgentBench split source manifest is missing")
    else:
        errors.extend(
            validate_source_manifest(
                Path(project_root), manifest, require_current_files=True
            )
        )
    units = payload.get("units")
    if not isinstance(units, list) or not units:
        errors.append("MemoryAgentBench split units are missing")
        return errors
    unit_ids: set[str] = set()
    fingerprint_splits: dict[str, set[str]] = defaultdict(set)
    for unit in units:
        if not isinstance(unit, Mapping):
            errors.append("MemoryAgentBench split unit is invalid")
            continue
        unit_id = str(unit.get("unit_id") or "")
        if not unit_id or unit_id in unit_ids:
            errors.append("MemoryAgentBench split unit ID is missing or duplicated")
        unit_ids.add(unit_id)
        split = str(unit.get("split") or "")
        if split not in SPLITS:
            errors.append("MemoryAgentBench split name is invalid")
        fingerprint = str(unit.get("context_sha256") or "")
        fingerprint_splits[fingerprint].add(split)
    calculated_breaches = sorted(
        fingerprint
        for fingerprint, split_set in fingerprint_splits.items()
        if len(split_set) > 1
    )
    if calculated_breaches != payload.get("context_split_breaches"):
        errors.append("MemoryAgentBench context breach summary mismatch")
    if calculated_breaches:
        errors.append("MemoryAgentBench context crosses splits")
    return errors
