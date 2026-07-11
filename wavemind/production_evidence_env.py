from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from .production_evidence import (
    build_production_evidence_dispatch_plan,
    build_scale_gap_manifest,
    evaluate_production_evidence,
    evaluate_production_evidence_preflight,
)


PRODUCTION_EVIDENCE_ENV_SCHEMA = "wavemind.production_evidence_env_contract.v1"


ENV_METADATA: dict[str, dict[str, str]] = {
    "WAVEMIND_CLUSTER_NODES": {
        "kind": "api-node-list",
        "example": "node-a=https://wm-a.staging.example.com,node-b=https://wm-b.staging.example.com,node-c=https://wm-c.staging.example.com,node-d=https://wm-d.staging.example.com",
        "description": "Remote WaveMind API nodes for the external service-node cluster workload.",
    },
    "WAVEMIND_CLUSTER_NODES_MANIFEST_JSON": {
        "kind": "api-node-manifest-json",
        "example": '{"environment":"staging","source":"kubernetes","deployment_id":"wm-staging-2026-07","nodes":[{"id":"node-a","url":"https://wm-a.staging.example.com"},{"id":"node-b","url":"https://wm-b.staging.example.com"},{"id":"node-c","url":"https://wm-c.staging.example.com"},{"id":"node-d","url":"https://wm-d.staging.example.com"}]}',
        "description": "JSON manifest alternative for external service-node cluster evidence.",
    },
    "WAVEMIND_ACTIVE_ACTIVE_REGIONS": {
        "kind": "api-region-list",
        "example": "us=https://wm-us.staging.example.com,eu=https://wm-eu.staging.example.com,ap=https://wm-ap.staging.example.com",
        "description": "Remote WaveMind API regions for active-active namespace sync evidence.",
    },
    "WAVEMIND_ACTIVE_ACTIVE_REGIONS_MANIFEST_JSON": {
        "kind": "api-region-manifest-json",
        "example": '{"environment":"staging","source":"kubernetes","deployment_id":"wm-regions-2026-07","regions":[{"id":"us","url":"https://wm-us.staging.example.com"},{"id":"eu","url":"https://wm-eu.staging.example.com"},{"id":"ap","url":"https://wm-ap.staging.example.com"}]}',
        "description": "JSON manifest alternative for remote active-active region evidence.",
    },
    "WAVEMIND_SERVERLESS_NODES": {
        "kind": "serverless-api-node-list",
        "example": "https://wm-serverless-a.example.com,https://wm-serverless-b.example.com",
        "description": "Deployed serverless/managed WaveMind API nodes for remote telemetry evidence.",
    },
    "WAVEMIND_QDRANT_URL": {
        "kind": "qdrant-url",
        "example": "https://qdrant-10m.staging.example.com:6333",
        "description": "Single Qdrant service URL for 10M service-backed streaming load.",
    },
    "WAVEMIND_QDRANT_URLS": {
        "kind": "qdrant-url-list",
        "example": "https://qdrant-a.staging.example.com:6333,https://qdrant-b.staging.example.com:6333",
        "description": "Comma-separated Qdrant shard URLs for 10M sharded and 100M sharded service load.",
    },
    "WAVEMIND_QDRANT_API_KEY": {
        "kind": "qdrant-api-secret",
        "example": "REDACTED_QDRANT_API_KEY",
        "description": "Optional Qdrant API key for the single-service Qdrant production load job.",
    },
    "WAVEMIND_QDRANT_API_KEYS": {
        "kind": "qdrant-api-secret-list",
        "example": "REDACTED_QDRANT_API_KEY_A,REDACTED_QDRANT_API_KEY_B",
        "description": "Optional comma-separated Qdrant API keys for sharded Qdrant production load jobs.",
    },
    "WAVEMIND_PGVECTOR_DSNS": {
        "kind": "postgres-dsn-list",
        "example": (
            "postgresql://USER:PASSWORD@pgvector-a.staging.example.com:5432/wavemind,"
            "postgresql://USER:PASSWORD@pgvector-b.staging.example.com:5432/wavemind"
        ),
        "description": (
            "Comma-separated PostgreSQL/pgvector service DSNs for the namespace-sharded "
            "10M streaming load."
        ),
    },
    "WAVEMIND_FAISS_IVFPQ_PATH": {
        "kind": "filesystem-path",
        "example": "/mnt/wavemind/faiss/wavemind-ivfpq-50m.faiss",
        "description": "Persisted FAISS IVF-PQ index path for the 50M streaming profile.",
    },
    "WAVEMIND_FAISS_IVFPQ_FREE_GB": {
        "kind": "disk-free-override-gb",
        "example": "8",
        "description": "Optional deterministic free-disk override for FAISS IVF-PQ preflight.",
    },
    "WAVEMIND_API_KEY": {
        "kind": "api-secret",
        "example": "REDACTED_API_KEY",
        "description": "Optional API key used when remote WaveMind endpoints require authentication.",
    },
}


def _utc_now() -> str:
    return (
        datetime.now(timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )


def _env_value(env: Mapping[str, str], name: str) -> str:
    return str(env.get(name) or "").strip()


def _secret_command(name: str, *, repo: str) -> str:
    return f"printf '%s' \"${name}\" | gh secret set {name} --repo {repo} --body-file -"


def _env_example_line(name: str) -> str:
    example = ENV_METADATA.get(name, {}).get("example", f"<{name}>")
    return f"{name}={example}"


def _status_for_variable(
    *,
    name: str,
    env: Mapping[str, str],
    missing_names: set[str],
    required_names: set[str],
    recommended_names: set[str],
) -> str:
    if _env_value(env, name):
        return "configured"
    if name in missing_names:
        return "missing"
    if name in required_names:
        return "alternative_or_inherited"
    if name in recommended_names:
        return "recommended"
    return "optional"


def build_production_evidence_env_contract(
    root: Path | str = Path.cwd(),
    *,
    env: Mapping[str, str] | None = None,
    repo: str = "CaspianG/wavemind",
) -> dict[str, Any]:
    root = Path(root)
    environment = dict(os.environ if env is None else env)
    strict = evaluate_production_evidence(root)
    preflight = evaluate_production_evidence_preflight(root, env=environment)
    dispatch = build_production_evidence_dispatch_plan(root, env=environment)
    scale_gap = build_scale_gap_manifest(root)

    required_names: set[str] = set()
    missing_names: set[str] = set()
    recommended_names: set[str] = set()
    used_by: dict[str, set[str]] = {}
    workflows: dict[str, set[str]] = {}
    artifacts: dict[str, set[str]] = {}
    claims: dict[str, set[str]] = {}
    workflow_inputs: dict[str, set[str]] = {}

    def register(
        name: str,
        *,
        requirement_id: str,
        workflow: str | None = None,
        artifact: str | None = None,
        claim: str | None = None,
        input_name: str | None = None,
        required: bool = True,
        missing: bool = False,
    ) -> None:
        if required:
            required_names.add(name)
        if missing:
            missing_names.add(name)
        used_by.setdefault(name, set()).add(requirement_id)
        if workflow:
            workflows.setdefault(name, set()).add(workflow)
        if artifact:
            artifacts.setdefault(name, set()).add(artifact)
        if claim:
            claims.setdefault(name, set()).add(claim)
        if input_name:
            workflow_inputs.setdefault(name, set()).add(input_name)

    for check in preflight.get("checks", []):
        if not isinstance(check, dict):
            continue
        check_id = str(check.get("id") or "unknown")
        output_artifact = str(check.get("output_artifact") or "")
        for name in check.get("required_env", []) or []:
            register(
                str(name),
                requirement_id=check_id,
                artifact=output_artifact,
                required=True,
                missing=str(name) in set(check.get("missing_env", []) or []),
            )
        for warning in check.get("warnings", []) or []:
            if "WAVEMIND_API_KEY" in str(warning):
                recommended_names.add("WAVEMIND_API_KEY")
                register(
                    "WAVEMIND_API_KEY",
                    requirement_id=check_id,
                    artifact=output_artifact,
                    required=False,
                    missing=False,
                )

    for job in dispatch.get("jobs", []) or []:
        if not isinstance(job, dict):
            continue
        job_id = str(job.get("id") or "unknown")
        workflow = str(job.get("workflow") or "")
        artifact = str(job.get("artifact") or "")
        claim = str(job.get("claim_unlocked") or "")
        missing_for_job = set(str(name) for name in job.get("missing_env", []) or [])
        for name in job.get("required_env", []) or []:
            register(
                str(name),
                requirement_id=job_id,
                workflow=workflow,
                artifact=artifact,
                claim=claim,
                required=True,
                missing=str(name) in missing_for_job,
            )
        for name in job.get("required_secrets", []) or []:
            recommended_names.add(str(name))
            register(
                str(name),
                requirement_id=job_id,
                workflow=workflow,
                artifact=artifact,
                claim=claim,
                required=False,
                missing=False,
            )
        bindings = job.get("input_bindings") if isinstance(job.get("input_bindings"), dict) else {}
        for input_name, value in bindings.items():
            env_name = str(value).lstrip("$")
            register(
                env_name,
                requirement_id=job_id,
                workflow=workflow,
                artifact=artifact,
                claim=claim,
                input_name=str(input_name),
                required=True,
                missing=env_name in missing_for_job,
            )

    for row in scale_gap.get("profile_gaps", []) or []:
        if not isinstance(row, dict):
            continue
        requirement_id = str(row.get("requirement_id") or row.get("profile") or "unknown")
        for name in row.get("missing_env", []) or []:
            register(
                str(name),
                requirement_id=requirement_id,
                artifact=str(row.get("output_artifact") or ""),
                claim=str(row.get("claim_unlocked") or ""),
                required=True,
                missing=True,
            )

    all_names = sorted(required_names | recommended_names | set(ENV_METADATA))
    variables: list[dict[str, Any]] = []
    for name in all_names:
        metadata = ENV_METADATA.get(name, {})
        status = _status_for_variable(
            name=name,
            env=environment,
            missing_names=missing_names,
            required_names=required_names,
            recommended_names=recommended_names,
        )
        variables.append(
            {
                "name": name,
                "status": status,
                "configured": bool(_env_value(environment, name)),
                "required": name in required_names,
                "recommended": name in recommended_names,
                "kind": metadata.get("kind", "environment"),
                "sensitivity": "secret_or_internal",
                "description": metadata.get("description", ""),
                "example": metadata.get("example", f"<{name}>"),
                "used_by": sorted(used_by.get(name, set())),
                "workflows": sorted(workflows.get(name, set())),
                "workflow_inputs": sorted(workflow_inputs.get(name, set())),
                "artifacts": sorted(artifacts.get(name, set())),
                "claims": sorted(claims.get(name, set())),
                "github_secret": name,
                "github_secret_command": _secret_command(name, repo=repo),
            }
        )

    missing_required = [row["name"] for row in variables if row["status"] == "missing"]
    configured_required = [
        row["name"] for row in variables if row["required"] and row["configured"]
    ]
    recommended_missing = [
        row["name"]
        for row in variables
        if row["recommended"] and not row["configured"] and row["name"] not in missing_required
    ]
    overall_status = "ready" if not missing_required else "action_required"

    checks = _contract_checks(
        variables=variables,
        strict=strict,
        preflight=preflight,
        dispatch=dispatch,
        scale_gap=scale_gap,
        env=environment,
    )
    if any(not row["pass"] for row in checks):
        overall_status = "invalid"

    env_example = render_production_evidence_env_example({"variables": variables})
    return {
        "schema": PRODUCTION_EVIDENCE_ENV_SCHEMA,
        "generated_at": _utc_now(),
        "overall_status": overall_status,
        "repo": repo,
        "claim_boundary": (
            "Environment contract only. It stores placeholders and secret names, never "
            "credential values, and does not unlock production claims until strict "
            "evidence artifacts pass ingestion and validation."
        ),
        "summary": {
            "overall_status": overall_status,
            "required_env_count": sum(1 for row in variables if row["required"]),
            "configured_required_count": len(configured_required),
            "missing_required_count": len(missing_required),
            "recommended_secret_count": len(recommended_names),
            "recommended_missing_count": len(recommended_missing),
            "workflow_count": len(
                {
                    workflow
                    for names in workflows.values()
                    for workflow in names
                    if workflow
                }
            ),
            "strict_requirement_count": len(strict.get("requirements", []) or []),
            "preflight_check_count": len(preflight.get("checks", []) or []),
            "dispatch_job_count": len(dispatch.get("jobs", []) or []),
            "scale_gap_profile_count": len(scale_gap.get("profile_gaps", []) or []),
            "missing_required_env": missing_required,
            "recommended_missing_env": recommended_missing,
        },
        "variables": variables,
        "github_actions": {
            "secret_policy": "Set these as GitHub Actions secrets or environment-scoped secrets; do not commit their values.",
            "secret_names": [row["name"] for row in variables],
            "secret_set_commands": [row["github_secret_command"] for row in variables],
        },
        "env_example": env_example,
        "checks": checks,
        "source_files": [
            "benchmarks/production_evidence_results.json",
            "benchmarks/production_evidence_preflight_results.json",
            "benchmarks/production_evidence_dispatch_results.json",
            "benchmarks/scale_gap_results.json",
        ],
    }


def _contract_checks(
    *,
    variables: list[dict[str, Any]],
    strict: dict[str, Any],
    preflight: dict[str, Any],
    dispatch: dict[str, Any],
    scale_gap: dict[str, Any],
    env: Mapping[str, str],
) -> list[dict[str, Any]]:
    variable_names = {row["name"] for row in variables}
    preflight_env = {
        str(name)
        for check in preflight.get("checks", []) or []
        if isinstance(check, dict)
        for name in check.get("required_env", []) or []
    }
    dispatch_env = {
        str(name)
        for job in dispatch.get("jobs", []) or []
        if isinstance(job, dict)
        for name in list(job.get("required_env", []) or [])
        + list(job.get("required_secrets", []) or [])
    }
    scale_gap_env = {
        str(name)
        for row in scale_gap.get("profile_gaps", []) or []
        if isinstance(row, dict)
        for name in row.get("missing_env", []) or []
    }
    missing_from_contract = sorted((preflight_env | dispatch_env | scale_gap_env) - variable_names)
    serialized = json.dumps(variables, ensure_ascii=False)
    configured_values: list[str] = []
    for row in variables:
        name = str(row["name"])
        value = _env_value(env, name)
        example = str(ENV_METADATA.get(name, {}).get("example") or "")
        if len(value) >= 8 and value != example:
            configured_values.append(value)
    return [
        {
            "name": "all_preflight_env_represented",
            "pass": preflight_env.issubset(variable_names),
            "detail": f"{len(preflight_env & variable_names)}/{len(preflight_env)} preflight env vars represented",
        },
        {
            "name": "all_dispatch_env_represented",
            "pass": dispatch_env.issubset(variable_names),
            "detail": f"{len(dispatch_env & variable_names)}/{len(dispatch_env)} dispatch env vars represented",
        },
        {
            "name": "all_scale_gap_env_represented",
            "pass": scale_gap_env.issubset(variable_names),
            "detail": f"{len(scale_gap_env & variable_names)}/{len(scale_gap_env)} scale-gap env vars represented",
        },
        {
            "name": "no_missing_contract_rows",
            "pass": not missing_from_contract,
            "detail": ", ".join(missing_from_contract) if missing_from_contract else "none",
        },
        {
            "name": "strict_requirements_joined",
            "pass": len(strict.get("requirements", []) or []) >= 8,
            "detail": f"{len(strict.get('requirements', []) or [])} strict requirements",
        },
        {
            "name": "secret_values_not_serialized",
            "pass": not any(value in serialized for value in configured_values),
            "detail": "contract uses placeholders and secret names only",
        },
    ]


def render_production_evidence_env_example(payload: dict[str, Any]) -> str:
    variables = payload.get("variables", []) if isinstance(payload.get("variables"), list) else []
    lines = [
        "# WaveMind strict production evidence environment",
        "# Fill these locally or as GitHub Actions environment-scoped secrets.",
        "# Do not commit real values.",
        "",
    ]
    for row in variables:
        if not isinstance(row, dict):
            continue
        description = str(row.get("description") or "")
        if description:
            lines.append(f"# {description}")
        lines.append(_env_example_line(str(row.get("name"))))
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def render_production_evidence_env_markdown(payload: dict[str, Any]) -> str:
    summary = payload["summary"]
    lines = [
        "# WaveMind Production Evidence Environment Contract",
        "",
        "This is the operator-facing environment contract for strict production",
        "evidence runs. It maps every required variable to the claims, workflows,",
        "artifacts, and GitHub secrets it unlocks. It is secret-safe: values are not serialized.",
        "",
        payload["claim_boundary"],
        "",
        "| metric | value |",
        "|---|---:|",
        f"| overall status | `{payload['overall_status']}` |",
        f"| required env | `{summary['required_env_count']}` |",
        f"| configured required env | `{summary['configured_required_count']}` |",
        f"| missing required env | `{summary['missing_required_count']}` |",
        f"| recommended missing env | `{summary['recommended_missing_count']}` |",
        f"| workflows | `{summary['workflow_count']}` |",
        f"| dispatch jobs | `{summary['dispatch_job_count']}` |",
        f"| strict requirements | `{summary['strict_requirement_count']}` |",
        "",
        "## Variables",
        "",
        "| variable | status | kind | used by | workflows | artifacts |",
        "|---|---|---|---|---|---|",
    ]
    for row in payload.get("variables", []):
        lines.append(
            "| `{name}` | `{status}` | `{kind}` | {used_by} | {workflows} | {artifacts} |".format(
                name=row["name"],
                status=row["status"],
                kind=row["kind"],
                used_by=", ".join(f"`{item}`" for item in row.get("used_by", [])) or "",
                workflows=", ".join(f"`{item}`" for item in row.get("workflows", [])) or "",
                artifacts=", ".join(f"`{item}`" for item in row.get("artifacts", [])) or "",
            )
        )
    lines.extend(
        [
            "",
            "## GitHub Secrets",
            "",
            "Run these from a shell where each variable is already exported. The",
            "commands pipe values from the environment; values are not echoed into",
            "the repository.",
            "",
        ]
    )
    for command in payload.get("github_actions", {}).get("secret_set_commands", []):
        lines.append(f"- `{command}`")
    lines.extend(["", "## Checks", "", "| check | status | detail |", "|---|---|---|"])
    for check in payload.get("checks", []):
        lines.append(
            f"| {check['name']} | `{'pass' if check['pass'] else 'fail'}` | {check['detail']} |"
        )
    lines.append("")
    return "\n".join(lines)


def write_production_evidence_env_artifacts(
    payload: dict[str, Any],
    *,
    output: Path,
    markdown_output: Path,
    env_output: Path,
) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    markdown_output.parent.mkdir(parents=True, exist_ok=True)
    markdown_output.write_text(render_production_evidence_env_markdown(payload), encoding="utf-8")
    env_output.parent.mkdir(parents=True, exist_ok=True)
    env_output.write_text(render_production_evidence_env_example(payload), encoding="utf-8")
