from __future__ import annotations

import json
import tempfile
from pathlib import Path
from typing import Any, Mapping

from .core import WaveMind
from .evidence import (
    attach_artifact_integrity,
    build_source_manifest,
    file_sha256,
    repository_commit,
    validate_artifact_integrity,
    validate_source_manifest,
)


SCHEMA = "wavemind.evaluation_candidate_admission.v1"
SOURCE_PATHS = (
    "wavemind/core.py",
    "wavemind/storage.py",
    "wavemind/evaluation_lifecycle_diagnostic.py",
    "wavemind/evaluation_candidate_admission.py",
    "benchmarks/evaluation_candidate_admission.py",
    "tests/test_core_persistence.py",
    "tests/test_evaluation_lifecycle_diagnostic.py",
    "tests/test_evaluation_candidate_admission.py",
)


def _json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _check(
    check_id: str,
    passed: bool,
    *,
    observed: Any,
    required: Any,
) -> dict[str, Any]:
    return {
        "id": check_id,
        "status": "passed" if passed else "failed",
        "observed": observed,
        "required": required,
    }


def _verified_metadata(reference: str) -> dict[str, Any]:
    return {
        "verification_status": "verified",
        "verified": True,
        "provenance": [{"source": "operator", "reference": reference}],
    }


def run_correction_operational_checks(temp_root: str | Path) -> dict[str, bool]:
    root = Path(temp_root).resolve()
    root.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=root) as temporary:
        db_path = Path(temporary) / "candidate.sqlite3"
        mind = WaveMind(
            db_path=db_path,
            width=16,
            height=16,
            layers=1,
            score_threshold=0.0,
            persist_access_on_query=False,
            query_feedback_strength=0.0,
        )
        predecessor_id = mind.remember(
            "Current city: Berlin",
            namespace="candidate:tenant",
            metadata={"target_id": "city", **_verified_metadata("city-0")},
        )
        unsafe_rejected = False
        try:
            mind.supersede(
                predecessor_id,
                "Current city: Lisbon",
                namespace="candidate:tenant",
            )
        except ValueError:
            unsafe_rejected = True
        state_unchanged_after_rejection = (
            mind.store.count(namespace="candidate:tenant") == 1
            and mind.store.get(predecessor_id).metadata.get("memory_status")
            != "stale"
        )
        replacement_id = mind.supersede(
            predecessor_id,
            "Current city: Lisbon",
            namespace="candidate:tenant",
            metadata={"target_id": "city", **_verified_metadata("city-1")},
            transition_id="candidate-city-1",
        )
        retried_id = mind.supersede(
            predecessor_id,
            "Current city: Lisbon",
            namespace="candidate:tenant",
            metadata={"target_id": "city", **_verified_metadata("city-1")},
            transition_id="candidate-city-1",
        )
        predecessor = mind.store.get(predecessor_id)
        replacement = mind.store.get(replacement_id)
        chain_preserved = bool(
            predecessor
            and replacement
            and predecessor.metadata.get("memory_status") == "stale"
            and predecessor.metadata.get("_wavemind_transition", {}).get(
                "superseded_by_id"
            )
            == replacement_id
            and replacement.metadata.get("_wavemind_transition", {}).get(
                "supersedes_id"
            )
            == predecessor_id
            and replacement.metadata.get("provenance")
        )
        idempotent = bool(
            retried_id == replacement_id
            and mind.store.count(namespace="candidate:tenant") == 2
            and len(
                mind.audit_events(
                    namespace="candidate:tenant", action="supersede", limit=10
                )
            )
            == 1
        )
        namespace_rejected = False
        try:
            mind.supersede(
                replacement_id,
                "Current city: Porto",
                namespace="candidate:other",
                metadata=_verified_metadata("city-2"),
            )
        except ValueError:
            namespace_rejected = True
        rollback_id = mind.remember(
            "Current editor: Vim",
            namespace="candidate:tenant",
            metadata={"target_id": "editor", **_verified_metadata("editor-0")},
        )
        before_count = mind.store.count(namespace="candidate:tenant")
        failure_raised = False
        try:
            mind.supersede(
                rollback_id,
                "Current editor: Helix",
                namespace="candidate:tenant",
                metadata={
                    **_verified_metadata("editor-1"),
                    "not_json": object(),
                },
                transition_id="candidate-editor-1",
            )
        except TypeError:
            failure_raised = True
        rollback_preserved = bool(
            failure_raised
            and mind.store.count(namespace="candidate:tenant") == before_count
            and mind.store.get(rollback_id).metadata.get("memory_status") != "stale"
        )
        mind.close()

        reopened = WaveMind(
            db_path=db_path,
            width=16,
            height=16,
            layers=1,
            score_threshold=0.0,
            persist_access_on_query=False,
            query_feedback_strength=0.0,
        )
        recalled = reopened.query(
            "current city",
            namespace="candidate:tenant",
            top_k=5,
            metadata_filters={"target_id": "city"},
        )
        restart_preserved = [record.id for record in recalled] == [replacement_id]
        reopened.close()
    return {
        "unsafe_unverified_replacement_rejected": unsafe_rejected,
        "rejection_preserves_predecessor": state_unchanged_after_rejection,
        "provenance_chain_preserved": chain_preserved,
        "retry_idempotent": idempotent,
        "namespace_change_rejected": namespace_rejected,
        "atomic_failure_rolls_back": rollback_preserved,
        "restart_preserves_active_version": restart_preserved,
    }


def build_candidate_admission(
    *,
    project_root: str | Path,
    hypothesis_path: str | Path,
    result_path: str | Path,
    raw_path: str | Path,
    temp_root: str | Path,
) -> dict[str, Any]:
    root = Path(project_root).resolve()
    hypothesis = _json(Path(hypothesis_path))
    result = _json(Path(result_path))
    raw_file = Path(raw_path)
    raw = _json(raw_file)
    acceptance = hypothesis["acceptance"]
    candidate = result["summary"]["wavemind_versioned"]
    checks: list[dict[str, Any]] = []
    integrity_errors = {
        "hypothesis": validate_artifact_integrity(hypothesis),
        "result": validate_artifact_integrity(result),
        "raw": validate_artifact_integrity(raw),
    }
    checks.append(
        _check(
            "input-integrity",
            not any(integrity_errors.values()),
            observed=integrity_errors,
            required="no integrity errors",
        )
    )
    raw_binding = {
        "expected_sha256": result["raw_evidence"]["sha256"],
        "actual_sha256": file_sha256(raw_file),
        "expected_rows": result["raw_evidence"]["row_count"],
        "actual_rows": len(raw.get("per_target", [])),
    }
    checks.append(
        _check(
            "raw-evidence-binding",
            raw_binding["expected_sha256"] == raw_binding["actual_sha256"]
            and raw_binding["expected_rows"] == raw_binding["actual_rows"],
            observed=raw_binding,
            required="matching SHA-256 and row count",
        )
    )
    source_binding = {
        "result": result.get("source_sha"),
        "raw": raw.get("source_sha"),
        "protocol": result.get("protocol", {}).get("payload_sha256"),
        "expected_protocol": hypothesis.get("protocol", {}).get("payload_sha256"),
        "heldout_access": result.get("protocol", {}).get("heldout_access"),
    }
    checks.append(
        _check(
            "exact-source-and-protocol",
            source_binding["result"] == source_binding["raw"]
            and source_binding["protocol"] == source_binding["expected_protocol"]
            and source_binding["heldout_access"] == "forbidden",
            observed=source_binding,
            required="same source, frozen protocol, heldout forbidden",
        )
    )

    metric_specs = (
        (
            "primary-transition",
            candidate["operation_state_transition"],
            acceptance["minimum_operation_state_transition"],
            "minimum",
        ),
        (
            "stale-leakage",
            candidate["stale_leakage"],
            acceptance["maximum_stale_leakage"],
            "maximum",
        ),
        (
            "context-budget",
            candidate["context_characters_mean"],
            acceptance["maximum_context_characters_mean"],
            "maximum",
        ),
        (
            "warm-p95-budget",
            candidate["latency_ms"]["p95"],
            acceptance["maximum_warm_p95_ms"],
            "maximum",
        ),
        (
            "namespace-safety",
            candidate["namespace_leakage"],
            acceptance["maximum_namespace_leakage"],
            "maximum",
        ),
        (
            "unverified-safety",
            candidate["unverified_injection"],
            acceptance["maximum_unverified_injection"],
            "maximum",
        ),
        (
            "deletion-safety",
            candidate["deleted_resurfacing"],
            acceptance["maximum_deleted_resurfacing"],
            "maximum",
        ),
    )
    for check_id, observed, required, direction in metric_specs:
        passed = observed >= required if direction == "minimum" else observed <= required
        checks.append(
            _check(check_id, passed, observed=observed, required={direction: required})
        )
    unaffected = {
        stratum: result["by_operation_type"][stratum]["wavemind_versioned"][
            "operation_state_transition"
        ]
        for stratum in hypothesis["expected_unaffected_strata"]
    }
    checks.append(
        _check(
            "unaffected-strata",
            all(
                value >= acceptance["minimum_unaffected_stratum_transition"]
                for value in unaffected.values()
            ),
            observed=unaffected,
            required={
                "minimum_each": acceptance["minimum_unaffected_stratum_transition"]
            },
        )
    )
    expected_affected = {
        (row["case_id"], row["target_id"])
        for row in hypothesis["expected_affected_rows"]
    }
    raw_rows = raw.get("per_target", [])
    repaired = {
        (row["case_id"], row["target_id"])
        for row in raw_rows
        if row.get("backend") == "wavemind_versioned"
        and row.get("operation_state_transition") is True
        and (row.get("case_id"), row.get("target_id")) in expected_affected
    }
    prior_failures = {
        (row["case_id"], row["target_id"])
        for row in raw_rows
        if row.get("backend") == "wavemind_core"
        and row.get("operation_state_transition") is False
        and (row.get("case_id"), row.get("target_id")) in expected_affected
    }
    checks.append(
        _check(
            "preregistered-row-repair",
            repaired == expected_affected and prior_failures == expected_affected,
            observed={
                "expected": len(expected_affected),
                "prior_failures": len(prior_failures),
                "candidate_repairs": len(repaired),
            },
            required="all preregistered failures repaired and no row substituted",
        )
    )
    operational = run_correction_operational_checks(temp_root)
    checks.append(
        _check(
            "operational-correction-safety",
            all(operational.values()),
            observed=operational,
            required="all operational checks true",
        )
    )
    checks.append(
        _check(
            "candidate-error-taxonomy",
            result.get("candidate_error_taxonomy") == {},
            observed=result.get("candidate_error_taxonomy"),
            required={},
        )
    )
    passed = all(row["status"] == "passed" for row in checks)
    payload = {
        "schema": SCHEMA,
        "status": "passed" if passed else "failed",
        "admitted": passed,
        "source_sha": repository_commit(root),
        "candidate_source_sha": result["source_sha"],
        "hypothesis_id": hypothesis["id"],
        "scope": "bounded_development_candidate_only",
        "evidence_inputs": {
            "hypothesis": {
                "path": "benchmarks/evaluation_hypothesis_stateful_correction_v1.json",
                "payload_sha256": hypothesis["integrity"]["payload_sha256"],
            },
            "result": {
                "path": "benchmarks/evaluation_lifecycle_candidate1_results.json",
                "payload_sha256": result["integrity"]["payload_sha256"],
            },
            "raw_file_sha256": raw_binding["actual_sha256"],
        },
        "checks": checks,
        "metrics": candidate,
        "source_manifest": build_source_manifest(root, SOURCE_PATHS),
        "claim_boundary": (
            "Candidate 1 passed its preregistered MemOps development gate. This is "
            "not validation, held-out, answer-quality, workflow, or general quality evidence."
        ),
    }
    return attach_artifact_integrity(payload)


def validate_candidate_admission(
    payload: Mapping[str, Any],
    *,
    project_root: str | Path,
    require_current_files: bool,
) -> list[str]:
    errors = validate_artifact_integrity(payload)
    if payload.get("schema") != SCHEMA:
        errors.append("candidate admission schema is invalid")
    checks = payload.get("checks")
    if not isinstance(checks, list) or not checks:
        errors.append("candidate admission checks are missing")
        return errors
    all_passed = all(
        isinstance(row, Mapping) and row.get("status") == "passed" for row in checks
    )
    if payload.get("admitted") is not all_passed:
        errors.append("candidate admission status disagrees with checks")
    expected_status = "passed" if all_passed else "failed"
    if payload.get("status") != expected_status:
        errors.append("candidate admission verdict disagrees with checks")
    manifest = payload.get("source_manifest")
    if not isinstance(manifest, Mapping):
        errors.append("candidate source manifest is missing")
    else:
        errors.extend(
            validate_source_manifest(
                Path(project_root),
                manifest,
                require_current_files=require_current_files,
            )
        )
    if require_current_files:
        inputs = payload.get("evidence_inputs")
        if not isinstance(inputs, Mapping):
            errors.append("candidate evidence inputs are missing")
        else:
            for label in ("hypothesis", "result"):
                binding = inputs.get(label)
                if not isinstance(binding, Mapping):
                    errors.append(f"candidate {label} binding is missing")
                    continue
                path = binding.get("path")
                if not isinstance(path, str):
                    errors.append(f"candidate {label} path is invalid")
                    continue
                artifact_path = (Path(project_root) / path).resolve()
                if not artifact_path.is_file():
                    errors.append(f"candidate {label} artifact is missing")
                    continue
                artifact = _json(artifact_path)
                if validate_artifact_integrity(artifact):
                    errors.append(f"candidate {label} artifact integrity is invalid")
                elif artifact.get("integrity", {}).get("payload_sha256") != binding.get(
                    "payload_sha256"
                ):
                    errors.append(f"candidate {label} artifact binding mismatch")
    return errors
