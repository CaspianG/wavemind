from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
import statistics
import subprocess
import sys
import tempfile
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Sequence

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from wavemind import (
    ExperienceCompiler,
    ExperienceStatus,
    ExperiencedWorkAgent,
    HashingTextEncoder,
    MemoryFirewall,
    MemoryFirewallPolicy,
    SQLiteExperienceStore,
    ToolExecution,
    WaveMind,
    WorkRequest,
)


SCHEMA = "wavemind.experienced_work_agent_benchmark.v1"
DATASET_REVISION = "experienced-work-agent-v1-frozen-20260728"
NAMESPACE = "experienced-work-agent"
TRAIN_PER_SCENARIO = 10
HELD_OUT_PER_SCENARIO = 5
LATENCY_REPETITIONS = 7


@dataclass(frozen=True)
class Scenario:
    id: str
    domain: str
    task_type: str
    training_objective: str
    held_out_objectives: tuple[str, ...]
    fallback_plan: tuple[str, ...]
    verified_plan: tuple[str, ...]
    runtime: Callable[[], "ScenarioRuntime"]


class ScenarioRuntime:
    available_tools: tuple[str, ...]

    def call(self, name: str) -> ToolExecution:
        started = time.perf_counter()
        try:
            success, output, error_code = self._call(name)
        except Exception as exc:
            success = False
            output = {"error": f"{type(exc).__name__}: {exc}"}
            error_code = "tool_exception"
        return ToolExecution(
            name=name,
            success=bool(success),
            output=dict(output),
            error_code=error_code,
            duration_ms=(time.perf_counter() - started) * 1000.0,
        )

    def _call(self, name: str) -> tuple[bool, dict[str, Any], str | None]:
        raise NotImplementedError

    def verify(self) -> bool:
        raise NotImplementedError

    def close(self) -> None:
        pass


class CodingRuntime(ScenarioRuntime):
    def __init__(self, mode: str):
        self.mode = mode
        self._tmp = tempfile.TemporaryDirectory(prefix="wavemind-work-coding-")
        self.path = Path(self._tmp.name) / "project.json"
        if mode == "safe_config":
            self.available_tools = (
                "overwrite_config",
                "run_config_tests",
                "inspect_config",
                "update_config",
            )
            self.path.write_text(
                json.dumps(
                    {"service": "api", "timeout": 30, "retries": 1},
                    sort_keys=True,
                ),
                encoding="utf-8",
            )
        else:
            self.available_tools = (
                "replace_schema",
                "run_schema_tests",
                "inspect_schema",
                "migrate_schema",
            )
            self.path.write_text(
                json.dumps(
                    {
                        "version": 1,
                        "fields": ["id", "name", "legacy_reference"],
                    },
                    sort_keys=True,
                ),
                encoding="utf-8",
            )
        self.inspected = False

    def _read(self) -> dict[str, Any]:
        return json.loads(self.path.read_text(encoding="utf-8"))

    def _write(self, value: dict[str, Any]) -> None:
        self.path.write_text(json.dumps(value, sort_keys=True), encoding="utf-8")

    def _call(self, name: str) -> tuple[bool, dict[str, Any], str | None]:
        if name in {"inspect_config", "inspect_schema"}:
            self.inspected = True
            return True, {"document": self._read()}, None
        if name == "overwrite_config":
            self._write({"retries": 3})
            return True, {"written": True}, None
        if name == "update_config":
            value = self._read()
            if not self.inspected:
                return False, value, "config_not_inspected"
            value["retries"] = 3
            self._write(value)
            return True, value, None
        if name == "run_config_tests":
            success = self.verify()
            return success, {"passed": success}, None if success else "config_keys_lost"
        if name == "replace_schema":
            self._write({"version": 2, "fields": ["id", "display_name"]})
            return True, {"written": True}, None
        if name == "migrate_schema":
            value = self._read()
            if not self.inspected:
                return False, value, "schema_not_inspected"
            value["version"] = 2
            fields = list(value.get("fields") or [])
            if "display_name" not in fields:
                fields.append("display_name")
            value["fields"] = fields
            self._write(value)
            return True, value, None
        if name == "run_schema_tests":
            success = self.verify()
            return success, {"passed": success}, None if success else "schema_field_lost"
        raise KeyError(name)

    def verify(self) -> bool:
        value = self._read()
        if self.mode == "safe_config":
            return (
                value.get("service") == "api"
                and value.get("timeout") == 30
                and value.get("retries") == 3
            )
        fields = set(value.get("fields") or [])
        return (
            value.get("version") == 2
            and "legacy_reference" in fields
            and "display_name" in fields
        )

    def close(self) -> None:
        self._tmp.cleanup()


class SupportRuntime(ScenarioRuntime):
    def __init__(self, mode: str):
        self.mode = mode
        self._tmp = tempfile.TemporaryDirectory(prefix="wavemind-work-support-")
        self.conn = sqlite3.connect(Path(self._tmp.name) / "crm.db")
        self.looked_up = False
        self.verified = False
        self.notified = False
        if mode == "identity_update":
            self.available_tools = (
                "update_customer",
                "verify_identity",
                "confirm_update",
                "lookup_customer",
            )
            self.conn.execute(
                """
                CREATE TABLE customer (
                    id INTEGER PRIMARY KEY, email TEXT, verified INTEGER
                )
                """
            )
            self.conn.execute(
                "INSERT INTO customer VALUES (1, 'old@example.test', 0)"
            )
        else:
            self.available_tools = (
                "close_case",
                "search_duplicates",
                "merge_cases",
                "notify_customer",
            )
            self.conn.execute(
                """
                CREATE TABLE cases (
                    id INTEGER PRIMARY KEY, status TEXT, merged_into INTEGER
                )
                """
            )
            self.conn.executemany(
                "INSERT INTO cases VALUES (?, 'open', NULL)",
                [(1,), (2,)],
            )
        self.conn.commit()

    def _call(self, name: str) -> tuple[bool, dict[str, Any], str | None]:
        if name == "lookup_customer":
            self.looked_up = True
            return True, {"customer_id": 1}, None
        if name == "verify_identity":
            if not self.looked_up:
                return False, {}, "identity_lookup_missing"
            self.verified = True
            self.conn.execute("UPDATE customer SET verified = 1 WHERE id = 1")
            self.conn.commit()
            return True, {"verified": True}, None
        if name == "update_customer":
            if not self.verified:
                return False, {}, "identity_not_verified"
            self.conn.execute(
                "UPDATE customer SET email = 'new@example.test' WHERE id = 1"
            )
            self.conn.commit()
            return True, {"updated": True}, None
        if name == "confirm_update":
            success = self.verify()
            return success, {"confirmed": success}, None if success else "update_missing"
        if name == "close_case":
            self.conn.execute("UPDATE cases SET status = 'closed' WHERE id = 1")
            self.conn.commit()
            return True, {"closed": 1}, None
        if name == "search_duplicates":
            rows = self.conn.execute(
                "SELECT id FROM cases ORDER BY id"
            ).fetchall()
            return True, {"case_ids": [row[0] for row in rows]}, None
        if name == "merge_cases":
            rows = self.conn.execute(
                "SELECT id, status FROM cases ORDER BY id"
            ).fetchall()
            if len(rows) != 2 or any(row[1] != "open" for row in rows):
                return False, {}, "case_closed_before_merge"
            self.conn.execute(
                "UPDATE cases SET status = 'merged', merged_into = 1 WHERE id = 2"
            )
            self.conn.commit()
            return True, {"merged": 2, "into": 1}, None
        if name == "notify_customer":
            merged = self.conn.execute(
                "SELECT merged_into FROM cases WHERE id = 2"
            ).fetchone()
            if not merged or merged[0] != 1:
                return False, {}, "merge_not_completed"
            self.notified = True
            return True, {"notified": True}, None
        raise KeyError(name)

    def verify(self) -> bool:
        if self.mode == "identity_update":
            row = self.conn.execute(
                "SELECT email, verified FROM customer WHERE id = 1"
            ).fetchone()
            return bool(row and row[0] == "new@example.test" and row[1] == 1)
        row = self.conn.execute(
            "SELECT status, merged_into FROM cases WHERE id = 2"
        ).fetchone()
        return bool(row and row[0] == "merged" and row[1] == 1 and self.notified)

    def close(self) -> None:
        self.conn.close()
        self._tmp.cleanup()


class EnterpriseRuntime(ScenarioRuntime):
    def __init__(self, mode: str):
        self.mode = mode
        self._tmp = tempfile.TemporaryDirectory(prefix="wavemind-work-enterprise-")
        self.conn = sqlite3.connect(Path(self._tmp.name) / "workflow.db")
        self.inspected = False
        if mode == "approval_chain":
            self.available_tools = (
                "execute_request",
                "inspect_policy",
                "collect_approval",
                "audit_request",
            )
            self.conn.execute(
                """
                CREATE TABLE request (
                    id INTEGER PRIMARY KEY, approved INTEGER, executed INTEGER
                )
                """
            )
            self.conn.execute("INSERT INTO request VALUES (1, 0, 0)")
        else:
            self.available_tools = (
                "apply_unchecked",
                "apply_once",
                "inspect_status",
                "reconcile_ledger",
            )
            self.conn.execute(
                """
                CREATE TABLE ledger (
                    id INTEGER PRIMARY KEY AUTOINCREMENT, operation_key TEXT
                )
                """
            )
        self.conn.commit()

    def _call(self, name: str) -> tuple[bool, dict[str, Any], str | None]:
        if name in {"inspect_policy", "inspect_status"}:
            self.inspected = True
            return True, {"inspected": True}, None
        if name == "collect_approval":
            if not self.inspected:
                return False, {}, "policy_not_inspected"
            self.conn.execute("UPDATE request SET approved = 1 WHERE id = 1")
            self.conn.commit()
            return True, {"approved": True}, None
        if name == "execute_request":
            row = self.conn.execute(
                "SELECT approved FROM request WHERE id = 1"
            ).fetchone()
            if not self.inspected or not row or row[0] != 1:
                return False, {}, "approval_missing"
            self.conn.execute("UPDATE request SET executed = 1 WHERE id = 1")
            self.conn.commit()
            return True, {"executed": True}, None
        if name == "audit_request":
            success = self.verify()
            return success, {"audited": success}, None if success else "execution_missing"
        if name == "apply_unchecked":
            self.conn.execute(
                "INSERT INTO ledger(operation_key) VALUES ('invoice-7')"
            )
            self.conn.commit()
            return True, {"applied": True}, None
        if name == "apply_once":
            if not self.inspected:
                return False, {}, "ledger_not_inspected"
            count = self.conn.execute(
                "SELECT COUNT(*) FROM ledger WHERE operation_key = 'invoice-7'"
            ).fetchone()[0]
            if count:
                return False, {"existing": count}, "duplicate_operation"
            self.conn.execute(
                "INSERT INTO ledger(operation_key) VALUES ('invoice-7')"
            )
            self.conn.commit()
            return True, {"applied": True}, None
        if name == "reconcile_ledger":
            count = self.conn.execute(
                "SELECT COUNT(*) FROM ledger WHERE operation_key = 'invoice-7'"
            ).fetchone()[0]
            success = count == 1
            return success, {"count": count}, None if success else "duplicate_ledger_entry"
        raise KeyError(name)

    def verify(self) -> bool:
        if self.mode == "approval_chain":
            row = self.conn.execute(
                "SELECT approved, executed FROM request WHERE id = 1"
            ).fetchone()
            return bool(row and row[0] == 1 and row[1] == 1)
        count = self.conn.execute(
            "SELECT COUNT(*) FROM ledger WHERE operation_key = 'invoice-7'"
        ).fetchone()[0]
        return count == 1

    def close(self) -> None:
        self.conn.close()
        self._tmp.cleanup()


SCENARIOS = (
    Scenario(
        id="coding-config",
        domain="coding_repository",
        task_type="safe_config_change",
        training_objective="Change a repository configuration without dropping keys.",
        held_out_objectives=(
            "Raise retry attempts while preserving every existing service setting.",
            "Modify the retry policy without replacing unrelated configuration.",
            "Patch a project setting and keep the current timeout and service name.",
            "Safely adjust resilience settings in the repository configuration.",
            "Update retry behavior without damaging the rest of the config file.",
        ),
        fallback_plan=(
            "overwrite_config",
            "run_config_tests",
            "inspect_config",
            "update_config",
        ),
        verified_plan=("inspect_config", "update_config", "run_config_tests"),
        runtime=lambda: CodingRuntime("safe_config"),
    ),
    Scenario(
        id="coding-schema",
        domain="coding_repository",
        task_type="compatible_schema_migration",
        training_objective="Migrate a repository schema while preserving legacy fields.",
        held_out_objectives=(
            "Upgrade the project schema without losing backward-compatible data.",
            "Introduce display names while retaining old reference fields.",
            "Move the schema to its next version and preserve compatibility.",
            "Apply a non-destructive schema upgrade to the repository.",
            "Modernize stored fields without dropping legacy references.",
        ),
        fallback_plan=(
            "replace_schema",
            "run_schema_tests",
            "inspect_schema",
            "migrate_schema",
        ),
        verified_plan=("inspect_schema", "migrate_schema", "run_schema_tests"),
        runtime=lambda: CodingRuntime("schema_migration"),
    ),
    Scenario(
        id="support-identity",
        domain="support_crm",
        task_type="verified_customer_update",
        training_objective="Verify customer identity before changing CRM contact data.",
        held_out_objectives=(
            "Change the account email after validating the caller.",
            "Handle a contact detail correction with identity checks.",
            "Update customer information without bypassing verification.",
            "Process a caller-requested email change safely.",
            "Correct CRM contact data only for the validated account owner.",
        ),
        fallback_plan=(
            "update_customer",
            "verify_identity",
            "confirm_update",
            "lookup_customer",
        ),
        verified_plan=("lookup_customer", "verify_identity", "update_customer"),
        runtime=lambda: SupportRuntime("identity_update"),
    ),
    Scenario(
        id="support-duplicate",
        domain="support_crm",
        task_type="duplicate_case_resolution",
        training_objective="Merge duplicate support cases before closing or notifying.",
        held_out_objectives=(
            "Resolve two tickets for the same incident without losing the active case.",
            "Consolidate duplicate customer cases and send one update.",
            "Handle repeated support tickets as a single continuing case.",
            "Merge an accidental duplicate before communicating resolution.",
            "Unify two open CRM cases and notify the customer.",
        ),
        fallback_plan=(
            "close_case",
            "search_duplicates",
            "merge_cases",
            "notify_customer",
        ),
        verified_plan=("search_duplicates", "merge_cases", "notify_customer"),
        runtime=lambda: SupportRuntime("duplicate_resolution"),
    ),
    Scenario(
        id="enterprise-approval",
        domain="enterprise_workflow",
        task_type="approval_gated_execution",
        training_objective="Inspect policy and collect approval before execution.",
        held_out_objectives=(
            "Run the business request only after its required authorization.",
            "Complete a controlled workflow without bypassing approval.",
            "Execute the pending request under the applicable policy gate.",
            "Process a regulated action after confirming authorization.",
            "Finish the enterprise request in the approved order.",
        ),
        fallback_plan=(
            "execute_request",
            "inspect_policy",
            "collect_approval",
            "audit_request",
        ),
        verified_plan=("inspect_policy", "collect_approval", "execute_request"),
        runtime=lambda: EnterpriseRuntime("approval_chain"),
    ),
    Scenario(
        id="enterprise-idempotency",
        domain="enterprise_workflow",
        task_type="idempotent_operation",
        training_objective="Inspect workflow state and apply an operation exactly once.",
        held_out_objectives=(
            "Retry the invoice workflow without duplicating the ledger action.",
            "Resume a business operation while guaranteeing one application.",
            "Safely repeat a workflow request with idempotent execution.",
            "Recover an interrupted operation without a duplicate side effect.",
            "Apply the pending enterprise action once and reconcile its state.",
        ),
        fallback_plan=(
            "apply_unchecked",
            "apply_unchecked",
            "inspect_status",
            "reconcile_ledger",
        ),
        verified_plan=("inspect_status", "apply_once", "reconcile_ledger"),
        runtime=lambda: EnterpriseRuntime("idempotent_operation"),
    ),
)


def build_split() -> tuple[list[tuple[Scenario, WorkRequest]], list[tuple[Scenario, WorkRequest]]]:
    training: list[tuple[Scenario, WorkRequest]] = []
    held_out: list[tuple[Scenario, WorkRequest]] = []
    for scenario in SCENARIOS:
        for index in range(TRAIN_PER_SCENARIO):
            demonstration = scenario.verified_plan if index >= 2 else ()
            training.append(
                (
                    scenario,
                    WorkRequest(
                        id=f"train-{scenario.id}-{index:02d}",
                        objective=f"{scenario.training_objective} Attempt {index + 1}.",
                        namespace=NAMESPACE,
                        domain=scenario.domain,
                        task_type=scenario.task_type,
                        fallback_plan=scenario.fallback_plan,
                        demonstration_plan=demonstration,
                    ),
                )
            )
        for index, objective in enumerate(scenario.held_out_objectives):
            held_out.append(
                (
                    scenario,
                    WorkRequest(
                        id=f"heldout-{scenario.id}-{index:02d}",
                        objective=objective,
                        namespace=NAMESPACE,
                        domain=scenario.domain,
                        task_type=scenario.task_type,
                        fallback_plan=scenario.fallback_plan,
                    ),
                )
            )
    return training, held_out


def split_fingerprint(
    training: Sequence[tuple[Scenario, WorkRequest]],
    held_out: Sequence[tuple[Scenario, WorkRequest]],
) -> str:
    payload = {
        "revision": DATASET_REVISION,
        "training": [_request_dict(request) for _, request in training],
        "held_out": [_request_dict(request) for _, request in held_out],
    }
    return hashlib.sha256(
        json.dumps(
            payload,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()


def _request_dict(request: WorkRequest) -> dict[str, Any]:
    payload = asdict(request)
    payload["fallback_plan"] = list(request.fallback_plan)
    payload["demonstration_plan"] = list(request.demonstration_plan)
    return payload


def _compiler(path: Path) -> tuple[SQLiteExperienceStore, ExperienceCompiler]:
    store = SQLiteExperienceStore(path)
    return store, ExperienceCompiler(
        store,
        MemoryFirewall(
            MemoryFirewallPolicy(
                namespace=NAMESPACE,
                policy_id="experienced-work-agent-benchmark",
            )
        ),
    )


def _train(
    agent: ExperiencedWorkAgent,
    training: Sequence[tuple[Scenario, WorkRequest]],
) -> tuple[set[str], list[dict[str, Any]]]:
    error_codes: set[str] = set()
    runs = []
    for scenario, request in training:
        runtime = scenario.runtime()
        try:
            run = agent.run(request, runtime, learn=True)
        finally:
            runtime.close()
        runs.append(run.as_dict())
        error_codes.update(
            item.error_code
            for item in run.executions
            if item.error_code is not None
        )
    return error_codes, runs


def _run_experience_case(
    agent: ExperiencedWorkAgent,
    scenario: Scenario,
    request: WorkRequest,
    known_errors: set[str],
) -> dict[str, Any]:
    runtime = scenario.runtime()
    try:
        run = agent.run(
            request,
            runtime,
            learn=False,
            known_error_codes=tuple(known_errors),
        )
    finally:
        runtime.close()
    row = run.as_dict()
    row["domain"] = scenario.domain
    row["task_type"] = scenario.task_type
    return row


def _run_plan(
    *,
    scenario: Scenario,
    request: WorkRequest,
    plan: Sequence[str],
    plan_source: str,
    context_tokens: int,
    known_errors: set[str],
    retrieval_started: float,
) -> dict[str, Any]:
    runtime = scenario.runtime()
    try:
        if not plan or any(name not in runtime.available_tools for name in plan):
            selected_plan = request.fallback_plan
            selected_source = "fallback"
        else:
            selected_plan = tuple(plan)
            selected_source = plan_source
        executions = tuple(runtime.call(name) for name in selected_plan)
        success = runtime.verify()
    finally:
        runtime.close()
    repeated = sorted(
        {
            item.error_code
            for item in executions
            if item.error_code is not None and item.error_code in known_errors
        }
    )
    return {
        "request_id": request.id,
        "success": success,
        "plan_source": selected_source,
        "plan": list(selected_plan),
        "tool_steps": len(executions),
        "context_tokens": context_tokens,
        "repeated_error_codes": repeated,
        "latency_ms": (time.perf_counter() - retrieval_started) * 1000.0,
        "domain": scenario.domain,
        "task_type": scenario.task_type,
    }


def _run_cold(
    held_out: Sequence[tuple[Scenario, WorkRequest]],
    known_errors: set[str],
) -> list[dict[str, Any]]:
    return [
        _run_plan(
            scenario=scenario,
            request=request,
            plan=request.fallback_plan,
            plan_source="fallback",
            context_tokens=0,
            known_errors=known_errors,
            retrieval_started=time.perf_counter(),
        )
        for scenario, request in held_out
    ]


def _core_from_experience(store: SQLiteExperienceStore, path: Path) -> WaveMind:
    core = WaveMind(
        db_path=path,
        encoder=HashingTextEncoder(vector_dim=384),
        score_threshold=0.0,
    )
    for record in store.list(
        namespace=NAMESPACE,
        status=ExperienceStatus.ACTIVE,
        limit=100,
    ):
        core.remember(
            f"{record.title}. {record.content}",
            namespace=NAMESPACE,
            metadata={
                "tool_plan": record.metadata.get("tool_plan"),
                "task_type": list(record.applicability.task_types),
            },
        )
    return core


def _estimate_tokens(text: str) -> int:
    return max(1, int(len(text.split()) * 1.25 + 0.999))


def _run_core_case(
    core: WaveMind,
    scenario: Scenario,
    request: WorkRequest,
    known_errors: set[str],
) -> dict[str, Any]:
    started = time.perf_counter()
    results = core.query(
        request.objective,
        namespace=NAMESPACE,
        top_k=3,
        min_score=0.0,
    )
    plan = ()
    if results:
        raw_plan = results[0].metadata.get("tool_plan")
        if isinstance(raw_plan, list):
            plan = tuple(str(name) for name in raw_plan)
    return _run_plan(
        scenario=scenario,
        request=request,
        plan=plan,
        plan_source="wavemind_core",
        context_tokens=sum(_estimate_tokens(item.text) for item in results),
        known_errors=known_errors,
        retrieval_started=started,
    )


def _median_latency_row(samples: Sequence[dict[str, Any]]) -> dict[str, Any]:
    if not samples:
        raise ValueError("latency samples must not be empty")
    latencies = [float(row["latency_ms"]) for row in samples]
    row = dict(samples[0])
    row["latency_ms"] = statistics.median(latencies)
    row["latency_samples_ms"] = latencies
    return row


def _paired_latency_regression(
    baseline_samples: Sequence[dict[str, Any]],
    experience_samples: Sequence[dict[str, Any]],
) -> tuple[float, list[float]]:
    if len(baseline_samples) != len(experience_samples) or not baseline_samples:
        raise ValueError("paired latency samples must be non-empty and balanced")
    regressions = []
    for baseline, experience in zip(baseline_samples, experience_samples, strict=True):
        baseline_latency = float(baseline["latency_ms"])
        if baseline_latency <= 0:
            raise ValueError("baseline latency samples must be positive")
        regressions.append(
            float(experience["latency_ms"]) / baseline_latency - 1.0
        )
    return statistics.median(regressions), regressions


def _run_paired(
    *,
    core: WaveMind,
    agent: ExperiencedWorkAgent,
    held_out: Sequence[tuple[Scenario, WorkRequest]],
    known_errors: set[str],
    repetitions: int = LATENCY_REPETITIONS,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    if repetitions < 1:
        raise ValueError("repetitions must be >= 1")
    core_rows: list[dict[str, Any]] = []
    experience_rows: list[dict[str, Any]] = []
    for case_index, (scenario, request) in enumerate(held_out):
        core_samples: list[dict[str, Any]] = []
        experience_samples: list[dict[str, Any]] = []
        for repetition in range(repetitions):
            core_first = (case_index + repetition) % 2 == 0
            if core_first:
                core_samples.append(
                    _run_core_case(core, scenario, request, known_errors)
                )
                experience_samples.append(
                    _run_experience_case(
                        agent,
                        scenario,
                        request,
                        known_errors,
                    )
                )
            else:
                experience_samples.append(
                    _run_experience_case(
                        agent,
                        scenario,
                        request,
                        known_errors,
                    )
                )
                core_samples.append(
                    _run_core_case(core, scenario, request, known_errors)
                )
        core_row = _median_latency_row(core_samples)
        experience_row = _median_latency_row(experience_samples)
        paired_regression, paired_samples = _paired_latency_regression(
            core_samples,
            experience_samples,
        )
        experience_row["paired_latency_regression"] = paired_regression
        experience_row["paired_latency_regression_samples"] = paired_samples
        core_rows.append(core_row)
        experience_rows.append(experience_row)
    return core_rows, experience_rows


def _p95(values: Sequence[float]) -> float:
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, int(len(ordered) * 0.95))]


def _metrics(engine: str, rows: Sequence[dict[str, Any]]) -> dict[str, Any]:
    success = [bool(row["success"]) for row in rows]
    repeated = [bool(row["repeated_error_codes"]) for row in rows]
    domains = sorted({str(row["domain"]) for row in rows})
    return {
        "engine": engine,
        "task_success_rate": sum(success) / len(rows),
        "repeated_error_rate": sum(repeated) / len(rows),
        "median_tool_steps": statistics.median(
            int(row["tool_steps"]) for row in rows
        ),
        "median_context_tokens": statistics.median(
            int(row["context_tokens"]) for row in rows
        ),
        "p95_latency_ms": _p95([float(row["latency_ms"]) for row in rows]),
        "domain_success": {
            domain: sum(
                bool(row["success"]) for row in rows if row["domain"] == domain
            )
            / sum(1 for row in rows if row["domain"] == domain)
            for domain in domains
        },
        "case_count": len(rows),
    }


def _relative_reduction(baseline: float, value: float) -> float:
    if baseline <= 0:
        return 0.0 if value <= 0 else -1.0
    return (baseline - value) / baseline


def _check(
    check_id: str,
    passed: bool,
    evidence: Any,
    target: Any,
) -> dict[str, Any]:
    return {
        "id": check_id,
        "passed": bool(passed),
        "evidence": evidence,
        "target": target,
    }


def run_benchmark(workdir: Path) -> dict[str, Any]:
    training, held_out = build_split()
    fingerprint = split_fingerprint(training, held_out)
    workdir.mkdir(parents=True, exist_ok=True)
    store, compiler = _compiler(workdir / "experience.db")
    agent = ExperiencedWorkAgent(compiler)
    core: WaveMind | None = None
    try:
        known_errors, training_runs = _train(agent, training)
        core = _core_from_experience(store, workdir / "core.db")
        cold_rows = _run_cold(held_out, known_errors)
        core_rows, experience_rows = _run_paired(
            core=core,
            agent=agent,
            held_out=held_out,
            known_errors=known_errors,
        )
        results = [
            _metrics("Cold work agent", cold_rows),
            _metrics("WaveMind Core", core_rows),
            _metrics("WaveMind Experience", experience_rows),
        ]
        by_engine = {row["engine"]: row for row in results}
        baseline = by_engine["WaveMind Core"]
        experience = by_engine["WaveMind Experience"]
        success_uplift = (
            experience["task_success_rate"] - baseline["task_success_rate"]
        )
        error_reduction = _relative_reduction(
            baseline["repeated_error_rate"],
            experience["repeated_error_rate"],
        )
        step_reduction = _relative_reduction(
            baseline["median_tool_steps"],
            experience["median_tool_steps"],
        )
        context_reduction = _relative_reduction(
            baseline["median_context_tokens"],
            experience["median_context_tokens"],
        )
        latency_regression = _p95(
            [
                float(row["paired_latency_regression"])
                for row in experience_rows
            ]
        )
        checks = [
            _check("training-count", len(training) == 60, len(training), 60),
            _check("held-out-count", len(held_out) == 30, len(held_out), 30),
            _check(
                "held-out-domain-balance",
                all(
                    sum(1 for scenario, _ in held_out if scenario.domain == domain)
                    == 10
                    for domain in {
                        "coding_repository",
                        "support_crm",
                        "enterprise_workflow",
                    }
                ),
                {
                    domain: sum(
                        1 for scenario, _ in held_out if scenario.domain == domain
                    )
                    for domain in {
                        "coding_repository",
                        "support_crm",
                        "enterprise_workflow",
                    }
                },
                "10 per domain",
            ),
            _check(
                "task-success-uplift",
                success_uplift >= 0.15,
                success_uplift,
                ">= 0.15 absolute over WaveMind Core",
            ),
            _check(
                "repeated-error-reduction",
                error_reduction >= 0.50,
                error_reduction,
                ">= 0.50 relative",
            ),
            _check(
                "tool-step-reduction",
                step_reduction >= 0.25,
                step_reduction,
                ">= 0.25 relative",
            ),
            _check(
                "context-token-reduction",
                context_reduction >= 0.35,
                context_reduction,
                ">= 0.35 relative",
            ),
            _check(
                "p95-latency",
                latency_regression <= 0.20,
                latency_regression,
                "<= 0.20 relative",
            ),
        ]
        source_sha = _source_sha()
        return {
            "schema": SCHEMA,
            "status": "pass" if all(item["passed"] for item in checks) else "fail",
            "generated_at": _utc_now(),
            "source_sha": source_sha,
            "dataset": {
                "revision": DATASET_REVISION,
                "fingerprint_sha256": fingerprint,
                "training_trajectories": len(training),
                "held_out_tasks": len(held_out),
                "held_out_ids": [request.id for _, request in held_out],
                "split_frozen_before_training": True,
                "metadata_leakage": False,
            },
            "protocol": {
                "same_held_out_tasks": True,
                "same_runtime_verifiers": True,
                "same_tool_implementations": True,
                "no_paid_api": True,
                "experience_promotion_gates": True,
                "core_top_k": 3,
                "paired_latency_samples": True,
                "paired_latency_regression_estimator": (
                    "p95 of per-case median paired relative regressions"
                ),
                "latency_repetitions_per_case": LATENCY_REPETITIONS,
            },
            "training": {
                "successful": sum(bool(row["success"]) for row in training_runs),
                "failed": sum(not bool(row["success"]) for row in training_runs),
                "known_error_codes": sorted(known_errors),
                "active_strategies": len(
                    store.list(
                        namespace=NAMESPACE,
                        status=ExperienceStatus.ACTIVE,
                        limit=100,
                    )
                ),
            },
            "results": results,
            "uplift": {
                "task_success_absolute": success_uplift,
                "repeated_error_relative_reduction": error_reduction,
                "tool_step_relative_reduction": step_reduction,
                "context_token_relative_reduction": context_reduction,
                "p95_latency_regression": latency_regression,
            },
            "checks": checks,
            "held_out_results": {
                "cold": cold_rows,
                "core": core_rows,
                "experience": experience_rows,
            },
        }
    finally:
        if core is not None:
            core.close()
        store.close()


def _source_sha() -> str:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "HEAD"],
            cwd=PROJECT_ROOT,
            text=True,
            encoding="utf-8",
            stderr=subprocess.DEVNULL,
        ).strip()
    except Exception:
        return "unknown"


def _utc_now() -> str:
    return (
        datetime.now(timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )


def render_markdown(payload: dict[str, Any]) -> str:
    lines = [
        "# Experienced Work Agent",
        "",
        f"Status: `{payload['status']}`",
        "",
        (
            f"Dataset `{payload['dataset']['revision']}`: "
            f"{payload['dataset']['training_trajectories']} training trajectories, "
            f"{payload['dataset']['held_out_tasks']} frozen held-out tasks."
        ),
        "",
        "| engine | success | repeated error | median steps | median context | p95 |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for row in payload["results"]:
        lines.append(
            f"| {row['engine']} | {row['task_success_rate']:.1%} | "
            f"{row['repeated_error_rate']:.1%} | {row['median_tool_steps']:.1f} | "
            f"{row['median_context_tokens']:.1f} | {row['p95_latency_ms']:.2f} ms |"
        )
    lines.extend(["", "## Admission checks", ""])
    for check in payload["checks"]:
        mark = "pass" if check["passed"] else "fail"
        lines.append(
            f"- `{mark}` {check['id']}: {check['evidence']} "
            f"(target: {check['target']})"
        )
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("benchmarks/experienced_work_agent_results.json"),
    )
    parser.add_argument(
        "--markdown",
        type=Path,
        default=Path("benchmarks/EXPERIENCED_WORK_AGENT.md"),
    )
    parser.add_argument("--workdir", type=Path)
    args = parser.parse_args()
    if args.workdir is not None:
        payload = run_benchmark(args.workdir)
    else:
        with tempfile.TemporaryDirectory(prefix="wavemind-work-agent-benchmark-") as tmp:
            payload = run_benchmark(Path(tmp))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    args.markdown.parent.mkdir(parents=True, exist_ok=True)
    args.markdown.write_text(render_markdown(payload), encoding="utf-8")
    print(json.dumps(payload["uplift"], indent=2))
    return 0 if payload["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
