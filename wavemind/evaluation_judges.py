from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping

from .evidence import (
    attach_artifact_integrity,
    build_source_manifest,
    execution_environment,
    repository_commit,
    utc_now,
    validate_artifact_integrity,
    validate_source_manifest,
)


SCHEMA = "wavemind.evaluation_judge_policy.v1"
SOURCE_PATHS = (
    "wavemind/evaluation_judges.py",
    "benchmarks/evaluation_judge_policy.py",
    "tests/test_evaluation_judges.py",
)
STATE_JUDGE_PROMPT_HASHES = {
    "travel/judge_task_requirements.md": "dd4abe82eedb4873cfa015708df99f59cfbfeaa85ac090b01bd1d75eb0500487",
    "travel/judge_ux_quality.md": "b04009d159fb477c3a215f30f10793c4e0a5587e578d07fcd2bfc7d719f90598",
    "customer_support/judge_task_requirements.md": "246c76f59f3cd0e736da35b9beb985088778ff233287454b8bae674285718c72",
    "customer_support/judge_ux_quality.md": "8b6ecae22872ab860d4a54f37e5bd4a6a160033b833cd1b0de6a3673640d7067",
    "shopping_assistant/judge_task_requirements.md": "558947b2ce0b5d90a633e7d44e8599c329a96ac5ed9e43c9d37ffb5e6cf3c055",
    "shopping_assistant/judge_ux_quality.md": "0234643a8dcf766c390aff2dc11b2f74f0e13ef7a38b29df70165bd333b82656",
}


def build_evaluation_judge_policy(*, project_root: str | Path) -> dict[str, Any]:
    root = Path(project_root).resolve()
    payload = {
        "schema": SCHEMA,
        "generated_at": utc_now(),
        "source_sha": repository_commit(root),
        "active_primary_scorers": [
            {
                "family": "state-bench-agent-learning",
                "metric": "deterministic_final_state",
                "kind": "deterministic",
                "llm_judge_required": False,
            },
            {
                "family": "memops-lifecycle",
                "metric": "structured_operation_state_transition",
                "kind": "deterministic",
                "llm_judge_required": False,
            },
        ],
        "llm_judges": [],
        "excluded_native_judge_lanes": [
            {
                "lane": "state-bench-ux",
                "reason": "The official GPT-5.4 UX judge is pinned but not locally calibrated; UX is excluded from the mandatory local claim.",
                "official_model": "gpt-5.4",
                "temperature": 0,
                "seed": 17,
                "prompt_hashes": STATE_JUDGE_PROMPT_HASHES,
            },
            {
                "lane": "longmemeval-answer-judge",
                "reason": "No local open-weight judge calibration and agreement artifact exists yet; the lane is excluded before product tuning.",
            },
            {
                "lane": "longmemeval-v2-local-reader",
                "reason": "The official-compatible local reader and judge profile is not calibrated yet; the lane is excluded before product tuning.",
            },
            {
                "lane": "memory-agent-bench-generative-components",
                "reason": "Generated-answer and official judge components remain excluded until a pinned local reader/scorer calibration exists.",
            },
            {
                "lane": "memops-generated-answer",
                "reason": "Generated-answer quality is secondary to the active structured lifecycle scorer until a pinned reader calibration exists.",
            },
        ],
        "policy": {
            "mandatory_llm_judge_fields": [
                "model_revision",
                "prompt_sha256",
                "temperature",
                "seed",
                "calibration_set_sha256",
                "agreement_metric",
                "agreement_value",
                "minimum_agreement",
                "repeat_count",
            ],
            "unavailable_judge_action": "exclude_lane_before_product_tuning",
            "synthetic_agreement_forbidden": True,
            "claim_cannot_expand_without_new_calibration": True,
        },
        "source_manifest": build_source_manifest(root, SOURCE_PATHS),
        "environment": execution_environment(profile="evaluation-judge-policy"),
        "claim_boundary": (
            "Judge validity for the active deterministic STATE-Bench and MemOps primary "
            "metrics only. Excluded UX and generative lanes make no quality claim."
        ),
    }
    return attach_artifact_integrity(payload)


def validate_evaluation_judge_policy(
    payload: Mapping[str, Any],
    *,
    project_root: str | Path,
    expected_source_sha: str,
) -> list[str]:
    errors = validate_artifact_integrity(payload)
    if payload.get("schema") != SCHEMA:
        errors.append("evaluation judge policy schema is invalid")
    if payload.get("source_sha") != expected_source_sha:
        errors.append("evaluation judge policy source SHA mismatch")
    source_manifest = payload.get("source_manifest")
    if not isinstance(source_manifest, Mapping):
        errors.append("evaluation judge source manifest is missing")
    else:
        errors.extend(
            validate_source_manifest(
                Path(project_root), source_manifest, require_current_files=True
            )
        )
    active = payload.get("active_primary_scorers")
    if not isinstance(active, list) or not active:
        errors.append("active primary scorers are missing")
        active = []
    required_judge_families = {
        str(item.get("family"))
        for item in active
        if isinstance(item, Mapping) and item.get("llm_judge_required") is True
    }
    judges = payload.get("llm_judges")
    if not isinstance(judges, list):
        errors.append("LLM judge registry is invalid")
        judges = []
    judge_by_family = {
        str(item.get("family")): item for item in judges if isinstance(item, Mapping)
    }
    required_fields = payload.get("policy", {}).get("mandatory_llm_judge_fields", [])
    for family in required_judge_families:
        judge = judge_by_family.get(family)
        if not isinstance(judge, Mapping):
            errors.append(f"required LLM judge is missing: {family}")
            continue
        missing = [field for field in required_fields if judge.get(field) is None]
        if missing:
            errors.append(f"required LLM judge fields are missing: {family}: {missing}")
            continue
        if float(judge["agreement_value"]) < float(judge["minimum_agreement"]):
            errors.append(f"required LLM judge agreement is below threshold: {family}")
        if int(judge["repeat_count"]) < 3:
            errors.append(f"required LLM judge repeat count is below three: {family}")
    exclusions = payload.get("excluded_native_judge_lanes")
    if not isinstance(exclusions, list) or not exclusions:
        errors.append("native judge exclusions are not declared")
    else:
        for exclusion in exclusions:
            if not isinstance(exclusion, Mapping) or not exclusion.get("reason"):
                errors.append("native judge exclusion has no factual reason")
    policy = payload.get("policy")
    if not isinstance(policy, Mapping):
        errors.append("judge policy is missing")
    else:
        if (
            policy.get("unavailable_judge_action")
            != "exclude_lane_before_product_tuning"
        ):
            errors.append("unavailable judges do not fail closed")
        if policy.get("synthetic_agreement_forbidden") is not True:
            errors.append("synthetic judge agreement is not forbidden")
    return errors
