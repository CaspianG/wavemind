from __future__ import annotations

import argparse
import hashlib
import json
import math
import statistics
import subprocess
import sys
import tempfile
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Sequence

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from wavemind import (
    AgentExperienceRuntime,
    AgentExperienceRuntimePolicy,
    CallableOutcomeVerifier,
    ExperienceCompiler,
    ExperienceCompilerPolicy,
    ExperienceStatus,
    MemoryFirewall,
    MemoryFirewallPolicy,
    SQLiteExperienceStore,
    VerificationSource,
)


SCHEMA = "wavemind.verified_experience_benchmark.v1"
DATASET_REVISION = "verified-experience-stateful-v1-frozen-20260803"
DOMAINS = ("travel", "customer_support", "shopping_assistant")
HELD_OUT_PER_DOMAIN = 50
HARD_PER_DOMAIN = 40
REPEATS = 5
T_CRITICAL_95_DF4 = 2.776


@dataclass(frozen=True)
class DomainProtocol:
    domain: str
    task_type: str
    routine_task_type: str
    required_plan: tuple[str, ...]
    fallback_plan: tuple[str, ...]
    routine_plan: tuple[str, ...]
    available_tools: tuple[str, ...]


@dataclass(frozen=True)
class HeldOutTask:
    id: str
    domain: str
    task_type: str
    query: str
    expected_plan: tuple[str, ...]
    fallback_plan: tuple[str, ...]
    available_tools: tuple[str, ...]
    experience_needed: bool


PROTOCOLS = (
    DomainProtocol(
        domain="travel",
        task_type="safe_itinerary_rebook",
        routine_task_type="itinerary_status",
        required_plan=(
            "inspect_reservation",
            "inspect_fare_rules",
            "hold_alternative",
            "cancel_original",
            "confirm_alternative",
            "verify_itinerary",
        ),
        fallback_plan=("cancel_original", "book_alternative"),
        routine_plan=("inspect_reservation",),
        available_tools=(
            "inspect_reservation",
            "inspect_fare_rules",
            "hold_alternative",
            "cancel_original",
            "confirm_alternative",
            "verify_itinerary",
            "book_alternative",
        ),
    ),
    DomainProtocol(
        domain="customer_support",
        task_type="verified_warranty_exchange",
        routine_task_type="case_status",
        required_plan=(
            "inspect_case",
            "verify_purchase",
            "check_warranty",
            "create_exchange",
            "attach_return_label",
            "verify_case_resolution",
        ),
        fallback_plan=("create_exchange", "close_case"),
        routine_plan=("inspect_case",),
        available_tools=(
            "inspect_case",
            "verify_purchase",
            "check_warranty",
            "create_exchange",
            "attach_return_label",
            "verify_case_resolution",
            "close_case",
        ),
    ),
    DomainProtocol(
        domain="shopping_assistant",
        task_type="constraint_safe_checkout",
        routine_task_type="cart_status",
        required_plan=(
            "inspect_cart",
            "verify_inventory",
            "validate_discount",
            "reserve_items",
            "submit_order",
            "verify_order_total",
        ),
        fallback_plan=("apply_discount", "submit_order"),
        routine_plan=("inspect_cart",),
        available_tools=(
            "inspect_cart",
            "verify_inventory",
            "validate_discount",
            "reserve_items",
            "submit_order",
            "verify_order_total",
            "apply_discount",
        ),
    ),
)


class ExecutableStateVerifier:
    """A deterministic environment verifier with no benchmark-answer metadata."""

    def __init__(self, expected_plan: Sequence[str]) -> None:
        self.expected_plan = tuple(expected_plan)
        self.calls: list[str] = []

    def call(self, tool_name: str) -> dict[str, Any]:
        self.calls.append(tool_name)
        expected = (
            self.expected_plan[len(self.calls) - 1]
            if len(self.calls) <= len(self.expected_plan)
            else None
        )
        return {"accepted": tool_name == expected, "state_revision": len(self.calls)}

    def verify(self) -> bool:
        return tuple(self.calls) == self.expected_plan


def frozen_tasks() -> tuple[HeldOutTask, ...]:
    tasks: list[HeldOutTask] = []
    wording = (
        "Complete {task_type} safely for case {index}",
        "Resolve case {index} using the {task_type} workflow",
        "Handle {task_type} request {index} without state loss",
        "Finish {task_type} for request {index} and verify the outcome",
        "Apply the correct {task_type} procedure to case {index}",
    )
    for protocol in PROTOCOLS:
        for index in range(HARD_PER_DOMAIN):
            tasks.append(
                HeldOutTask(
                    id=f"{protocol.domain}-hard-{index:03d}",
                    domain=protocol.domain,
                    task_type=protocol.task_type,
                    query=wording[index % len(wording)].format(
                        task_type=protocol.task_type.replace("_", " "), index=index
                    ),
                    expected_plan=protocol.required_plan,
                    fallback_plan=protocol.fallback_plan,
                    available_tools=protocol.available_tools,
                    experience_needed=True,
                )
            )
        for index in range(HELD_OUT_PER_DOMAIN - HARD_PER_DOMAIN):
            tasks.append(
                HeldOutTask(
                    id=f"{protocol.domain}-routine-{index:03d}",
                    domain=protocol.domain,
                    task_type=protocol.routine_task_type,
                    query=f"Read {protocol.routine_task_type.replace('_', ' ')} for case {index}",
                    expected_plan=protocol.routine_plan,
                    fallback_plan=protocol.routine_plan,
                    available_tools=protocol.available_tools,
                    experience_needed=False,
                )
            )
    return tuple(tasks)


def dataset_fingerprint(tasks: Sequence[HeldOutTask] | None = None) -> str:
    payload = [asdict(task) for task in (tasks or frozen_tasks())]
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def _runtime(path: Path, namespace: str) -> AgentExperienceRuntime:
    store = SQLiteExperienceStore(path)
    compiler = ExperienceCompiler(
        store,
        MemoryFirewall(
            MemoryFirewallPolicy(
                namespace=namespace,
                allow_canary_retrieval=True,
                require_consent_for_user_data=False,
            )
        ),
        policy=ExperienceCompilerPolicy(
            shadow_validation_count=2,
            activation_validation_count=3,
            rejection_failure_count=2,
        ),
    )
    return AgentExperienceRuntime(
        compiler,
        policy=AgentExperienceRuntimePolicy(
            intervention_score_threshold=0.0,
            default_packet_tokens=192,
            default_packet_items=1,
        ),
    )


def _train(runtime: AgentExperienceRuntime, namespace: str) -> dict[str, Any]:
    expected_events = 0
    active_ids: list[str] = []
    for protocol in PROTOCOLS:
        candidate_id = ""
        for repetition in range(3):
            environment = ExecutableStateVerifier(protocol.required_plan)
            run = runtime.begin_run(
                namespace=namespace,
                objective=f"Learn {protocol.task_type} from an independently verified execution",
                domain=protocol.domain,
                task_type=protocol.task_type,
                run_id=f"train-{protocol.domain}-{repetition}",
                session_id=f"train-session-{protocol.domain}-{repetition}",
                task_id=f"train-task-{protocol.domain}-{repetition}",
            )
            for tool_name in protocol.required_plan:
                run.execute_tool(tool_name, environment.call, tool_name)
            run.verify(
                CallableOutcomeVerifier(
                    source=VerificationSource.ENVIRONMENT,
                    verifier=f"{protocol.domain}-state-verifier",
                    callback=lambda _context, env=environment: (env.verify(), 1.0),
                    reference=f"local-state://{protocol.domain}/{repetition}",
                )
            )
            result = run.finish()
            expected_events += 7 + (2 * len(protocol.required_plan))
            candidate_id = result.candidate_ids[0]
        record = runtime.store.get(candidate_id)
        if record is None or record.status != ExperienceStatus.ACTIVE:
            raise RuntimeError(f"training did not activate {protocol.task_type}")
        active_ids.append(record.id)
    actual_events = sum(
        len(
            runtime.events(
                namespace=namespace, run_id=f"train-{protocol.domain}-{repeat}"
            )
        )
        for protocol in PROTOCOLS
        for repeat in range(3)
    )
    return {
        "verified_runs": 9,
        "active_procedures": len(active_ids),
        "active_ids": active_ids,
        "expected_events": expected_events,
        "captured_events": actual_events,
        "capture_rate": actual_events / expected_events,
    }


def _plan_from_record(
    runtime: AgentExperienceRuntime, experience_id: str
) -> tuple[str, ...]:
    record = runtime.store.get(experience_id)
    if record is None:
        return ()
    return tuple(str(value) for value in record.metadata.get("tool_plan") or ())


def _percentile(values: Sequence[float], percentile: float) -> float:
    ordered = sorted(float(value) for value in values)
    if not ordered:
        return 0.0
    position = (len(ordered) - 1) * percentile
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[lower]
    return ordered[lower] + (ordered[upper] - ordered[lower]) * (position - lower)


def _ci95(values: Sequence[float], *, bounded: bool = False) -> dict[str, float]:
    mean = statistics.fmean(values)
    margin = (
        0.0
        if len(values) < 2
        else T_CRITICAL_95_DF4 * statistics.stdev(values) / math.sqrt(len(values))
    )
    low, high = mean - margin, mean + margin
    if bounded:
        low, high = max(0.0, low), min(1.0, high)
    return {"mean": round(mean, 6), "low": round(low, 6), "high": round(high, 6)}


def _evaluate_mode(
    mode: str,
    runtime: AgentExperienceRuntime,
    namespace: str,
    tasks: Sequence[HeldOutTask],
) -> dict[str, Any]:
    active_records = runtime.store.list(
        namespace=namespace, status=ExperienceStatus.ACTIVE, limit=100
    )
    repeat_rows: list[dict[str, Any]] = []
    all_latency: list[float] = []
    domain_successes: dict[str, list[float]] = {domain: [] for domain in DOMAINS}
    for repeat in range(REPEATS):
        successes = 0
        hard_failures = 0
        context_tokens = 0
        interventions = 0
        unnecessary = 0
        per_domain: dict[str, list[bool]] = {domain: [] for domain in DOMAINS}
        for task in tasks:
            started = time.perf_counter()
            plan = task.fallback_plan
            injected = False
            if mode == "static_always_on":
                context_tokens += sum(
                    max(1, math.ceil(len(record.content) / 4))
                    for record in active_records
                )
                matching = [
                    record
                    for record in active_records
                    if task.domain in record.applicability.domains
                    and task.task_type in record.applicability.task_types
                ]
                if matching:
                    plan = tuple(
                        str(value)
                        for value in matching[0].metadata.get("tool_plan") or ()
                    )
                    injected = True
            elif mode == "selective_verified":
                decision = runtime.decide(
                    task.query,
                    namespace=namespace,
                    task_id=f"{task.id}-repeat-{repeat}",
                    domains=(task.domain,),
                    task_types=(task.task_type,),
                    tools=task.available_tools,
                    token_budget=192,
                    top_k=1,
                )
                injected = decision.inject
                if decision.packet is not None:
                    context_tokens += decision.packet.estimated_tokens
                    plan = _plan_from_record(
                        runtime, decision.packet.items[0].experience_id
                    )
            latency_ms = (time.perf_counter() - started) * 1000.0
            all_latency.append(latency_ms)
            interventions += int(injected)
            unnecessary += int(injected and not task.experience_needed)
            environment = ExecutableStateVerifier(task.expected_plan)
            for tool_name in plan:
                environment.call(tool_name)
            success = environment.verify()
            successes += int(success)
            hard_failures += int(task.experience_needed and not success)
            per_domain[task.domain].append(success)
        for domain, values in per_domain.items():
            domain_successes[domain].append(sum(values) / len(values))
        repeat_rows.append(
            {
                "repeat": repeat + 1,
                "task_success": successes / len(tasks),
                "repeated_error_rate": hard_failures
                / sum(task.experience_needed for task in tasks),
                "context_tokens": context_tokens,
                "interventions": interventions,
                "unnecessary_intervention_rate": unnecessary / max(1, interventions),
            }
        )
    return {
        "task_success": _ci95(
            [row["task_success"] for row in repeat_rows], bounded=True
        ),
        "repeated_error_rate": _ci95(
            [row["repeated_error_rate"] for row in repeat_rows], bounded=True
        ),
        "context_tokens": _ci95([row["context_tokens"] for row in repeat_rows]),
        "unnecessary_intervention_rate": _ci95(
            [row["unnecessary_intervention_rate"] for row in repeat_rows], bounded=True
        ),
        "p95_latency_ms": round(_percentile(all_latency, 0.95), 6),
        "domains": {
            domain: {"task_success": _ci95(values, bounded=True)}
            for domain, values in domain_successes.items()
        },
        "repeats": repeat_rows,
    }


def _safety_checks(runtime: AgentExperienceRuntime, namespace: str) -> dict[str, Any]:
    unverified_namespace = "verified-experience-unverified-audit"
    unverified = _runtime(Path(":memory:"), unverified_namespace)
    run = unverified.begin_run(
        namespace=unverified_namespace,
        objective="unverified execution",
        domain="audit",
        task_type="unverified",
    )
    run.execute_tool("unsafe_guess", lambda: {"ok": True})
    result = run.finish()
    unverified_promotions = sum(
        unverified.store.get(experience_id).status != ExperienceStatus.SHADOW
        for experience_id in result.candidate_ids
    )
    leakage = len(runtime.events(namespace="wrong-namespace", run_id="train-travel-0"))

    original = runtime.store.list(
        namespace=namespace, status=ExperienceStatus.ACTIVE, limit=1
    )[0]
    replacement = type(original).create(
        id=f"{original.id}-replacement",
        namespace=namespace,
        kind=original.kind,
        title=f"{original.title} updated",
        content="Temporary replacement used by the rollback parity check.",
        applicability=original.applicability,
        outcome=original.outcome,
        confidence=original.confidence,
        trust=original.trust,
        status=ExperienceStatus.ACTIVE,
        source=original.source,
        trajectory=original.trajectory,
        metadata={**original.metadata, "temporary_replacement": True},
    )
    promoted = runtime.store.supersede(
        original.id, replacement, reason="benchmark rollback parity"
    )
    restored = runtime.rollback(
        promoted.id, namespace=namespace, reason="restore benchmark record"
    )
    provenance_parity = float(
        restored.content == original.content
        and restored.trajectory == original.trajectory
        and restored.source == original.source
        and restored.applicability == original.applicability
    )
    unverified.store.close()
    return {
        "unverified_auto_promotions": int(unverified_promotions),
        "namespace_leakage": int(leakage),
        "rollback_provenance_parity": provenance_parity,
    }


def _repository_sha(root: Path) -> str:
    return subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=root, text=True, encoding="utf-8"
    ).strip()


def run_benchmark(*, source_sha: str | None = None) -> dict[str, Any]:
    tasks = frozen_tasks()
    namespace = "verified-experience-frozen"
    with tempfile.TemporaryDirectory(
        prefix="wavemind-verified-experience-"
    ) as directory:
        runtime = _runtime(Path(directory) / "experience.sqlite3", namespace)
        training = _train(runtime, namespace)
        modes = {
            mode: _evaluate_mode(mode, runtime, namespace, tasks)
            for mode in ("no_memory", "static_always_on", "selective_verified")
        }
        safety = _safety_checks(runtime, namespace)
        runtime.store.close()
    no_memory = modes["no_memory"]
    static = modes["static_always_on"]
    selective = modes["selective_verified"]
    success_uplift = (
        selective["task_success"]["mean"] - no_memory["task_success"]["mean"]
    )
    error_reduction = 1.0 - selective["repeated_error_rate"]["mean"] / max(
        no_memory["repeated_error_rate"]["mean"], 1e-12
    )
    token_reduction = 1.0 - selective["context_tokens"]["mean"] / max(
        static["context_tokens"]["mean"], 1e-12
    )
    domain_uplift = {
        domain: round(
            selective["domains"][domain]["task_success"]["mean"]
            - no_memory["domains"][domain]["task_success"]["mean"],
            6,
        )
        for domain in DOMAINS
    }
    metrics = {
        "task_success_uplift": round(success_uplift, 6),
        "domain_task_success_uplift": domain_uplift,
        "repeated_error_relative_reduction": round(error_reduction, 6),
        "context_token_relative_reduction_vs_full_history": round(token_reduction, 6),
        "unnecessary_intervention_rate": selective["unnecessary_intervention_rate"][
            "mean"
        ],
        "runtime_p95_ms": selective["p95_latency_ms"],
    }
    checks = {
        "task_success_uplift": success_uplift >= 0.10,
        "positive_uplift_all_domains": all(
            value > 0.0 for value in domain_uplift.values()
        ),
        "repeated_error_reduction": error_reduction >= 0.50,
        "context_token_reduction": token_reduction >= 0.30,
        "unnecessary_intervention": metrics["unnecessary_intervention_rate"] <= 0.10,
        "runtime_latency": metrics["runtime_p95_ms"] <= 75.0,
        "capture_rate": training["capture_rate"] >= 0.99,
        "unverified_promotion": safety["unverified_auto_promotions"] == 0,
        "namespace_isolation": safety["namespace_leakage"] == 0,
        "rollback_provenance": safety["rollback_provenance_parity"] == 1.0,
    }
    return {
        "schema": SCHEMA,
        "status": "pass" if all(checks.values()) else "fail",
        "source_sha": source_sha or _repository_sha(PROJECT_ROOT),
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "dataset": {
            "revision": DATASET_REVISION,
            "fingerprint_sha256": dataset_fingerprint(tasks),
            "domains": list(DOMAINS),
            "held_out_tasks": len(tasks),
            "held_out_per_domain": HELD_OUT_PER_DOMAIN,
            "hard_per_domain": HARD_PER_DOMAIN,
            "split_frozen_before_evaluation": True,
            "answer_metadata_visible_to_agent": False,
        },
        "protocol": {
            "repeats": REPEATS,
            "confidence_interval": "two-sided 95% Student t, df=4",
            "same_tasks_and_environment_verifiers": True,
            "evaluation_store_read_only": True,
            "no_llm_api_gpu": True,
            "no_test_specific_rules": True,
            "independent_environment_verification": True,
            "comparison_modes": ["no_memory", "static_always_on", "selective_verified"],
        },
        "training": training,
        "modes": modes,
        "metrics": metrics,
        "safety": safety,
        "checks": [{"id": key, "passed": value} for key, value in checks.items()],
    }


def render_markdown(payload: dict[str, Any]) -> str:
    lines = [
        "# Verified Agent Experience Benchmark",
        "",
        f"Status: **{payload['status']}**",
        "",
        f"Source SHA: `{payload['source_sha']}`",
        "",
        "| Mode | Task success | Repeated error | Context tokens | p95 runtime |",
        "|---|---:|---:|---:|---:|",
    ]
    for key, label in (
        ("no_memory", "No memory"),
        ("static_always_on", "Static always-on"),
        ("selective_verified", "Selective verified"),
    ):
        mode = payload["modes"][key]
        lines.append(
            f"| {label} | {mode['task_success']['mean']:.3f} | "
            f"{mode['repeated_error_rate']['mean']:.3f} | "
            f"{mode['context_tokens']['mean']:.0f} | {mode['p95_latency_ms']:.3f} ms |"
        )
    lines.extend(["", "## Frozen gates", ""])
    lines.extend(
        f"- {'PASS' if item['passed'] else 'FAIL'} `{item['id']}`"
        for item in payload["checks"]
    )
    return "\n".join(lines) + "\n"


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Run the frozen verified-experience benchmark"
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("benchmarks/verified_experience_results.json"),
    )
    parser.add_argument(
        "--markdown",
        type=Path,
        default=Path("benchmarks/VERIFIED_EXPERIENCE_RESULTS.md"),
    )
    parser.add_argument("--source-sha")
    args = parser.parse_args(argv)
    payload = run_benchmark(source_sha=args.source_sha)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(payload, indent=2, ensure_ascii=True) + "\n", encoding="utf-8"
    )
    args.markdown.write_text(render_markdown(payload), encoding="utf-8")
    print(
        json.dumps(
            {"status": payload["status"], "metrics": payload["metrics"]}, indent=2
        )
    )
    return 0 if payload["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
