from __future__ import annotations

import json
import shutil
import subprocess
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Mapping

from .evidence import (
    attach_artifact_integrity,
    canonical_json_bytes,
    file_sha256,
    sha256_bytes,
    validate_artifact_integrity,
)
from .evaluation_splits import SCHEMA as EVALUATION_SPLIT_SCHEMA
from .evaluation_splits import STATE_BENCH_REVISION
from .scientific_memory import MemoryDefinition, MemoryKind, ValidityInterval
from .scientific_baselines import hardware_inventory
from .scientific_runtime import ScientificCandidateMode, ScientificMemoryRuntime


STATE_BENCH_PREPARED_DEV_SCHEMA = "wavemind.state_bench_prepared_development.v1"
STATE_BENCH_LEARNING_MANIFEST_SCHEMA = "wavemind.state_bench_learning_manifest.v1"
STATE_BENCH_DEV_SEED = 17
STATE_BENCH_DEV_EVALUATION_CASES = 3
STATE_BENCH_RETRIEVAL_TOP_K = 3
STATE_BENCH_RETRIEVAL_TOKEN_BUDGET = 600
STATE_BENCH_BOUNDED_DEV_RUNS = 3
STATE_BENCH_AGENT_MODEL = "gpt-5.4"
STATE_BENCH_REQUIRED_CREDENTIAL_ENV = (
    "STATE_BENCH_EVAL_ENDPOINT",
    "STATE_BENCH_EVAL_DEPLOYMENTS",
    "STATE_BENCH_EVAL_API_KEY",
    "STATE_BENCH_AGENT_PROVIDER",
    "STATE_BENCH_AGENT_MODEL",
    "STATE_BENCH_AGENT_API_KEY",
    "STATE_BENCH_AGENT_ENDPOINT",
    "STATE_BENCH_AGENT_DEPLOYMENTS",
    "OPENAI_API_KEY",
)
_WRITE_TOOL_PREFIXES = (
    "add_",
    "apply_",
    "book_",
    "cancel_",
    "change_",
    "create_",
    "delete_",
    "exchange_",
    "issue_",
    "modify_",
    "place_",
    "redeem_",
    "refund_",
    "remove_",
    "return_",
    "set_",
    "submit_",
    "update_",
)


@dataclass(frozen=True)
class StateBenchDevelopmentPlan:
    domain: str
    seed: int
    learning_units: tuple[Mapping[str, Any], ...]
    evaluation_units: tuple[Mapping[str, Any], ...]

    @property
    def learning_unit_ids(self) -> tuple[str, ...]:
        return tuple(str(unit["unit_id"]) for unit in self.learning_units)

    @property
    def evaluation_unit_ids(self) -> tuple[str, ...]:
        return tuple(str(unit["unit_id"]) for unit in self.evaluation_units)


def _git_sha(root: str | Path) -> str:
    return subprocess.check_output(
        ["git", "rev-parse", "HEAD"],
        cwd=Path(root),
        text=True,
        encoding="utf-8",
    ).strip()


def _run_official_loader_preflight(
    *,
    project_root: Path,
    state_bench_root: Path,
) -> dict[str, Any]:
    uv_executable = shutil.which("uv")
    if not uv_executable:
        raise RuntimeError("uv is required for the official STATE-Bench runner")
    code = (
        "from state_bench.agents.loader import load_root_agent_class;"
        f"root={str(project_root)!r};"
        "names=['ScientificStateBenchAgent',"
        "'ScientificStateBenchNoMemoryControlAgent'];"
        "print(','.join(load_root_agent_class(name, root=root).__name__ "
        "for name in names))"
    )
    argv = [
        uv_executable,
        "run",
        "--project",
        str(state_bench_root),
        "--with-editable",
        str(project_root),
        "python",
        "-c",
        code,
    ]
    completed = subprocess.run(
        argv,
        cwd=project_root,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=180,
        check=False,
    )
    expected = "ScientificStateBenchAgent,ScientificStateBenchNoMemoryControlAgent"
    if completed.returncode or completed.stdout.strip() != expected:
        raise RuntimeError(
            "official STATE-Bench loader preflight failed: "
            + (completed.stderr.strip() or completed.stdout.strip())
        )
    return {
        "argv": argv,
        "returncode": completed.returncode,
        "stdout": completed.stdout.strip(),
        "stderr": completed.stderr.strip(),
        "both_agent_classes_loaded": True,
    }


def _validate_source_checkout(project_root: Path, source_sha: str) -> None:
    if _git_sha(project_root) != source_sha:
        raise RuntimeError("STATE-Bench source SHA does not match project checkout")
    status = subprocess.check_output(
        ["git", "status", "--porcelain", "--untracked-files=no"],
        cwd=project_root,
        text=True,
        encoding="utf-8",
    ).strip()
    if status:
        raise RuntimeError(
            "tracked project changes must be committed before preparation"
        )
    for relative in (
        "agents/scientific_state_bench_agent.py",
        "wavemind/scientific_state_bench.py",
    ):
        completed = subprocess.run(
            ["git", "cat-file", "-e", f"{source_sha}:{relative}"],
            cwd=project_root,
            capture_output=True,
            check=False,
        )
        if completed.returncode:
            raise RuntimeError(
                f"STATE-Bench source is absent from exact SHA: {relative}"
            )


def build_state_bench_development_plan(
    split_manifest: Mapping[str, Any],
    *,
    domain: str,
    seed: int = STATE_BENCH_DEV_SEED,
    evaluation_case_count: int = STATE_BENCH_DEV_EVALUATION_CASES,
) -> StateBenchDevelopmentPlan:
    errors = validate_artifact_integrity(split_manifest)
    if errors:
        raise ValueError("evaluation split integrity failed: " + "; ".join(errors))
    if split_manifest.get("schema") != EVALUATION_SPLIT_SCHEMA:
        raise ValueError("evaluation split schema mismatch")
    upstream = split_manifest.get("upstream")
    if (
        not isinstance(upstream, Mapping)
        or upstream.get("state-bench", {}).get("revision") != STATE_BENCH_REVISION
    ):
        raise ValueError("STATE-Bench split revision mismatch")
    if evaluation_case_count < 1:
        raise ValueError("evaluation_case_count must be positive")
    units = [
        unit
        for unit in split_manifest.get("units") or []
        if isinstance(unit, Mapping)
        and unit.get("dataset") == "state-bench"
        and unit.get("domain") == domain
        and unit.get("source_split") == "train"
        and unit.get("split") == "development"
    ]
    if len(units) != 80:
        raise ValueError(
            f"STATE-Bench {domain} development partition must contain 80 units"
        )
    ranked = sorted(
        units,
        key=lambda unit: (
            sha256_bytes(f"{seed}:{unit['unit_id']}".encode("utf-8")),
            str(unit["unit_id"]),
        ),
    )
    if evaluation_case_count >= len(ranked):
        raise ValueError("development evaluation must leave learning units")
    evaluation = tuple(ranked[:evaluation_case_count])
    evaluation_ids = {str(unit["unit_id"]) for unit in evaluation}
    learning = tuple(
        sorted(
            (unit for unit in ranked if str(unit["unit_id"]) not in evaluation_ids),
            key=lambda unit: str(unit["unit_id"]),
        )
    )
    return StateBenchDevelopmentPlan(
        domain=domain,
        seed=seed,
        learning_units=learning,
        evaluation_units=evaluation,
    )


def _trajectory_path(root: Path, domain: str, task_id: str) -> Path:
    return root / "datasets" / "train_task_trajectories" / domain / f"{task_id}.json"


def _task_id(unit: Mapping[str, Any]) -> str:
    task_id = str(unit.get("task_id") or "")
    if not task_id or Path(task_id).name != task_id:
        raise ValueError("STATE-Bench task ID is invalid")
    return task_id


def extract_procedure_memory(
    *,
    unit: Mapping[str, Any],
    trajectory: Mapping[str, Any],
    domain: str,
) -> MemoryDefinition:
    conversation = trajectory.get("conversation")
    if not isinstance(conversation, list) or not conversation:
        raise ValueError("STATE-Bench trajectory conversation is missing")
    tool_names: list[str] = []
    for turn in conversation:
        if not isinstance(turn, Mapping):
            continue
        for call in turn.get("tool_calls") or []:
            if not isinstance(call, Mapping):
                continue
            name = str(call.get("name") or "").strip()
            if name:
                tool_names.append(name)
    if not tool_names:
        raise ValueError("STATE-Bench trajectory has no tool sequence")
    task_id = _task_id(unit)
    memory_id = (
        "state-procedure-"
        + sha256_bytes(
            canonical_json_bytes(
                {
                    "unit_id": unit["unit_id"],
                    "tool_names": tool_names,
                }
            )
        )[:24]
    )
    sequence = " -> ".join(tool_names)
    request_family = ", ".join(
        dict.fromkeys(name.replace("_", " ") for name in tool_names)
    )
    content = (
        f"Unverified observed {domain} procedure for requests involving "
        f"{request_family}: use tool sequence {sequence}. Treat this as candidate "
        "guidance only; re-check current policy, tool results, user identity, and "
        "confirmation before any state-changing action."
    )
    has_write = any(name.startswith(_WRITE_TOOL_PREFIXES) for name in tool_names)
    return MemoryDefinition(
        memory_id=memory_id,
        kind=MemoryKind.PROCEDURE,
        content=content,
        preconditions=(
            f"domain={domain}",
            "current policy and tool state available",
        ),
        effects=tuple(dict.fromkeys(tool_names)),
        applicability={"domain": domain},
        validity=ValidityInterval(),
        provenance=(
            f"state-bench:{STATE_BENCH_REVISION}:{domain}:{task_id}",
            f"trajectory-sha256:{unit['trajectory_sha256']}",
        ),
        estimated_tokens=max(1, (len(content.encode("utf-8")) + 3) // 4),
        estimated_latency_ms=0.1,
        safety_risk=0.25 if has_write else 0.0,
    )


def _definition_payload(definition: MemoryDefinition) -> dict[str, Any]:
    return {
        "memory_id": definition.memory_id,
        "kind": definition.kind.value,
        "content": definition.content,
        "preconditions": list(definition.preconditions),
        "effects": list(definition.effects),
        "applicability": dict(definition.applicability),
        "validity": asdict(definition.validity),
        "provenance": list(definition.provenance),
        "estimated_tokens": definition.estimated_tokens,
        "estimated_latency_ms": definition.estimated_latency_ms,
        "safety_risk": definition.safety_risk,
    }


def prepare_state_bench_development_store(
    *,
    project_root: str | Path,
    state_bench_root: str | Path,
    split_manifest: Mapping[str, Any],
    protocol_digest: str,
    source_sha: str,
    domain: str,
    database_path: str | Path,
    learning_manifest_path: str | Path,
    environment: Mapping[str, str],
    seed: int = STATE_BENCH_DEV_SEED,
    evaluation_case_count: int = STATE_BENCH_DEV_EVALUATION_CASES,
) -> dict[str, Any]:
    project = Path(project_root).resolve()
    root = Path(state_bench_root).resolve()
    if _git_sha(root) != STATE_BENCH_REVISION:
        raise RuntimeError("STATE-Bench upstream SHA mismatch")
    _validate_source_checkout(project, source_sha)
    database = Path(database_path).resolve()
    event_database = database.with_name(database.name + ".scientific-events.sqlite3")
    learning_manifest = Path(learning_manifest_path).resolve()
    for output in (database, event_database, learning_manifest):
        if output.exists():
            raise FileExistsError(f"prepared STATE-Bench output is retained: {output}")
    plan = build_state_bench_development_plan(
        split_manifest,
        domain=domain,
        seed=seed,
        evaluation_case_count=evaluation_case_count,
    )
    official_root = root / "state_bench"
    agent_path = project / "agents" / "scientific_state_bench_agent.py"
    preparation_path = project / "wavemind" / "scientific_state_bench.py"
    required_sources = (
        agent_path,
        preparation_path,
        root / "uv.lock",
        root / "pyproject.toml",
        official_root / "scripts" / "run_batch.py",
        official_root / "agents" / "state_bench.py",
        official_root / "configs" / "eval_protocols" / "gpt54.json",
        project / "pyproject.toml",
    )
    if not all(path.is_file() for path in required_sources):
        raise FileNotFoundError(
            "STATE-Bench scientific implementation source is missing"
        )
    loader_preflight = _run_official_loader_preflight(
        project_root=project,
        state_bench_root=root,
    )
    for output in (database, event_database, learning_manifest):
        output.parent.mkdir(parents=True, exist_ok=True)
    definitions: list[MemoryDefinition] = []
    opened_trajectory_ids: list[str] = []
    for unit in plan.learning_units:
        task_id = _task_id(unit)
        path = _trajectory_path(root, domain, task_id)
        if not path.is_file() or file_sha256(path) != unit.get("trajectory_sha256"):
            raise ValueError(f"STATE-Bench trajectory hash mismatch: {task_id}")
        trajectory = json.loads(path.read_text(encoding="utf-8"))
        definitions.append(
            extract_procedure_memory(
                unit=unit,
                trajectory=trajectory,
                domain=domain,
            )
        )
        opened_trajectory_ids.append(str(unit["unit_id"]))
    if set(opened_trajectory_ids) & set(plan.evaluation_unit_ids):
        raise RuntimeError("development evaluation trajectory leaked into learnings")
    with ScientificMemoryRuntime(
        database,
        mode=ScientificCandidateMode.CAUSAL,
    ) as runtime:
        for definition in definitions:
            runtime.register_memory(
                definition,
                namespace=f"state-bench-{domain}",
                actor="state-bench-development-learning-builder",
            )
        if runtime.event_log.validate_chain():
            raise RuntimeError("prepared STATE-Bench event chain is invalid")
        event_count = len(runtime.event_log.events)
        event_chain_head = runtime.event_log.events[-1].event_sha256
        production_memory_count = sum(
            state.production_eligible
            for state in (
                runtime.event_log.memory_state(memory_id)
                for memory_id in runtime.event_log.definitions()
            )
        )
    learning_payload = attach_artifact_integrity(
        {
            "schema": STATE_BENCH_LEARNING_MANIFEST_SCHEMA,
            "source_sha": source_sha,
            "protocol_digest": protocol_digest,
            "upstream_sha": STATE_BENCH_REVISION,
            "domain": domain,
            "phase": "bounded-development",
            "learning_unit_ids": list(plan.learning_unit_ids),
            "excluded_evaluation_unit_ids": list(plan.evaluation_unit_ids),
            "memories": [_definition_payload(definition) for definition in definitions],
            "all_memories_unverified_candidates": True,
            "production_memory_count": production_memory_count,
        }
    )
    learning_manifest.write_text(
        json.dumps(learning_payload, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    credential_names = [
        name for name in STATE_BENCH_REQUIRED_CREDENTIAL_ENV if environment.get(name)
    ]
    evaluator_configuration_present = all(
        environment.get(name)
        for name in ("STATE_BENCH_EVAL_ENDPOINT", "STATE_BENCH_EVAL_DEPLOYMENTS")
    )
    agent_configuration_present = (
        environment.get("STATE_BENCH_AGENT_PROVIDER") == "openai"
        and environment.get("STATE_BENCH_AGENT_MODEL") == STATE_BENCH_AGENT_MODEL
        and bool(
            environment.get("STATE_BENCH_AGENT_API_KEY")
            or environment.get("OPENAI_API_KEY")
        )
    )
    execution_configuration_present = bool(
        evaluator_configuration_present and agent_configuration_present
    )
    task_ids = [_task_id(unit) for unit in plan.evaluation_units]
    uv_executable = str(loader_preflight["argv"][0])
    common_runner_args = [
        uv_executable,
        "run",
        "--project",
        str(root),
        "--with-editable",
        str(project),
        "python",
        "-m",
        "state_bench.scripts.run_batch",
        "--domain",
        domain,
        "--tasks",
        ",".join(task_ids),
        "--agent-model-name",
        STATE_BENCH_AGENT_MODEL,
        "--num-runs",
        str(STATE_BENCH_BOUNDED_DEV_RUNS),
        "--retrieve-learnings-top-k",
        str(STATE_BENCH_RETRIEVAL_TOP_K),
        "--num-workers",
        "1",
    ]
    payload = {
        "schema": STATE_BENCH_PREPARED_DEV_SCHEMA,
        "status": (
            "prepared_configuration_detected_not_executed"
            if execution_configuration_present
            else "prepared_waiting_for_credentials"
        ),
        "phase": "bounded-development-preparation",
        "admission_eligible": False,
        "source_sha": source_sha,
        "protocol_digest": protocol_digest,
        "official_upstream": {
            "repository": "microsoft/STATE-Bench",
            "sha": STATE_BENCH_REVISION,
            "run_batch_sha256": file_sha256(official_root / "scripts" / "run_batch.py"),
            "agent_hook_sha256": file_sha256(
                official_root / "agents" / "state_bench.py"
            ),
            "eval_protocol_sha256": file_sha256(
                official_root / "configs" / "eval_protocols" / "gpt54.json"
            ),
            "upstream_modified": False,
        },
        "implementation": {
            "agent_path": str(agent_path),
            "agent_sha256": file_sha256(agent_path),
            "preparation_path": str(preparation_path),
            "preparation_sha256": file_sha256(preparation_path),
            "official_loader_preflight": loader_preflight,
            "dependency_lock": {
                "state_bench_uv_lock_sha256": file_sha256(root / "uv.lock"),
                "state_bench_pyproject_sha256": file_sha256(root / "pyproject.toml"),
                "wavemind_pyproject_sha256": file_sha256(project / "pyproject.toml"),
            },
        },
        "development_plan": {
            "domain": domain,
            "seed": seed,
            "learning_unit_ids": list(plan.learning_unit_ids),
            "evaluation_unit_ids": list(plan.evaluation_unit_ids),
            "learning_and_evaluation_disjoint": True,
            "validation_units_touched": False,
            "final_units_touched": False,
            "evaluation_trajectory_content_touched": False,
        },
        "candidate": {
            "id": ScientificCandidateMode.CAUSAL.value,
            "retrieval_top_k": STATE_BENCH_RETRIEVAL_TOP_K,
            "retrieval_token_budget": STATE_BENCH_RETRIEVAL_TOKEN_BUDGET,
            "evaluation_mode": "paired shadow treatment versus no-memory control",
            "production_influence_before_verified_pairs": False,
            "memory_count": len(definitions),
            "production_memory_count": production_memory_count,
            "event_count": event_count,
            "event_chain_head_sha256": event_chain_head,
        },
        "paired_execution": {
            "working_directory": str(project),
            "agent_model": STATE_BENCH_AGENT_MODEL,
            "run_count": STATE_BENCH_BOUNDED_DEV_RUNS,
            "case_order": task_ids,
            "common_prompt_and_retrieval_tool": True,
            "control_agent_class": "ScientificStateBenchNoMemoryControlAgent",
            "treatment_agent_class": "ScientificStateBenchAgent",
            "control_argv_template": [
                *common_runner_args,
                "--agent-class",
                "ScientificStateBenchNoMemoryControlAgent",
                "--output-dir",
                "{CONTROL_OUTPUT_DIR}",
            ],
            "treatment_argv_template": [
                *common_runner_args,
                "--agent-class",
                "ScientificStateBenchAgent",
                "--output-dir",
                "{TREATMENT_OUTPUT_DIR}",
            ],
            "treatment_environment": {
                "WAVEMIND_STATE_BENCH_SCIENTIFIC_DB": str(database),
                "WAVEMIND_STATE_BENCH_PHASE": "bounded-development-shadow",
                "WAVEMIND_STATE_BENCH_DOMAIN": domain,
                "STATE_BENCH_AGENT_PROVIDER": "openai",
                "STATE_BENCH_AGENT_MODEL": STATE_BENCH_AGENT_MODEL,
            },
            "output_placeholders_require_distinct_retained_directories": True,
        },
        "controls": {
            "seed": seed,
            "agent_model": STATE_BENCH_AGENT_MODEL,
            "agent_reasoning_effort": None,
            "retrieval_top_k": STATE_BENCH_RETRIEVAL_TOP_K,
            "retrieval_token_budget": STATE_BENCH_RETRIEVAL_TOKEN_BUDGET,
            "common_system_prompt_and_retrieval_tool": True,
            "official_task_order": task_ids,
            "hardware_inventory": hardware_inventory(),
        },
        "prepared_store": {
            "database_path": str(database),
            "database_sha256": file_sha256(database),
            "event_database_path": str(event_database),
            "event_database_sha256": file_sha256(event_database),
            "learning_manifest_path": str(learning_manifest),
            "learning_manifest_sha256": file_sha256(learning_manifest),
        },
        "credentials": {
            "present_environment_variable_names": credential_names,
            "secret_values_recorded": False,
            "locked_evaluator_configuration_present": bool(
                evaluator_configuration_present
            ),
            "frozen_agent_configuration_present": bool(agent_configuration_present),
            "official_execution_configuration_present": (
                execution_configuration_present
            ),
            "official_execution_succeeded": False,
        },
        "claim_boundary": (
            "Prepared bounded-development store only. No STATE-Bench task, "
            "simulator, judge, validation, or final run was executed."
        ),
    }
    return attach_artifact_integrity(payload)


def validate_prepared_state_bench_artifact(
    payload: Mapping[str, Any],
) -> list[str]:
    errors = validate_artifact_integrity(payload)
    if payload.get("schema") != STATE_BENCH_PREPARED_DEV_SCHEMA:
        errors.append("prepared STATE-Bench schema is invalid")
    official = payload.get("official_upstream")
    if not isinstance(official, Mapping) or official.get("sha") != STATE_BENCH_REVISION:
        errors.append("prepared STATE-Bench upstream SHA is invalid")
    implementation = payload.get("implementation")
    if not isinstance(implementation, Mapping) or not implementation.get(
        "official_loader_preflight", {}
    ).get("both_agent_classes_loaded"):
        errors.append("official STATE-Bench agent loader preflight did not pass")
    plan = payload.get("development_plan")
    if not isinstance(plan, Mapping):
        errors.append("prepared STATE-Bench development plan is missing")
        return errors
    learning = set(plan.get("learning_unit_ids") or [])
    evaluation = set(plan.get("evaluation_unit_ids") or [])
    if not learning or not evaluation or learning & evaluation:
        errors.append("prepared STATE-Bench learning/evaluation split is invalid")
    if len(learning) != 77 or len(evaluation) != 3:
        errors.append("prepared STATE-Bench bounded development counts are invalid")
    if plan.get("validation_units_touched") is not False:
        errors.append("STATE-Bench validation units were touched")
    if plan.get("final_units_touched") is not False:
        errors.append("STATE-Bench final units were touched")
    if plan.get("evaluation_trajectory_content_touched") is not False:
        errors.append("STATE-Bench development evaluation content was touched")
    candidate = payload.get("candidate")
    if not isinstance(candidate, Mapping):
        errors.append("prepared STATE-Bench candidate metadata is missing")
    elif candidate.get("production_memory_count") != 0:
        errors.append("unverified STATE-Bench memories gained production influence")
    elif candidate.get("retrieval_top_k") != STATE_BENCH_RETRIEVAL_TOP_K:
        errors.append("prepared STATE-Bench retrieval top_k is not frozen")
    paired = payload.get("paired_execution")
    if not isinstance(paired, Mapping):
        errors.append("prepared STATE-Bench paired execution is missing")
    elif paired.get("run_count") != STATE_BENCH_BOUNDED_DEV_RUNS:
        errors.append("prepared STATE-Bench run count is not frozen")
    elif paired.get("case_order") != [
        str(unit_id).split(":", 2)[-1]
        for unit_id in plan.get("evaluation_unit_ids") or []
    ]:
        errors.append("prepared STATE-Bench case order does not match split")
    controls = payload.get("controls")
    if not isinstance(controls, Mapping):
        errors.append("prepared STATE-Bench common controls are missing")
    elif controls.get("agent_model") != STATE_BENCH_AGENT_MODEL:
        errors.append("prepared STATE-Bench agent model is not frozen")
    elif controls.get("hardware_inventory") in (None, {}):
        errors.append("prepared STATE-Bench hardware inventory is missing")
    credentials = payload.get("credentials")
    if (
        not isinstance(credentials, Mapping)
        or credentials.get("secret_values_recorded") is not False
    ):
        errors.append("STATE-Bench credential provenance is unsafe")
    return errors
