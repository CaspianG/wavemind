from __future__ import annotations

import re
from typing import Any, Mapping

from .evidence import validate_artifact_integrity


DATASET_MANIFEST_SCHEMA = "wavemind.evaluation_dataset_manifest.v1"
VALID_LAYERS = {"lifecycle", "retrieval", "answer", "workflow", "efficiency_safety"}
REQUIRED_SOURCE_IDS = {
    "memory-agent-bench",
    "longmemeval",
    "longmemeval-v2",
    "state-bench",
    "memops",
}
REQUIRED_TASK_IDS = {
    "memory-agent-bench.accurate-retrieval",
    "memory-agent-bench.conflict-resolution",
    "memory-agent-bench.long-range-understanding",
    "memory-agent-bench.test-time-learning",
    "memory-agent-bench.recommendation",
    "memory-agent-bench.longmemeval-infbench",
    "longmemeval.gold-evidence",
    "longmemeval.end-to-end-qa",
    "longmemeval-v2.memory-backend",
    "state-bench.agent-learning",
    "memops.lifecycle",
}
BACKEND_FORBIDDEN_FIELDS = {
    "case_id",
    "dataset_row_id",
    "evaluator_metadata",
    "expected_outcome",
    "gold_answer",
    "gold_evidence",
    "question_type",
    "split",
}
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
GIT_SHA_RE = re.compile(r"^[0-9a-f]{40}$")


def backend_query_view(
    case: Mapping[str, Any], contract: Mapping[str, Any]
) -> dict[str, Any]:
    """Return the only fields a memory backend is allowed to observe."""

    allowed = contract.get("allowed_fields")
    if not isinstance(allowed, list) or not all(
        isinstance(item, str) for item in allowed
    ):
        raise ValueError("backend query contract requires string allowed_fields")
    forbidden = set(contract.get("forbidden_fields", []))
    if not BACKEND_FORBIDDEN_FIELDS.issubset(forbidden):
        raise ValueError(
            "backend query contract does not forbid all evaluator metadata"
        )
    if forbidden.intersection(allowed):
        raise ValueError("backend query contract exposes a forbidden field")
    return {field: case[field] for field in allowed if field in case}


def validate_dataset_manifest(payload: Mapping[str, Any]) -> list[str]:
    errors = validate_artifact_integrity(payload)
    if payload.get("schema") != DATASET_MANIFEST_SCHEMA:
        errors.append("dataset manifest schema is invalid")
    revision = payload.get("revision")
    if not isinstance(revision, str) or not revision:
        errors.append("dataset manifest revision is missing")

    sources = payload.get("sources")
    source_ids: set[str] = set()
    if not isinstance(sources, list):
        errors.append("dataset sources must be a list")
        sources = []
    for source in sources:
        if not isinstance(source, Mapping):
            errors.append("dataset source entry is invalid")
            continue
        source_id = source.get("id")
        if not isinstance(source_id, str) or not source_id:
            errors.append("dataset source id is missing")
            continue
        if source_id in source_ids:
            errors.append(f"duplicate dataset source: {source_id}")
        source_ids.add(source_id)
        if not GIT_SHA_RE.fullmatch(str(source.get("revision", ""))):
            errors.append(f"dataset source revision is not an exact SHA: {source_id}")
        if not source.get("license"):
            errors.append(f"dataset source license is missing: {source_id}")
        digest_fields = [
            key
            for key in ("dataset_card_sha256", "readme_sha256", "license_sha256")
            if key in source
        ]
        if not digest_fields:
            errors.append(f"dataset source has no pinned content checksum: {source_id}")
        for key in digest_fields:
            if not SHA256_RE.fullmatch(str(source.get(key, ""))):
                errors.append(f"dataset source checksum is invalid: {source_id}.{key}")
        content = source.get("content", [])
        if content is not None and not isinstance(content, list):
            errors.append(f"dataset source content manifest is invalid: {source_id}")
        for item in content if isinstance(content, list) else []:
            if not isinstance(item, Mapping) or not item.get("path"):
                errors.append(f"dataset source content entry is invalid: {source_id}")
            elif not SHA256_RE.fullmatch(str(item.get("sha256", ""))):
                errors.append(
                    f"dataset source content checksum is invalid: {source_id}"
                )
    missing_sources = REQUIRED_SOURCE_IDS - source_ids
    if missing_sources:
        errors.append(
            f"required dataset sources are missing: {sorted(missing_sources)}"
        )

    mappings = payload.get("task_mappings")
    task_by_id: dict[str, Mapping[str, Any]] = {}
    if not isinstance(mappings, list):
        errors.append("task mappings must be a list")
        mappings = []
    for mapping in mappings:
        if not isinstance(mapping, Mapping):
            errors.append("task mapping entry is invalid")
            continue
        task_id = mapping.get("id")
        if not isinstance(task_id, str) or not task_id:
            errors.append("task mapping id is missing")
            continue
        if task_id in task_by_id:
            errors.append(f"duplicate task mapping: {task_id}")
        task_by_id[task_id] = mapping
        if mapping.get("layer") not in VALID_LAYERS:
            errors.append(f"task mapping layer is invalid: {task_id}")
        if not mapping.get("native_scorer"):
            errors.append(f"task mapping native scorer is missing: {task_id}")
    missing_tasks = REQUIRED_TASK_IDS - set(task_by_id)
    if missing_tasks:
        errors.append(f"required task mappings are missing: {sorted(missing_tasks)}")

    long_range = task_by_id.get("memory-agent-bench.long-range-understanding", {})
    if long_range.get("layer") == "retrieval" or not long_range.get("generated_answer"):
        errors.append("MemoryAgentBench long-range task was coerced into retrieval")
    longmem_retrieval = task_by_id.get("longmemeval.gold-evidence", {})
    if longmem_retrieval.get("abstention_rows_included") is not False:
        errors.append("LongMemEval abstention rows must not enter evidence recall")
    longmem_answer = task_by_id.get("longmemeval.end-to-end-qa", {})
    strata = set(longmem_answer.get("strata", []))
    if not {"knowledge-update", "temporal", "multi-session", "abstention"}.issubset(
        strata
    ):
        errors.append("LongMemEval answer strata are incomplete")
    v2_metrics = set(
        task_by_id.get("longmemeval-v2.memory-backend", {}).get("metrics", [])
    )
    if not {
        "overall",
        "static",
        "dynamic",
        "procedure",
        "gotchas",
        "memory_query_latency",
        "lafs",
    }.issubset(v2_metrics):
        errors.append("LongMemEval-V2 native metrics are incomplete")
    state_metrics = set(
        task_by_id.get("state-bench.agent-learning", {}).get("metrics", [])
    )
    if not {
        "pass_at_1",
        "pass_power_5",
        "turns",
        "tool_calls",
        "tokens",
        "cost_proxy",
    }.issubset(state_metrics):
        errors.append("STATE-Bench native metrics are incomplete")
    operations = set(task_by_id.get("memops.lifecycle", {}).get("operations", []))
    if not {"remember", "update", "forget", "reflect", "composed"}.issubset(operations):
        errors.append("MemOps lifecycle operations are incomplete")

    contract = payload.get("backend_query_contract")
    if not isinstance(contract, Mapping):
        errors.append("backend query contract is missing")
    else:
        try:
            probe = {field: f"sentinel-{field}" for field in BACKEND_FORBIDDEN_FIELDS}
            probe.update({"query": "allowed", "namespace": "allowed"})
            view = backend_query_view(probe, contract)
            leaked = BACKEND_FORBIDDEN_FIELDS.intersection(view)
            if leaked:
                errors.append(
                    f"backend query contract leaks evaluator fields: {sorted(leaked)}"
                )
        except ValueError as exc:
            errors.append(str(exc))

    statistics = payload.get("statistics_policy")
    if not isinstance(statistics, Mapping):
        errors.append("statistics policy is missing")
    elif statistics.get("multiple_primary_correction") != "holm":
        errors.append("multiple primary comparison policy is not preregistered as holm")
    return errors
